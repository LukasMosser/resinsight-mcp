"""Attach production view services to the trial's real stored result and application."""

import argparse
import asyncio
import base64
import json
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from resinsight_mcp.resinsight.views.service import ResInsightViewService

from resinsight_mcp.contracts.errors import ContractError, Failure, OperationResult
from resinsight_mcp.contracts.jobs import LoadedResult
from resinsight_mcp.contracts.sessions import AttachRequest, CloseRequest, ObjectKind
from resinsight_mcp.mcp import Bindings, serve_stdio
from resinsight_mcp.mcp import server as protocol
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
from resinsight_mcp.resinsight.sessions.service import ResInsightSessionService
from resinsight_mcp.resinsight.views.rips import RipsViewBackend
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .run_observer import Trial, exact_object


def value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def serve(trial: Trial, evidence: Path) -> None:
    """Detach this client on exit; the trial owner retains process ownership."""
    store = SqliteWorkspaceStore.open(trial.workspace)
    sessions = ResInsightSessionService(store, RipsApplicationFactory(trial.application_logs))
    connection = value(
        sessions.attach(AttachRequest(session_id=trial.session_id, endpoint=trial.endpoint))
    )
    try:
        project = value(sessions.inspect_project(trial.session_id))
        case = exact_object(project, ObjectKind.CASE, trial.case_name)
        result = value(store.get_result(trial.session_id, trial.result_id))
        views = ResInsightViewService(store, sessions, RipsViewBackend())
        loaded = LoadedResult(case=case, result=result)
        assert value(views.bind_result(loaded)) == loaded
        (evidence / "server-binding.json").write_text(
            json.dumps(
                {
                    "connection": connection.model_dump(mode="json"),
                    "project": project.model_dump(mode="json"),
                    "loaded_result": loaded.model_dump(mode="json"),
                },
                indent=2,
            )
            + "\n"
        )
        original = protocol._call
        guard = Lock()
        count = 0

        def record(operation, arguments, bindings):
            nonlocal count
            response = original(operation, arguments, bindings)
            with guard:
                index = count
                count += 1
                payload = {
                    "tool": operation.name,
                    "arguments": arguments,
                    "response": response.model_dump(mode="json"),
                }
                with (evidence / "server-responses.jsonl").open("a") as stream:
                    stream.write(json.dumps(payload) + "\n")
                for item in response.content:
                    if item.type == "image":
                        (evidence / f"native-{index:02d}.png").write_bytes(
                            base64.b64decode(item.data, validate=True)
                        )
            return response

        with patch.object(protocol, "_call", record):
            asyncio.run(serve_stdio(Bindings(workspaces=store, sessions=sessions, views=views)))
    finally:
        detached = sessions.close(
            CloseRequest(
                session_id=trial.session_id, connection_id=connection.context.connection_id
            )
        )
        (evidence / "server-detach.json").write_text(detached.model_dump_json(indent=2) + "\n")
        value(detached)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    serve(Trial.model_validate_json(arguments.trial.read_text()), arguments.evidence)
