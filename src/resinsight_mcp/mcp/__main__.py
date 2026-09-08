"""Launch workspace operations over local standard input and output."""

import argparse
import asyncio
import logging
from pathlib import Path

from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .catalog import Bindings
from .stdio import serve_stdio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--create-workspace", action="store_true")
    arguments = parser.parse_args()
    if not arguments.workspace_root.is_absolute():
        parser.error("The workspace root must be an absolute path.")
    logging.basicConfig(level=logging.INFO)
    factory = (
        SqliteWorkspaceStore.create if arguments.create_workspace else SqliteWorkspaceStore.open
    )
    asyncio.run(serve_stdio(Bindings(workspaces=factory(arguments.workspace_root))))


if __name__ == "__main__":
    main()
