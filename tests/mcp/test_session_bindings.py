"""Exercise optional session bindings through an SDK client without an application."""

import json
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ConnectionId, SessionId
from resinsight_mcp.contracts.interfaces import SessionService
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    AttachRequest,
    CloseAction,
    CloseReceipt,
    CloseRequest,
    Connection,
    ConnectionState,
    Endpoint,
    LaunchRequest,
    ObjectKind,
    ObjectRef,
    ProcessIdentity,
    ProcessOwnership,
    ProjectCloseRequest,
    ProjectObject,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
    authorize_close,
)
from resinsight_mcp.mcp.catalog import Bindings
from resinsight_mcp.mcp.server import create_server
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def success[T](value: T) -> OperationResult[T]:
    return OperationResult[T](outcome=Success(value=value))


def failure(response: types.CallToolResult) -> Error:
    assert response.isError is True
    assert len(response.content) == 1
    outcome = (
        OperationResult[object].model_validate_json(json.dumps(response.structuredContent)).outcome
    )
    assert isinstance(outcome, Failure)
    return outcome.error


class RecordingService:
    """Keep explicit test connections and record typed calls without launching processes."""

    def __init__(self, store: SqliteWorkspaceStore) -> None:
        self.store = store
        self.connections: dict[SessionId, Connection] = {}
        self.calls: list[object] = []
        self.connection_error: Error | None = None

    def create_session(self, session: Session) -> OperationResult[Session]:
        self.calls.append(session)
        return self.store.create_session(session)

    def list_sessions(self) -> OperationResult[tuple[Session, ...]]:
        return self.store.list_sessions()

    def select_session(self, session_id: SessionId) -> OperationResult[Session]:
        self.calls.append(session_id)
        return self.store.get_session(session_id)

    def list_connections(self) -> OperationResult[tuple[Connection, ...]]:
        return success(tuple(self.connections.values()))

    def get_connection(self, session_id: SessionId) -> OperationResult[Connection]:
        self.calls.append(session_id)
        if self.connection_error is not None:
            return OperationResult[Connection](outcome=Failure(error=self.connection_error))
        return success(self.connections[session_id])

    def launch(self, request: LaunchRequest) -> OperationResult[Connection]:
        self.calls.append(request)
        connection = Connection(
            context=ApplicationContext(
                session_id=request.session_id,
                connection_id=ConnectionId.new(),
                project_generation=0,
            ),
            endpoint=Endpoint(port=50001),
            ownership=ProcessOwnership.OWNED,
            state=ConnectionState.READY,
            process=ProcessIdentity(pid=123, start_marker="test process record"),
        )
        self.connections[request.session_id] = connection
        return success(connection)

    def attach(self, request: AttachRequest) -> OperationResult[Connection]:
        self.calls.append(request)
        connection = Connection(
            context=ApplicationContext(
                session_id=request.session_id,
                connection_id=ConnectionId.new(),
                project_generation=0,
            ),
            endpoint=request.endpoint,
            ownership=ProcessOwnership.ATTACHED,
            state=ConnectionState.READY,
        )
        self.connections[request.session_id] = connection
        return success(connection)

    def close(
        self, request: CloseRequest, *, attached_termination_authorized: bool = False
    ) -> OperationResult[CloseReceipt]:
        self.calls.append(request)
        connection = self.connections[request.session_id]
        try:
            action = authorize_close(
                connection,
                request,
                attached_termination_authorized=attached_termination_authorized,
            )
        except ContractError as exc:
            return OperationResult[CloseReceipt](outcome=Failure(error=exc.error))
        self.connections[request.session_id] = connection.transition(ConnectionState.DETACHED)
        return success(
            CloseReceipt(
                session_id=request.session_id, connection_id=request.connection_id, action=action
            )
        )

    def inspect_project(self, session_id: SessionId) -> OperationResult[ProjectState]:
        self.calls.append(session_id)
        return success(ProjectState(context=self.connections[session_id].context))

    def open_project(self, request: ProjectOpenRequest) -> OperationResult[ProjectState]:
        self.calls.append(request)
        return success(ProjectState(context=request.context))

    def save_project(self, request: ProjectSaveRequest) -> OperationResult[ProjectState]:
        self.calls.append(request)
        return success(ProjectState(context=request.context, last_saved_path=request.path))

    def close_project(self, request: ProjectCloseRequest) -> OperationResult[ProjectState]:
        self.calls.append(request)
        return success(ProjectState(context=request.context))

    def resolve_object(self, reference: ObjectRef) -> OperationResult[ProjectObject]:
        self.calls.append(reference)
        return success(ProjectObject(ref=reference, name="Test case"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def service(tmp_path: Path) -> RecordingService:
    service = RecordingService(SqliteWorkspaceStore.create(tmp_path / "workspace"))
    _contract: SessionService = service
    return service


@pytest.mark.anyio
async def test_requests_reach_session_service_as_typed_records(service: RecordingService) -> None:
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    owned = Session(session_id=SessionId.new(), name="Owned test")
    attached = Session(session_id=SessionId.new(), name="Attached test")
    async with create_connected_server_and_client_session(server) as client:
        for session in (owned, attached):
            response = await client.call_tool("session_create", session.model_dump(mode="json"))
            assert response.structuredContent == success(session).model_dump(mode="json")
        listed = await client.call_tool("session_list", {})
        outcome = (
            OperationResult[tuple[Session, ...]]
            .model_validate_json(json.dumps(listed.structuredContent))
            .outcome
        )
        assert isinstance(outcome, Success)
        assert set(outcome.value) == {owned, attached}
        launch = LaunchRequest(session_id=owned.session_id, executable=Path("/test/ResInsight"))
        attach = AttachRequest(session_id=attached.session_id, endpoint=Endpoint(port=50002))
        for tool, request in (("application_launch", launch), ("application_attach", attach)):
            response = await client.call_tool(tool, request.model_dump(mode="json"))
            assert response.isError is False
            assert service.calls[-1] == request
        context = service.connections[attached.session_id].context
        requests = (
            ("project_open", ProjectOpenRequest(context=context, path=Path("/test/input.rsp"))),
            (
                "project_save",
                ProjectSaveRequest(context=context, path=Path("/test/output.rsp"), overwrite=True),
            ),
            ("project_close", ProjectCloseRequest(context=context)),
            (
                "object_resolve",
                ObjectRef(context=context, kind=ObjectKind.CASE, object_id="test case"),
            ),
            (
                "application_close",
                CloseRequest(session_id=attached.session_id, connection_id=context.connection_id),
            ),
        )
        for tool, request in requests:
            response = await client.call_tool(tool, request.model_dump(mode="json"))
            assert response.isError is False
            assert service.calls[-1] == request
        assert service.connections[attached.session_id].state == ConnectionState.DETACHED
        assert service.connections[owned.session_id].state == ConnectionState.READY


@pytest.mark.anyio
async def test_missing_session_is_resolved_before_service_invocation(
    service: RecordingService,
) -> None:
    session_id = SessionId.new()
    context = ApplicationContext(
        session_id=session_id, connection_id=ConnectionId.new(), project_generation=0
    )
    requests = (
        ("session_select", {"session_id": str(session_id)}),
        ("connection_get", {"session_id": str(session_id)}),
        ("project_inspect", {"session_id": str(session_id)}),
        (
            "application_launch",
            LaunchRequest(session_id=session_id, executable=Path("/test/ResInsight")).model_dump(
                mode="json"
            ),
        ),
        (
            "application_attach",
            AttachRequest(session_id=session_id, endpoint=Endpoint(port=50002)).model_dump(
                mode="json"
            ),
        ),
        (
            "application_close",
            CloseRequest(session_id=session_id, connection_id=context.connection_id).model_dump(
                mode="json"
            ),
        ),
        (
            "project_open",
            ProjectOpenRequest(context=context, path=Path("/test/input.rsp")).model_dump(
                mode="json"
            ),
        ),
        (
            "project_save",
            ProjectSaveRequest(context=context, path=Path("/test/output.rsp")).model_dump(
                mode="json"
            ),
        ),
        ("project_close", ProjectCloseRequest(context=context).model_dump(mode="json")),
        (
            "object_resolve",
            ObjectRef(context=context, kind=ObjectKind.CASE, object_id="test").model_dump(
                mode="json"
            ),
        ),
    )
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    async with create_connected_server_and_client_session(server) as client:
        for tool, arguments in requests:
            assert failure(await client.call_tool(tool, arguments)).code == ErrorCode.NOT_FOUND
    assert service.calls == []
    assert service.connections == {}


@pytest.mark.anyio
async def test_select_does_not_supply_a_later_mutation_target(service: RecordingService) -> None:
    session = Session(session_id=SessionId.new(), name="Explicit target")
    assert isinstance(service.store.create_session(session).outcome, Success)
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    async with create_connected_server_and_client_session(server) as client:
        response = await client.call_tool("session_select", {"session_id": str(session.session_id)})
        assert response.isError is False
        calls_after_selection = list(service.calls)
        response = await client.call_tool("application_launch", {"executable": "/test/ResInsight"})
        assert failure(response).code == ErrorCode.INVALID_MODEL
        assert service.calls == calls_after_selection
        assert service.connections == {}


@pytest.mark.anyio
async def test_request_cannot_grant_attached_process_termination(service: RecordingService) -> None:
    session = Session(session_id=SessionId.new(), name="Attached process")
    assert isinstance(service.store.create_session(session).outcome, Success)
    attached = service.attach(
        AttachRequest(session_id=session.session_id, endpoint=Endpoint(port=50002))
    )
    assert isinstance(attached.outcome, Success)
    connection = attached.outcome.value
    request = CloseRequest(
        session_id=session.session_id,
        connection_id=connection.context.connection_id,
        action=CloseAction.TERMINATE,
    )
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        schema = next(tool.inputSchema for tool in tools.tools if tool.name == "application_close")
        assert "attached_termination_authorized" not in schema["properties"]
        before = list(service.calls)
        response = await client.call_tool(
            "application_close",
            {**request.model_dump(mode="json"), "attached_termination_authorized": True},
        )
        assert failure(response).code == ErrorCode.INVALID_MODEL
        assert service.calls == before
        response = await client.call_tool("application_close", request.model_dump(mode="json"))
        assert failure(response).code == ErrorCode.UNSUPPORTED_OPERATION
        assert service.connections[session.session_id] == connection


@pytest.mark.anyio
async def test_protocol_reconnect_preserves_service_connection(service: RecordingService) -> None:
    session = Session(session_id=SessionId.new(), name="Persistent connection")
    assert isinstance(service.store.create_session(session).outcome, Success)
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    async with create_connected_server_and_client_session(server) as client:
        request = AttachRequest(session_id=session.session_id, endpoint=Endpoint(port=50002))
        response = await client.call_tool("application_attach", request.model_dump(mode="json"))
        assert response.isError is False
        connection = service.connections[session.session_id]
    assert service.connections[session.session_id] == connection
    async with create_connected_server_and_client_session(server) as client:
        response = await client.call_tool("connection_get", {"session_id": str(session.session_id)})
        assert response.structuredContent == success(connection).model_dump(mode="json")
        response = await client.call_tool("connection_list", {})
        assert response.structuredContent == success((connection,)).model_dump(mode="json")
    assert service.connections[session.session_id] == connection
    assert connection.state == ConnectionState.READY


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.BUSY,
        ErrorCode.LOST_CONNECTION,
        ErrorCode.STALE_OBJECT,
        ErrorCode.UNSUPPORTED_OPERATION,
    ],
)
async def test_stable_service_errors_cross_protocol_unchanged(
    service: RecordingService, code: ErrorCode
) -> None:
    session = Session(session_id=SessionId.new(), name="Service failure")
    assert isinstance(service.store.create_session(session).outcome, Success)
    error = Error(
        code=code,
        message="Explicit test service failure.",
        effect=MutationEffect.UNKNOWN
        if code == ErrorCode.LOST_CONNECTION
        else MutationEffect.NOT_APPLIED,
    )
    service.connection_error = error
    server = create_server(Bindings(workspaces=service.store, sessions=service))
    async with create_connected_server_and_client_session(server) as client:
        response = await client.call_tool("connection_get", {"session_id": str(session.session_id)})
        assert failure(response) == error
