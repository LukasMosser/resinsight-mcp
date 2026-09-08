"""Helpers use public records and independent Python processes."""

import io
import json
import select
import subprocess
import sys
from pathlib import Path
from typing import Any

from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](outcome: OperationResult[T]) -> T:
    """Require a successful public operation and return its record."""
    assert isinstance(outcome.outcome, Success), outcome.model_dump(mode="json")
    return outcome.outcome.value


def write_json(
    store: SqliteWorkspaceStore,
    session: Session,
    name: str,
    content: object,
    kind: ArtifactKind = ArtifactKind.INPUT,
) -> Artifact:
    artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path=name,
        kind=kind,
    )
    return value(store.write_artifact(artifact, io.BytesIO(json.dumps(content).encode("utf-8"))))


def workers(
    action: str, root: Path, payloads: list[dict[str, Any]], tmp_path: Path
) -> list[dict[str, Any]]:
    processes = []
    try:
        for index, payload in enumerate(payloads):
            path = tmp_path / f"worker-{index}.json"
            path.write_text(json.dumps(payload))
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("worker.py")),
                    action,
                    str(root),
                    str(path),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
        for process in processes:
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 15)[0], "Writer did not become ready."
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("go\n")
            process.stdin.flush()
        outcomes = []
        for process in processes:
            output, errors = process.communicate(timeout=15)
            assert process.returncode == 0, errors
            outcomes.append(json.loads(output))
        return outcomes
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
