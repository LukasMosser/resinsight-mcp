"""Prove two real application sessions through an explicitly supplied P05 transport."""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

import grpc
import psutil
import rips
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from PIL import Image

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.errors import ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    CloseAction,
    CloseRequest,
    Connection,
    LaunchRequest,
    ObjectKind,
    ProjectCloseRequest,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


class Trial:
    def __init__(self, output: Path, executable: Path, case: Path, transport_source: Path) -> None:
        self.output = output
        self.executable = executable
        self.case = case
        self.transport_source = transport_source
        self.connections: list[Connection] = []
        self.projects: list[ProjectState] = []

    def event(self, event_name: str, **details: Any) -> None:
        record = {"time": datetime.now(UTC).isoformat(), "event": event_name, **details}
        with (self.output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    async def call[T: Record](
        self, client: ClientSession, tool: str, arguments: dict[str, Any], result_type: type[T]
    ) -> T:
        response = await client.call_tool(tool, arguments)
        assert response.content and isinstance(response.content[0], TextContent)
        result = OperationResult[dict[str, Any]].model_validate_json(response.content[0].text)
        assert response.structuredContent == result.model_dump(mode="json")
        assert not response.isError, response.model_dump_json()
        return result_type.model_validate_json(json.dumps(value(result)))

    async def request[T: Record](
        self, client: ClientSession, tool: str, request: Record, result_type: type[T]
    ) -> T:
        return await self.call(client, tool, request.model_dump(mode="json"), result_type)

    async def stale(self, client: ClientSession, project: ProjectState) -> None:
        response = await client.call_tool(
            "object_resolve", project.objects[0].ref.model_dump(mode="json")
        )
        assert response.isError
        assert response.structuredContent is not None
        error = response.structuredContent["outcome"]["error"]
        assert error["code"] == "stale_object", error
        self.event("stale_reference_rejected", context=project.context.model_dump(mode="json"))

    def seed(self, connection: Connection, name: str) -> None:
        endpoint = connection.endpoint
        with grpc.insecure_channel(f"{endpoint.host}:{endpoint.port}") as channel:
            project = cast(Any, rips.Project).create(channel)
            case = project.load_case(str(self.case))
            case.name = name
            case.update()
            view = case.create_view()
            view.apply_cell_result("DYNAMIC_NATIVE", "PRESSURE")
            view.set_time_step(0)
            view.grid_z_scale = 20
            view.update()
            folder = self.output / name
            folder.mkdir()
            view.export_snapshot(export_folder=str(folder), width=1200, height=800)
            snapshots = tuple(folder.glob("*.png"))
            assert len(snapshots) == 1
            with Image.open(snapshots[0]) as picture:
                picture.load()
                assert picture.size == (1200, 800)
            self.event("native_case_seeded", name=name, snapshot=str(snapshots[0]))

    async def build_session(self, client: ClientSession, name: str) -> None:
        session = Session(session_id=SessionId.new(), name=name)
        await self.request(client, "session_create", session, Session)
        connection = await self.request(
            client,
            "application_launch",
            LaunchRequest(session_id=session.session_id, executable=self.executable),
            Connection,
        )
        self.connections.append(connection)
        self.event("application_launched", connection=connection.model_dump(mode="json"))
        self.seed(connection, name)
        project = await self.call(
            client, "project_inspect", {"session_id": str(session.session_id)}, ProjectState
        )
        assert {item.name for item in project.objects if item.ref.kind == ObjectKind.CASE} == {name}
        destination = self.output / f"{name}.rsp"
        saved = await self.request(
            client,
            "project_save",
            ProjectSaveRequest(context=project.context, path=destination),
            ProjectState,
        )
        document = ElementTree.parse(destination)
        assert name in tuple(element.text for element in document.iter())
        assert saved.last_saved_path == destination
        await self.stale(client, project)
        reopened = await self.request(
            client,
            "project_open",
            ProjectOpenRequest(context=saved.context, path=destination),
            ProjectState,
        )
        assert {item.name for item in reopened.objects if item.ref.kind == ObjectKind.CASE} == {
            name
        }
        assert reopened.context.project_generation > saved.context.project_generation
        self.projects.append(reopened)
        self.event(
            "project_saved_and_reopened", name=name, project=reopened.model_dump(mode="json")
        )

    async def external_change(self, client: ClientSession) -> None:
        first, second = self.connections
        with grpc.insecure_channel(f"127.0.0.1:{first.endpoint.port}") as channel:
            project = cast(Any, rips.Project).create(channel)
            case = project.cases()[0]
            case.name = "P04 external change"
            case.update()
        await self.stale(client, self.projects[0])
        current = await self.call(
            client,
            "project_inspect",
            {"session_id": str(first.context.session_id)},
            ProjectState,
        )
        assert any(item.name == "P04 external change" for item in current.objects)
        unchanged = await self.call(
            client,
            "project_inspect",
            {"session_id": str(second.context.session_id)},
            ProjectState,
        )
        assert unchanged == self.projects[1]
        blank = await self.request(
            client, "project_close", ProjectCloseRequest(context=current.context), ProjectState
        )
        assert not blank.objects
        self.projects[0] = await self.request(
            client,
            "project_open",
            ProjectOpenRequest(context=blank.context, path=self.output / "P04 first.rsp"),
            ProjectState,
        )
        self.event("external_change_detected_and_sessions_isolated")

    async def protocol(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("server.py")), str(self.output)],
            env={**os.environ, "PYTHONPATH": str(self.transport_source)},
        )
        with (self.output / "mcp-stderr.log").open("w") as errors:
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=180)
                ) as client:
                    await client.initialize()
                    for name in ("P04 first", "P04 second"):
                        await self.build_session(client, name)
                    assert self.connections[0].process != self.connections[1].process
                    await self.external_change(client)
        self.event("mcp_client_disconnected")

    def reconnect(self) -> None:
        store = SqliteWorkspaceStore.open(self.output / "workspace")
        sessions = ResInsightSessionService(store, RipsApplicationFactory(self.output / "new-logs"))
        for old in self.connections:
            assert old.process is not None
            process = psutil.Process(old.process.pid)
            assert str(process.create_time()) == old.process.start_marker
            attached = value(
                sessions.attach(
                    AttachRequest(session_id=old.context.session_id, endpoint=old.endpoint)
                )
            )
            assert attached.process == old.process
            assert attached.context.connection_id != old.context.connection_id
            project = value(sessions.inspect_project(old.context.session_id))
            previous = next(
                p for p in self.projects if p.context.session_id == old.context.session_id
            )
            assert {item.name for item in project.objects} == {
                item.name for item in previous.objects
            }
            rejection = sessions.resolve_object(previous.objects[0].ref)
            assert isinstance(rejection.outcome, Failure)
            assert rejection.outcome.error.code == ErrorCode.STALE_OBJECT
            value(
                sessions.close(
                    CloseRequest(
                        session_id=old.context.session_id,
                        connection_id=attached.context.connection_id,
                    )
                )
            )
            assert process.is_running()
            self.event("attached_detach_survived", connection=attached.model_dump(mode="json"))
        assert len(value(store.list_sessions())) == 2

    def cleanup(self) -> None:
        sessions = ResInsightSessionService(
            SqliteWorkspaceStore.open(self.output / "workspace"),
            RipsApplicationFactory(self.output / "cleanup-logs"),
        )
        for old in self.connections:
            attached = value(
                sessions.attach(
                    AttachRequest(session_id=old.context.session_id, endpoint=old.endpoint)
                )
            )
            value(
                sessions.close(
                    CloseRequest(
                        session_id=old.context.session_id,
                        connection_id=attached.context.connection_id,
                        action=CloseAction.TERMINATE,
                    ),
                    attached_termination_authorized=True,
                )
            )
            self.event("test_application_terminated", pid=old.process.pid if old.process else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport-source", type=Path, required=True)
    parser.add_argument("--keep-applications", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir()
    SqliteWorkspaceStore.create(arguments.output / "workspace")
    trial = Trial(
        arguments.output, arguments.executable, arguments.case, arguments.transport_source
    )
    environment = {
        "started_at": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "platform": platform.platform(),
        "python": sys.version,
        "versions": {name: version(name) for name in ("rips", "psutil", "mcp", "grpcio")},
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    }
    (arguments.output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    asyncio.run(trial.protocol())
    trial.reconnect()
    trial.event("acceptance_passed", applications=2, projects=2)
    if not arguments.keep_applications:
        trial.cleanup()


if __name__ == "__main__":
    main()
