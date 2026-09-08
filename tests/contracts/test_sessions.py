"""Object and process permissions are tied to explicit current identities."""

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.contracts.identifiers import ConnectionId, SessionId
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    CloseAction,
    CloseRequest,
    Connection,
    ConnectionState,
    Endpoint,
    ObjectKind,
    ObjectRef,
    ProcessIdentity,
    ProcessOwnership,
    authorize_close,
)


@pytest.mark.parametrize("changed", ["session", "connection", "project"])
def test_handles_cannot_cross_sessions_reconnections_or_projects(
    context: ApplicationContext, changed: str
) -> None:
    case = ObjectRef(context=context, kind=ObjectKind.CASE, object_id="0")
    case.require_current(context)
    current = ApplicationContext(
        session_id=SessionId.new() if changed == "session" else context.session_id,
        connection_id=ConnectionId.new() if changed == "connection" else context.connection_id,
        project_generation=2 if changed == "project" else context.project_generation,
    )
    with pytest.raises(ContractError) as stale:
        case.require_current(current)
    assert stale.value.error.code == ErrorCode.STALE_OBJECT


def test_busy_is_recoverable_but_lost_requires_new_connection(context: ApplicationContext) -> None:
    ready = Connection(
        context=context,
        endpoint=Endpoint(port=50051),
        ownership=ProcessOwnership.ATTACHED,
        state=ConnectionState.READY,
    )
    busy = ready.transition(ConnectionState.BUSY)
    assert busy.transition(ConnectionState.READY).context == context
    lost = busy.transition(ConnectionState.LOST)
    with pytest.raises(ContractError) as reconnect:
        lost.transition(ConnectionState.READY)
    assert reconnect.value.error.code == ErrorCode.INVALID_TRANSITION
    assert lost.transition(ConnectionState.DETACHED).state == ConnectionState.DETACHED


def test_attached_close_defaults_to_detach_and_rejects_unapproved_termination(
    context: ApplicationContext,
) -> None:
    connection = Connection(
        context=context,
        endpoint=Endpoint(port=50051),
        ownership=ProcessOwnership.ATTACHED,
        state=ConnectionState.READY,
        process=ProcessIdentity(pid=1234, start_marker="started-1"),
    )
    close = CloseRequest(session_id=context.session_id, connection_id=context.connection_id)
    assert authorize_close(connection, close) == CloseAction.DETACH
    terminate = CloseRequest(
        session_id=context.session_id,
        connection_id=context.connection_id,
        action=CloseAction.TERMINATE,
    )
    with pytest.raises(ContractError) as denied:
        authorize_close(connection, terminate)
    assert denied.value.error.code == ErrorCode.UNSUPPORTED_OPERATION
    assert connection.state == ConnectionState.READY


def test_close_rejects_request_for_a_different_connection(context: ApplicationContext) -> None:
    connection = Connection(
        context=context,
        endpoint=Endpoint(port=50051),
        ownership=ProcessOwnership.ATTACHED,
        state=ConnectionState.READY,
    )
    close = CloseRequest(session_id=context.session_id, connection_id=ConnectionId.new())
    with pytest.raises(ContractError) as stale:
        authorize_close(connection, close)
    assert stale.value.error.code == ErrorCode.STALE_OBJECT


def test_owned_connection_requires_process_identity(context: ApplicationContext) -> None:
    with pytest.raises(ValidationError):
        Connection(
            context=context,
            endpoint=Endpoint(port=50051),
            ownership=ProcessOwnership.OWNED,
            state=ConnectionState.READY,
        )


@pytest.mark.parametrize("ownership", [ProcessOwnership.OWNED, ProcessOwnership.ATTACHED])
def test_termination_requires_fresh_matching_process_lifetime(
    context: ApplicationContext, ownership: ProcessOwnership
) -> None:
    recorded = ProcessIdentity(pid=1234, start_marker="host-start-1")
    connection = Connection(
        context=context,
        endpoint=Endpoint(port=50051),
        ownership=ownership,
        state=ConnectionState.READY,
        process=recorded,
    )
    request = CloseRequest(
        session_id=context.session_id,
        connection_id=context.connection_id,
        action=CloseAction.TERMINATE,
    )
    for verification in (
        None,
        ProcessIdentity(pid=1234, start_marker="host-start-2"),
        ProcessIdentity(pid=1235, start_marker="host-start-1"),
    ):
        with pytest.raises(ContractError) as unverified:
            authorize_close(
                connection,
                request,
                verified_process=verification,
                attached_termination_authorized=True,
            )
        assert unverified.value.error.code == ErrorCode.LOST_CONNECTION
    assert (
        authorize_close(
            connection, request, verified_process=recorded, attached_termination_authorized=True
        )
        == CloseAction.TERMINATE
    )
    detached = connection.transition(ConnectionState.DETACHED)
    with pytest.raises(ContractError) as closed:
        authorize_close(
            detached, request, verified_process=recorded, attached_termination_authorized=True
        )
    assert closed.value.error.code == ErrorCode.LOST_CONNECTION
