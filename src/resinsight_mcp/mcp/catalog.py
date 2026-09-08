"""One catalog binds typed operations without owning application state."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp import types
from pydantic import Field, PositiveInt, ValidationError

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ObservationId, SessionId
from resinsight_mcp.contracts.interfaces import (
    JobController,
    Renderer,
    SessionService,
    WorkspaceStore,
)
from resinsight_mcp.contracts.jobs import Job, JobRef, JobRequest
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.observations import Observation, RenderRequest, ViewContext
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    CloseReceipt,
    CloseRequest,
    Connection,
    LaunchRequest,
    ObjectRef,
    ProjectCloseRequest,
    ProjectObject,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
)

CATALOG_RESOURCE = types.Resource(
    uri="resinsight://catalog",
    name="operation_catalog",
    description="Available operations and their typed request and response descriptions.",
    mimeType="application/json",
)


class EmptyRequest(Record):
    """This operation takes no arguments."""


class SessionRequest(Record):
    session_id: SessionId = Field(
        description="The explicit durable engineering session identifier."
    )


class ObservationRequest(SessionRequest):
    observation_id: ObservationId = Field(
        description="The saved observation to read in this session."
    )


class ViewRenderRequest(SessionRequest):
    context: ViewContext = Field(
        description="The requested view and its exact stored result context."
    )
    width: PositiveInt = Field(description="Requested image width in pixels.")
    height: PositiveInt = Field(description="Requested image height in pixels.")


@dataclass(frozen=True)
class Bindings:
    """Services outlive protocol connections and retain responsibility for their state."""

    workspaces: WorkspaceStore
    renderer: Renderer | None = None
    sessions: SessionService | None = None
    jobs: JobController | None = None


@dataclass(frozen=True)
class Operation[Request: Record, Value]:
    name: str
    description: str
    request: type[Request]
    response: type[OperationResult[Value]]
    call: Callable[[Request], OperationResult[Value]]
    session_id: Callable[[Request], SessionId] | None = None
    read_only: bool = False

    def tool(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.request.model_json_schema(),
            outputSchema=self.response.model_json_schema(),
            annotations=types.ToolAnnotations(
                readOnlyHint=self.read_only,
                destructiveHint=not self.read_only,
                openWorldHint=False,
            ),
        )

    def invoke(self, request: Request, store: WorkspaceStore) -> OperationResult[Value]:
        if self.session_id is not None:
            session = store.get_session(self.session_id(request))
            if isinstance(session.outcome, Failure):
                return self.response(outcome=session.outcome)
        return self.response.model_validate(self.call(request).model_dump())


def _render(bindings: Bindings, request: ViewRenderRequest) -> OperationResult[Observation]:
    if request.context.model.session_id != request.session_id:
        raise ContractError(
            Error(code=ErrorCode.STALE_OBJECT, message="The view belongs to another session.")
        )
    result = bindings.workspaces.get_result(request.session_id, request.context.result_id)
    if isinstance(result.outcome, Failure):
        return OperationResult[Observation](outcome=result.outcome)
    try:
        render_request = RenderRequest(
            result=result.outcome.value,
            context=request.context,
            width=request.width,
            height=request.height,
        )
    except ValidationError as exc:
        raise ContractError(
            Error(
                code=ErrorCode.INVALID_MODEL, message="The view does not match the stored result."
            )
        ) from exc
    assert bindings.renderer is not None
    response = bindings.renderer.render(render_request)
    if isinstance(response.outcome, Success):
        observation = response.outcome.value
        if observation.context != request.context:
            raise ContractError(
                Error(code=ErrorCode.STALE_OBJECT, message="The rendered view context has changed.")
            )
        if (observation.image.width, observation.image.height) != (request.width, request.height):
            raise ContractError(
                Error(
                    code=ErrorCode.RENDER_FAILED,
                    message="The rendered dimensions differ from the request.",
                )
            )
    return response


def build_catalog(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    """Advertise only operations whose service implementation was explicitly supplied."""
    store = bindings.workspaces
    session_service = bindings.sessions if bindings.sessions is not None else store
    operations: list[Operation[Any, Any]] = [
        Operation(
            "session_create",
            "Create a durable workspace with an explicit session identifier.",
            Session,
            OperationResult[Session],
            session_service.create_session,
        ),
        Operation(
            "session_list",
            "List durable engineering sessions without selecting a mutation target.",
            EmptyRequest,
            OperationResult[tuple[Session, ...]],
            lambda _: session_service.list_sessions(),
            read_only=True,
        ),
        Operation(
            "session_get",
            "Read one durable session by its explicit identifier.",
            SessionRequest,
            OperationResult[Session],
            lambda request: store.get_session(request.session_id),
            read_only=True,
        ),
        Operation(
            "observation_get",
            "Read a saved observation with native image content. This does not render a new frame.",
            ObservationRequest,
            OperationResult[Observation],
            lambda request: store.get_observation(request.session_id, request.observation_id),
            session_id=lambda request: request.session_id,
            read_only=True,
        ),
    ]
    if bindings.renderer is not None:
        operations.append(
            Operation(
                "view_render",
                "Render the session view from its stored result with native image content.",
                ViewRenderRequest,
                OperationResult[Observation],
                lambda request: _render(bindings, request),
                session_id=lambda request: request.session_id,
            )
        )
    if bindings.sessions is not None:
        operations.extend(_session_operations(bindings.sessions))
    if bindings.jobs is not None:
        operations.extend(_job_operations(bindings.jobs))
    return tuple(operations)


def _session_operations(service: SessionService) -> tuple[Operation[Any, Any], ...]:
    return (
        Operation(
            "session_select",
            "Resolve a session without choosing a default for later requests.",
            SessionRequest,
            OperationResult[Session],
            lambda request: service.select_session(request.session_id),
            session_id=lambda request: request.session_id,
            read_only=True,
        ),
        Operation(
            "connection_list",
            "List live application connection records.",
            EmptyRequest,
            OperationResult[tuple[Connection, ...]],
            lambda _: service.list_connections(),
            read_only=True,
        ),
        Operation(
            "connection_get",
            "Read the application connection for an explicit session.",
            SessionRequest,
            OperationResult[Connection],
            lambda request: service.get_connection(request.session_id),
            session_id=lambda request: request.session_id,
            read_only=True,
        ),
        Operation(
            "application_launch",
            "Launch an owned application for an existing session.",
            LaunchRequest,
            OperationResult[Connection],
            service.launch,
            session_id=lambda request: request.session_id,
        ),
        Operation(
            "application_attach",
            "Attach an explicit session to a local application endpoint.",
            AttachRequest,
            OperationResult[Connection],
            service.attach,
            session_id=lambda request: request.session_id,
        ),
        Operation(
            "application_close",
            "Detach by default. Termination requires verified service ownership.",
            CloseRequest,
            OperationResult[CloseReceipt],
            service.close,
            session_id=lambda request: request.session_id,
        ),
        Operation(
            "project_inspect",
            "Read the current project context and service-issued object references.",
            SessionRequest,
            OperationResult[ProjectState],
            lambda request: service.inspect_project(request.session_id),
            session_id=lambda request: request.session_id,
            read_only=True,
        ),
        Operation(
            "project_open",
            "Open a project after checking the explicit expected application context.",
            ProjectOpenRequest,
            OperationResult[ProjectState],
            service.open_project,
            session_id=lambda request: request.context.session_id,
        ),
        Operation(
            "project_save",
            "Save the explicit project context to an absolute path.",
            ProjectSaveRequest,
            OperationResult[ProjectState],
            service.save_project,
            session_id=lambda request: request.context.session_id,
        ),
        Operation(
            "project_close",
            "Close the project after checking the explicit expected application context.",
            ProjectCloseRequest,
            OperationResult[ProjectState],
            service.close_project,
            session_id=lambda request: request.context.session_id,
        ),
        Operation(
            "object_resolve",
            "Check a service-issued object reference against the current project.",
            ObjectRef,
            OperationResult[ProjectObject],
            service.resolve_object,
            session_id=lambda request: request.context.session_id,
            read_only=True,
        ),
    )


def _job_operations(service: JobController) -> tuple[Operation[Any, Any], ...]:
    return (
        Operation(
            "job_submit",
            "Submit a prepared model revision with explicit resource limits.",
            JobRequest,
            OperationResult[Job],
            service.submit,
            session_id=lambda request: request.prepared.revision.model.session_id,
        ),
        Operation(
            "job_poll",
            "Check execution state for a job in an explicit session.",
            JobRef,
            OperationResult[Job],
            service.poll,
            session_id=lambda request: request.session_id,
            read_only=True,
        ),
        Operation(
            "job_cancel",
            "Record cancellation intent without claiming confirmed termination.",
            JobRef,
            OperationResult[Job],
            service.request_cancel,
            session_id=lambda request: request.session_id,
        ),
    )
