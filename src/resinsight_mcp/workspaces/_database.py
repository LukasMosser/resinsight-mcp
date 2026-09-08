"""SQLite transactions for one local workspace."""

import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect

from ._files import FileArea

SCHEMA_VERSION = 1
APPLICATION_ID = 0x524D4350
_COLUMNS = {
    "sessions": (("session_id", "TEXT", 1, 1), ("payload", "TEXT", 1, 0)),
    "records": (
        ("kind", "TEXT", 1, 1),
        ("session_id", "TEXT", 1, 2),
        ("record_id", "TEXT", 1, 3),
        ("payload", "TEXT", 1, 0),
    ),
}


def _database_error(error: sqlite3.Error, effect: MutationEffect) -> ContractError:
    name = getattr(error, "sqlite_errorname", "")
    if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")):
        code = ErrorCode.BUSY
    elif name.startswith(("SQLITE_CORRUPT", "SQLITE_NOTADB")):
        code = ErrorCode.CORRUPT_WORKSPACE
    else:
        code = ErrorCode.STORAGE_FAILED
    return ContractError(
        Error(code=code, message=f"The workspace database operation failed: {error}", effect=effect)
    )


class Database:
    def __init__(self, files: FileArea, timeout: float) -> None:
        self.check_timeout(timeout)
        self.files = files
        self.timeout = timeout

    @staticmethod
    def check_timeout(timeout: float) -> None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("The database timeout must be finite and nonnegative.")

    def _connect(self) -> sqlite3.Connection:
        self.files.check_database_files()
        connection = None
        try:
            connection = sqlite3.connect(
                self.files.database_path.as_uri() + "?mode=rw",
                timeout=self.timeout,
                uri=True,
                autocommit=True,
            )
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise _database_error(error, MutationEffect.NOT_APPLIED) from error

    @staticmethod
    def _verify(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ContractError(
                Error(
                    code=ErrorCode.UNSUPPORTED_SCHEMA,
                    message=f"Unsupported workspace schema {version}. Expected {SCHEMA_VERSION}.",
                )
            )
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise ContractError(
                Error(
                    code=ErrorCode.CORRUPT_WORKSPACE,
                    message="This database does not have the workspace application identity.",
                )
            )
        Database._verify_tables(connection)
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ContractError(
                Error(
                    code=ErrorCode.UNSUPPORTED_SCHEMA,
                    message="This workspace requires SQLite rollback-journal mode.",
                )
            )

    @staticmethod
    def _verify_tables(connection: sqlite3.Connection) -> None:
        for table, expected in _COLUMNS.items():
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            observed = tuple((row[1], row[2], row[3], row[5]) for row in columns)
            if observed != expected:
                raise ContractError(
                    Error(
                        code=ErrorCode.CORRUPT_WORKSPACE,
                        message=f"The {table} table does not match the workspace schema.",
                    )
                )
        relationships = connection.execute("PRAGMA foreign_key_list(records)").fetchall()
        expected_relationship = (
            0,
            0,
            "sessions",
            "session_id",
            "session_id",
            "NO ACTION",
            "NO ACTION",
            "NONE",
        )
        if relationships != [expected_relationship]:
            raise ContractError(
                Error(
                    code=ErrorCode.CORRUPT_WORKSPACE,
                    message="The workspace schema does not enforce record session ownership.",
                )
            )

    @staticmethod
    def _close(connection: sqlite3.Connection) -> None:
        try:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
        except sqlite3.Error as error:
            raise _database_error(error, MutationEffect.UNKNOWN) from error
        finally:
            connection.close()

    @contextmanager
    def transaction(
        self, *, write: bool = False, verify: bool = True
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        committing = False
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if verify:
                self._verify(connection)
            yield connection
            committing = write
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            effect = MutationEffect.UNKNOWN if committing else MutationEffect.NOT_APPLIED
            raise _database_error(error, effect) from error
        finally:
            self._close(connection)

    def initialize(self) -> None:
        self.files.create_database_file()
        with self.transaction(write=True, verify=False) as connection:
            connection.execute(
                "CREATE TABLE sessions "
                "(session_id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                """CREATE TABLE records (
                    kind TEXT NOT NULL CHECK (
                      kind IN ('artifact', 'revision', 'job', 'result', 'observation', 'checkpoint')
                    ),
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (kind, session_id, record_id)
                )"""
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")

    def inspect(self) -> None:
        with self.transaction() as connection:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ContractError(
                    Error(
                        code=ErrorCode.CORRUPT_WORKSPACE,
                        message="SQLite reported an inconsistent workspace database.",
                    )
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ContractError(
                    Error(
                        code=ErrorCode.CORRUPT_WORKSPACE,
                        message="A workspace record refers to a missing session.",
                    )
                )
