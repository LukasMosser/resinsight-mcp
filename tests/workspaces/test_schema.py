"""Opening a store never silently creates or migrates an incompatible database."""

import sqlite3
from pathlib import Path

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value


@pytest.mark.parametrize("version", [0, 2])
def test_unsupported_schema_is_rejected_without_migration(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path, version: int
) -> None:
    database = tmp_path / "workspace" / "workspace.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    with pytest.raises(ContractError) as unsupported:
        SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert unsupported.value.error.code == ErrorCode.UNSUPPORTED_SCHEMA
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        connection.execute("PRAGMA user_version = 1")
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert value(reopened.get_session(session.session_id)) == session


def test_unrelated_database_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "unrelated"
    root.mkdir()
    (root / "artifacts").mkdir()
    database = root / "workspace.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE notes (message TEXT)")
        connection.execute("INSERT INTO notes VALUES ('Keep this unrelated study')")
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(ContractError) as unrelated:
        SqliteWorkspaceStore.open(root)
    assert unrelated.value.error.code == ErrorCode.CORRUPT_WORKSPACE
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT message FROM notes").fetchone()[0]
            == "Keep this unrelated study"
        )


def test_open_missing_store_does_not_create_one(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    with pytest.raises(ContractError):
        SqliteWorkspaceStore.open(root)
    assert not root.exists()


def test_create_rejects_existing_workspace_without_erasing_records(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path
) -> None:
    with pytest.raises(ContractError):
        SqliteWorkspaceStore.create(tmp_path / "workspace")
    assert value(store.get_session(session.session_id)) == session


@pytest.mark.parametrize("timeout", [-1.0, float("nan"), float("inf")])
def test_invalid_timeout_does_not_create_partial_workspace(tmp_path: Path, timeout: float) -> None:
    root = tmp_path / "invalid-timeout"
    with pytest.raises(ValueError):
        SqliteWorkspaceStore.create(root, timeout=timeout)
    assert not root.exists()
