"""Application connection identity, state, and process ownership."""

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from ._base import Record, Text
from .errors import ContractError, Error, ErrorCode
from .identifiers import ConnectionId, SessionId


class ApplicationContext(Record):
    session_id: SessionId
    connection_id: ConnectionId
    project_generation: NonNegativeInt


class ObjectKind(StrEnum):
    CASE = "case"
    VIEW = "view"
    WELL = "well"


class ObjectRef(Record):
    context: ApplicationContext
    kind: ObjectKind
    object_id: Text

    def require_current(self, current: ApplicationContext) -> None:
        """Reject handles from another session, connection, or project generation."""
        if self.context != current:
            raise ContractError(
                Error(
                    code=ErrorCode.STALE_OBJECT, message="The object context is no longer current."
                )
            )


class Endpoint(Record):
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65535)


class ProcessOwnership(StrEnum):
    OWNED = "owned"
    ATTACHED = "attached"


class ProcessIdentity(Record):
    """A PID and a host-derived start marker identify one process lifetime."""

    pid: PositiveInt
    start_marker: Text


class ConnectionState(StrEnum):
    READY = "ready"
    BUSY = "busy"
    LOST = "lost"
    DETACHED = "detached"


_CONNECTION_TRANSITIONS = {
    ConnectionState.READY: frozenset(
        {ConnectionState.BUSY, ConnectionState.LOST, ConnectionState.DETACHED}
    ),
    ConnectionState.BUSY: frozenset(
        {ConnectionState.READY, ConnectionState.LOST, ConnectionState.DETACHED}
    ),
    ConnectionState.LOST: frozenset({ConnectionState.DETACHED}),
    ConnectionState.DETACHED: frozenset(),
}


class Connection(Record):
    context: ApplicationContext
    endpoint: Endpoint
    ownership: ProcessOwnership
    state: ConnectionState
    process: ProcessIdentity | None = None

    @model_validator(mode="after")
    def check_owned_process(self) -> Self:
        if self.ownership == ProcessOwnership.OWNED and self.process is None:
            raise ValueError("An owned connection requires its recorded process identifier.")
        return self

    def transition(self, state: ConnectionState) -> Self:
        """Reconnection requires a new, verified connection identity."""
        if state not in _CONNECTION_TRANSITIONS[self.state]:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_TRANSITION,
                    message=f"A connection cannot change from {self.state} to {state}.",
                )
            )
        return type(self).model_validate({**self.model_dump(), "state": state})


class LaunchRequest(Record):
    session_id: SessionId
    executable: Path

    @model_validator(mode="after")
    def check_executable_path(self) -> Self:
        if not self.executable.is_absolute():
            raise ValueError("The application executable path must be absolute.")
        return self


class AttachRequest(Record):
    session_id: SessionId
    endpoint: Endpoint


class CloseAction(StrEnum):
    DETACH = "detach"
    TERMINATE = "terminate"


class CloseRequest(Record):
    session_id: SessionId
    connection_id: ConnectionId
    action: CloseAction = CloseAction.DETACH


class CloseReceipt(Record):
    session_id: SessionId
    connection_id: ConnectionId
    action: CloseAction


def authorize_close(
    connection: Connection,
    request: CloseRequest,
    *,
    verified_process: ProcessIdentity | None = None,
    attached_termination_authorized: bool = False,
) -> CloseAction:
    """Use trusted ownership and permission records, never request-supplied ownership."""
    if (
        request.session_id != connection.context.session_id
        or request.connection_id != connection.context.connection_id
    ):
        raise ContractError(
            Error(
                code=ErrorCode.STALE_OBJECT, message="The close request names another connection."
            )
        )
    if request.action == CloseAction.DETACH:
        return CloseAction.DETACH
    if connection.ownership == ProcessOwnership.ATTACHED and not attached_termination_authorized:
        raise ContractError(
            Error(
                code=ErrorCode.UNSUPPORTED_OPERATION,
                message="Terminating an attached process requires explicit owner authorization.",
            )
        )
    if (
        verified_process is None
        or verified_process != connection.process
        or connection.state == ConnectionState.DETACHED
    ):
        raise ContractError(
            Error(
                code=ErrorCode.LOST_CONNECTION, message="The current process identity is unproved."
            )
        )
    return CloseAction.TERMINATE
