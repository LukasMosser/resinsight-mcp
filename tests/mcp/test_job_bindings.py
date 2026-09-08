"""Exercise optional job bindings through an SDK without running a simulator."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId, JobId, RevisionId, SessionId
from resinsight_mcp.contracts.interfaces import JobController
from resinsight_mcp.contracts.jobs import Job, JobRef, JobRequest, JobState, ResourceLimits
from resinsight_mcp.contracts.models import (
    Backend,
    ModelInputs,
    ModelRevision,
    PreparedModel,
    Session,
)
from resinsight_mcp.mcp.catalog import Bindings
from resinsight_mcp.mcp.server import create_server
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@dataclass
class ControlledJobs:
    """Record dispatch and supply typed outcomes without owning any processes."""

    job: Job
    calls: list[tuple[str, JobRequest | JobRef]] = field(default_factory=list)
    error: Error | None = None

    def _response(self) -> OperationResult[Job]:
        if self.error is not None:
            return OperationResult(outcome=Failure(error=self.error))
        return OperationResult(outcome=Success(value=self.job))

    def submit(self, request: JobRequest) -> OperationResult[Job]:
        self.calls.append(("submit", request))
        return self._response()

    def poll(self, job: JobRef) -> OperationResult[Job]:
        self.calls.append(("poll", job))
        return self._response()

    def request_cancel(self, job: JobRef) -> OperationResult[Job]:
        self.calls.append(("request_cancel", job))
        return self._response()


def failure(response: types.CallToolResult) -> Error:
    assert response.isError is True
    outcome = (
        OperationResult[Job].model_validate_json(json.dumps(response.structuredContent)).outcome
    )
    assert isinstance(outcome, Failure)
    return outcome.error


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def store(tmp_path: Path) -> SqliteWorkspaceStore:
    return SqliteWorkspaceStore.create(tmp_path / "workspace")


@pytest.fixture
def job_request() -> JobRequest:
    artifact = ArtifactId.new()
    return JobRequest(
        prepared=PreparedModel(
            revision=ModelRevision(
                model=ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new()),
                inputs=ModelInputs(artifacts=(artifact,), entrypoint=artifact),
                unit_system=UnitSystem.FIELD,
                coordinates=CoordinateFrame(
                    length_unit=Unit.FOOT,
                    depth_direction=DepthDirection.POSITIVE_DOWN,
                    datum="Local origin",
                ),
            ),
            backend=Backend.OPM_FLOW,
        ),
        limits=ResourceLimits(cpu_count=2, memory_mib=512, wall_time_seconds=60),
    )


@pytest.fixture
def jobs(job_request: JobRequest) -> ControlledJobs:
    controller = ControlledJobs(
        Job(
            job_id=JobId.new(),
            model=job_request.prepared.revision.model,
            backend=job_request.prepared.backend,
            state=JobState.RUNNING,
            cancel_requested=True,
        )
    )
    _contract: JobController = controller
    return controller


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [False, True])
async def test_job_tools_require_explicit_controller(
    store: SqliteWorkspaceStore, jobs: ControlledJobs, enabled: bool
) -> None:
    server = create_server(Bindings(workspaces=store, jobs=jobs if enabled else None))
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        tools = {tool.name: tool for tool in listed.tools if tool.name.startswith("job_")}
        assert set(tools) == ({"job_submit", "job_poll", "job_cancel"} if enabled else set())
        if enabled:
            assert tools["job_submit"].inputSchema == JobRequest.model_json_schema()
            assert tools["job_poll"].inputSchema == JobRef.model_json_schema()
            assert tools["job_cancel"].inputSchema == JobRef.model_json_schema()
            for tool in tools.values():
                assert tool.outputSchema == OperationResult[Job].model_json_schema()
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is (tool.name == "job_poll")


@pytest.mark.anyio
async def test_typed_job_calls_dispatch_to_exact_controller_method(
    store: SqliteWorkspaceStore, jobs: ControlledJobs, job_request: JobRequest
) -> None:
    session = Session(session_id=jobs.job.model.session_id, name="Job bindings")
    assert isinstance(store.create_session(session).outcome, Success)
    reference = JobRef(session_id=session.session_id, job_id=jobs.job.job_id)
    server = create_server(Bindings(workspaces=store, jobs=jobs))
    async with create_connected_server_and_client_session(server) as client:
        for tool, request, method in (
            ("job_submit", job_request, "submit"),
            ("job_poll", reference, "poll"),
            ("job_cancel", reference, "request_cancel"),
        ):
            before = len(jobs.calls)
            response = await client.call_tool(tool, request.model_dump(mode="json"))
            assert response.isError is False
            outcome = (
                OperationResult[Job]
                .model_validate_json(json.dumps(response.structuredContent))
                .outcome
            )
            assert isinstance(outcome, Success)
            assert outcome.value == jobs.job
            assert jobs.calls[before:] == [(method, request)]
            assert type(jobs.calls[-1][1]) is type(request)
        assert outcome.value.cancel_requested is True
        assert outcome.value.state == JobState.RUNNING
        assert outcome.value.termination_confirmed is False


@pytest.mark.anyio
async def test_missing_session_prevents_all_job_dispatch(
    store: SqliteWorkspaceStore, jobs: ControlledJobs, job_request: JobRequest
) -> None:
    unrelated = Session(session_id=SessionId.new(), name="Other session")
    assert isinstance(store.create_session(unrelated).outcome, Success)
    reference = JobRef(session_id=jobs.job.model.session_id, job_id=jobs.job.job_id)
    server = create_server(Bindings(workspaces=store, jobs=jobs))
    async with create_connected_server_and_client_session(server) as client:
        for tool, request in (
            ("job_submit", job_request),
            ("job_poll", reference),
            ("job_cancel", reference),
        ):
            response = await client.call_tool(tool, request.model_dump(mode="json"))
            assert failure(response).code == ErrorCode.NOT_FOUND
    assert jobs.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["job_submit", "job_poll", "job_cancel"])
async def test_job_requests_require_explicit_session(
    store: SqliteWorkspaceStore, jobs: ControlledJobs, job_request: JobRequest, tool: str
) -> None:
    assert isinstance(
        store.create_session(Session(session_id=jobs.job.model.session_id, name="Known")).outcome,
        Success,
    )
    if tool == "job_submit":
        arguments = job_request.model_dump(mode="json")
        del arguments["prepared"]["revision"]["model"]["session_id"]
    else:
        arguments = {"job_id": str(jobs.job.job_id)}
    server = create_server(Bindings(workspaces=store, jobs=jobs))
    async with create_connected_server_and_client_session(server) as client:
        response = await client.call_tool(tool, arguments)
        assert failure(response).code == ErrorCode.INVALID_MODEL
    assert jobs.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["job_submit", "job_poll", "job_cancel"])
async def test_job_controller_errors_retain_stable_contract(
    store: SqliteWorkspaceStore, jobs: ControlledJobs, job_request: JobRequest, tool: str
) -> None:
    assert isinstance(
        store.create_session(Session(session_id=jobs.job.model.session_id, name="Known")).outcome,
        Success,
    )
    jobs.error = Error(code=ErrorCode.BUSY, message="The job controller is busy.")
    request = (
        job_request
        if tool == "job_submit"
        else JobRef(session_id=jobs.job.model.session_id, job_id=jobs.job.job_id)
    )
    server = create_server(Bindings(workspaces=store, jobs=jobs))
    async with create_connected_server_and_client_session(server) as client:
        response = await client.call_tool(tool, request.model_dump(mode="json"))
        assert failure(response) == jobs.error
