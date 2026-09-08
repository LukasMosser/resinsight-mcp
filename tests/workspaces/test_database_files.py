"""Public reads tolerate journal deletion and reject unsafe database entries."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.workspaces import SqliteWorkspaceStore, _files

from ._support import value


def test_read_accepts_journal_deleted_during_metadata_check(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    updated = session.model_copy(update={"name": "Committed journal update"})
    original = _files._entry_info
    observations: list[os.stat_result] = []
    with closing(sqlite3.connect(root / "workspace.sqlite3")) as writer:
        writer.execute(
            "UPDATE sessions SET payload = ? WHERE session_id = ?",
            (updated.model_dump_json(), str(session.session_id)),
        )
        with (root / "workspace.sqlite3-journal").open("rb") as journal:

            def observe(name: str, parent: int) -> os.stat_result | None:
                if name != "workspace.sqlite3-journal":
                    return original(name, parent)
                # Commit deletes the real journal while its metadata is being observed.
                writer.commit()
                info = os.fstat(journal.fileno())
                assert info.st_nlink == 0
                observations.append(info)
                return info

            monkeypatch.setattr(_files, "_entry_info", observe)
            assert value(store.get_session(session.session_id)) == updated
    assert len(observations) == 1


def test_read_rejects_unlinked_main_database(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "workspace" / "workspace.sqlite3"
    original = _files._entry_info
    with database.open("rb") as handle:
        database.unlink()
        info = os.fstat(handle.fileno())
        assert info.st_nlink == 0

        def observe(name: str, parent: int) -> os.stat_result | None:
            return info if name == database.name else original(name, parent)

        monkeypatch.setattr(_files, "_entry_info", observe)
        outcome = store.get_session(session.session_id).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.INVALID_PATH


@pytest.mark.parametrize("name", ["workspace.sqlite3", "workspace.sqlite3-journal"])
@pytest.mark.parametrize("kind", ["hardlink", "symlink", "directory", "fifo"])
def test_read_rejects_unsafe_database_entries(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path, name: str, kind: str
) -> None:
    entry = tmp_path / "workspace" / name
    outside = tmp_path / "outside"
    if entry.exists():
        entry.rename(outside)
    else:
        outside.touch()
    if kind == "hardlink":
        os.link(outside, entry)
    elif kind == "symlink":
        entry.symlink_to(outside)
    elif kind == "directory":
        entry.mkdir()
    else:
        os.mkfifo(entry)
    outcome = store.get_session(session.session_id).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.INVALID_PATH
