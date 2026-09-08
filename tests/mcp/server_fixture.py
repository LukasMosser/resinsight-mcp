"""Run a real protocol server with explicit test services."""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.observations import Observation, RenderRequest
from resinsight_mcp.mcp import Bindings, serve_stdio
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class NoisyStore(SqliteWorkspaceStore):
    def get_session(self, session_id: SessionId) -> OperationResult[Session]:
        print("fixture service print", flush=True)
        logging.warning("fixture service log")
        subprocess.run(
            [sys.executable, "-c", "print('fixture child output', flush=True)"], check=True
        )
        return super().get_session(session_id)


class BrokenStore(SqliteWorkspaceStore):
    def create_session(self, session: Session) -> OperationResult[Session]:
        raise RuntimeError("private-service-secret")

    def list_sessions(self) -> OperationResult[tuple[Session, ...]]:
        raise RuntimeError("private-service-secret")


class ContractFailureStore(SqliteWorkspaceStore):
    def list_sessions(self) -> OperationResult[tuple[Session, ...]]:
        raise ContractError(Error(code=ErrorCode.BUSY, message="The workspace is busy."))


class SavedRenderer:
    """Return a supplied observation without claiming a ResInsight render."""

    def __init__(self, path: Path) -> None:
        self.observation = Observation.model_validate_json(path.read_text())

    def render(self, request: RenderRequest) -> OperationResult[Observation]:
        assert request.context == self.observation.context
        assert (request.width, request.height) == (
            self.observation.image.width,
            self.observation.image.height,
        )
        return OperationResult(outcome=Success(value=self.observation))


class UnrelatedRenderer(SavedRenderer):
    """Return an unrelated image to exercise transport isolation."""

    def render(self, request: RenderRequest) -> OperationResult[Observation]:
        return OperationResult(outcome=Success(value=self.observation))


async def main() -> None:
    root = Path(sys.argv[1])
    mode = sys.argv[2]
    store_type = {
        "plain": SqliteWorkspaceStore,
        "noisy": NoisyStore,
        "broken": BrokenStore,
        "contract": ContractFailureStore,
        "render": SqliteWorkspaceStore,
        "unrelated-render": SqliteWorkspaceStore,
    }[mode]
    store = store_type.open(root)
    renderers = {"render": SavedRenderer, "unrelated-render": UnrelatedRenderer}
    renderer = renderers[mode](Path(sys.argv[3])) if mode in renderers else None
    await serve_stdio(Bindings(workspaces=store, renderer=renderer))


if __name__ == "__main__":
    asyncio.run(main())
