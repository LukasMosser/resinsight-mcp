"""Typed JSON records with session-qualified identities."""

import sqlite3

from pydantic import ValidationError

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode
from resinsight_mcp.contracts.jobs import Job, Result
from resinsight_mcp.contracts.models import ModelRevision, Session
from resinsight_mcp.contracts.observations import Observation
from resinsight_mcp.contracts.workspace import Artifact, ProjectCheckpoint

_KINDS: dict[type[Record], str] = {
    Session: "session",
    Artifact: "artifact",
    ModelRevision: "revision",
    Job: "job",
    Result: "result",
    Observation: "observation",
    ProjectCheckpoint: "checkpoint",
}


def fail(code: ErrorCode, message: str) -> ContractError:
    return ContractError(Error(code=code, message=message))


def identity(value: Record) -> tuple[str, str]:
    if isinstance(value, Session):
        return str(value.session_id), str(value.session_id)
    if isinstance(value, Artifact):
        return str(value.ref.session_id), str(value.ref.artifact_id)
    if isinstance(value, ModelRevision):
        return str(value.model.session_id), str(value.model.revision_id)
    if isinstance(value, Job):
        return str(value.model.session_id), str(value.job_id)
    if isinstance(value, Result):
        return str(value.model.session_id), str(value.result_id)
    if isinstance(value, Observation):
        return str(value.context.model.session_id), str(value.observation_id)
    if isinstance(value, ProjectCheckpoint):
        return str(value.model.session_id), str(value.checkpoint_id)
    raise TypeError("This record type has no workspace identity.")


def _decode[T: Record](record_type: type[T], payload: str, session: str, record_id: str) -> T:
    try:
        record = record_type.model_validate_json(payload)
    except ValidationError as error:
        raise fail(
            ErrorCode.CORRUPT_WORKSPACE, "A stored record failed contract validation."
        ) from error
    if identity(record) != (session, record_id):
        raise fail(
            ErrorCode.CORRUPT_WORKSPACE, "A stored record has a different identity from its key."
        )
    return record


def find[T: Record](
    connection: sqlite3.Connection, record_type: type[T], session: str, record_id: str
) -> T | None:
    if record_type is Session:
        row = connection.execute(
            "SELECT payload FROM sessions WHERE session_id = ?", (session,)
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT payload FROM records WHERE kind = ? AND session_id = ? AND record_id = ?",
            (_KINDS[record_type], session, record_id),
        ).fetchone()
    return None if row is None else _decode(record_type, row[0], session, record_id)


def require[T: Record](
    connection: sqlite3.Connection, record_type: type[T], session: str, record_id: str
) -> T:
    record = find(connection, record_type, session, record_id)
    if record is None:
        raise fail(ErrorCode.NOT_FOUND, f"The requested {_KINDS[record_type]} does not exist here.")
    return record


def all_records[T: Record](
    connection: sqlite3.Connection, record_type: type[T], session: str | None = None
) -> tuple[T, ...]:
    if record_type is Session:
        rows = connection.execute(
            "SELECT session_id, session_id, payload FROM sessions ORDER BY session_id"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT session_id, record_id, payload FROM records "
            "WHERE kind = ? AND session_id = ? ORDER BY record_id",
            (_KINDS[record_type], session),
        ).fetchall()
    return tuple(_decode(record_type, row[2], row[0], row[1]) for row in rows)


def insert[T: Record](connection: sqlite3.Connection, record: T) -> T:
    record = type(record).model_validate(record)
    session, record_id = identity(record)
    if isinstance(record, Session):
        connection.execute(
            "INSERT INTO sessions (session_id, payload) VALUES (?, ?)",
            (session, record.model_dump_json()),
        )
    else:
        connection.execute(
            "INSERT INTO records (kind, session_id, record_id, payload) VALUES (?, ?, ?, ?)",
            (_KINDS[type(record)], session, record_id, record.model_dump_json()),
        )
    return record


def immutable[T: Record](connection: sqlite3.Connection, record: T) -> T:
    session, record_id = identity(record)
    previous = find(connection, type(record), session, record_id)
    if previous is not None:
        if previous != record:
            raise fail(ErrorCode.CONFLICT, "An immutable record already uses this identity.")
        return previous
    return insert(connection, record)


def replace_job(connection: sqlite3.Connection, job: Job) -> None:
    session, record_id = identity(job)
    connection.execute(
        "UPDATE records SET payload = ? WHERE kind = 'job' AND session_id = ? AND record_id = ?",
        (job.model_dump_json(), session, record_id),
    )
