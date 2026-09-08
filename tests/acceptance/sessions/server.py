"""Compose the P04 service with an explicitly supplied P05 transport checkout."""

import asyncio
import importlib
import logging
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Protocol, cast

from resinsight_mcp.contracts.interfaces import SessionService, WorkspaceStore
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class Transport(Protocol):
    def Bindings(self, *, workspaces: WorkspaceStore, sessions: SessionService) -> object: ...

    def serve_stdio(self, bindings: object) -> Coroutine[Any, Any, None]: ...


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    root = Path(sys.argv[1])
    workspaces = SqliteWorkspaceStore.open(root / "workspace")
    sessions = ResInsightSessionService(
        workspaces, RipsApplicationFactory(root / "application-logs")
    )
    transport = cast(Transport, importlib.import_module("resinsight_mcp.mcp"))
    asyncio.run(transport.serve_stdio(transport.Bindings(workspaces=workspaces, sessions=sessions)))


if __name__ == "__main__":
    main()
