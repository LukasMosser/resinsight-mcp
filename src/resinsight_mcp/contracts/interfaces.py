"""Typed boundaries for later implementations, without backend imports."""

from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol

from .engineering import ModelRef
from .errors import OperationResult
from .identifiers import ArtifactId, CheckpointId, ObservationId, ResultId, RevisionId, SessionId
from .jobs import Job, JobRef, JobRequest, LoadedResult, Result, ResultImportRequest
from .models import ArtifactRef, ModelRevision, PreparationRequest, PreparedModel, Session
from .observations import Observation, RenderRequest
from .sessions import (
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
from .workspace import Artifact, ProjectCheckpoint, RecoveryReport


class ProcessController(Protocol):
    """Resolve trusted ownership before closing a recorded process."""

    def launch(self, request: LaunchRequest) -> OperationResult[Connection]: ...

    def attach(self, request: AttachRequest) -> OperationResult[Connection]: ...

    def close(
        self,
        request: CloseRequest,
        *,
        attached_termination_authorized: bool = False,
    ) -> OperationResult[CloseReceipt]:
        """Verify the live process identity and obtain any attached-process owner authorization."""
        ...


class SessionService(ProcessController, Protocol):
    """Keep durable sessions separate from live application connections."""

    def create_session(self, session: Session) -> OperationResult[Session]: ...

    def list_sessions(self) -> OperationResult[tuple[Session, ...]]: ...

    def select_session(self, session_id: SessionId) -> OperationResult[Session]:
        """Resolve one session without supplying a default for later mutations."""
        ...

    def list_connections(self) -> OperationResult[tuple[Connection, ...]]: ...

    def get_connection(self, session_id: SessionId) -> OperationResult[Connection]: ...

    def inspect_project(self, session_id: SessionId) -> OperationResult[ProjectState]: ...

    def open_project(self, request: ProjectOpenRequest) -> OperationResult[ProjectState]: ...

    def save_project(self, request: ProjectSaveRequest) -> OperationResult[ProjectState]: ...

    def close_project(self, request: ProjectCloseRequest) -> OperationResult[ProjectState]: ...

    def resolve_object(self, reference: ObjectRef) -> OperationResult[ProjectObject]:
        """Observe current state before accepting a service-issued object reference."""
        ...


class WorkspaceStore(Protocol):
    """Preserve immutable revisions and reject conflicting writes to an existing revision."""

    def create_session(self, session: Session) -> OperationResult[Session]: ...

    def get_session(self, session_id: SessionId) -> OperationResult[Session]: ...

    def list_sessions(self) -> OperationResult[tuple[Session, ...]]: ...

    def write_artifact(self, artifact: Artifact, source: BinaryIO) -> OperationResult[Artifact]: ...

    def get_artifact(self, artifact: ArtifactRef) -> OperationResult[Artifact]: ...

    def list_artifacts(self, session_id: SessionId) -> OperationResult[tuple[Artifact, ...]]: ...

    def save_revision(self, revision: ModelRevision) -> OperationResult[ModelRevision]: ...

    def get_revision(self, model: ModelRef) -> OperationResult[ModelRevision]: ...

    def clone_revision(
        self,
        source: ModelRef,
        revision_id: RevisionId,
        *,
        replacements: tuple[ArtifactId, ...] = (),
    ) -> OperationResult[ModelRevision]: ...

    def save_job(self, job: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        """Require the prior stored job before changing it; reject stale competing writes."""
        ...

    def get_job(self, job: JobRef) -> OperationResult[Job]: ...

    def list_jobs(self, session_id: SessionId) -> OperationResult[tuple[Job, ...]]: ...

    def save_result(self, result: Result) -> OperationResult[Result]: ...

    def get_result(self, session_id: SessionId, result_id: ResultId) -> OperationResult[Result]: ...

    def save_observation(self, observation: Observation) -> OperationResult[Observation]:
        """Check observation.context.require_result against the stored result before saving."""
        ...

    def get_observation(
        self, session_id: SessionId, observation_id: ObservationId
    ) -> OperationResult[Observation]: ...

    def open_artifact(self, artifact: ArtifactRef) -> AbstractContextManager[BinaryIO]:
        """Raise ContractError for missing or inaccessible data; never return another artifact."""
        ...

    def save_checkpoint(
        self, checkpoint: ProjectCheckpoint
    ) -> OperationResult[ProjectCheckpoint]: ...

    def get_checkpoint(
        self, session_id: SessionId, checkpoint_id: CheckpointId
    ) -> OperationResult[ProjectCheckpoint]: ...

    def reconcile(
        self, session_id: SessionId, *, expected_jobs: tuple[Job, ...] = ()
    ) -> OperationResult[RecoveryReport]:
        """Stop the job controller before reconciling explicitly selected job snapshots."""
        ...


class Renderer(Protocol):
    def render(self, request: RenderRequest) -> OperationResult[Observation]:
        """Decode fresh output and record actual view context before returning success."""
        ...


class ModelPreparer(Protocol):
    def prepare(self, request: PreparationRequest) -> OperationResult[PreparedModel]:
        """Reject unsupported inputs or backends without changing the fixed revision."""
        ...


class JobController(Protocol):
    def submit(self, request: JobRequest) -> OperationResult[Job]: ...

    def poll(self, job: JobRef) -> OperationResult[Job]: ...

    def request_cancel(self, job: JobRef) -> OperationResult[Job]:
        """Record cancellation intent without claiming confirmed termination."""
        ...


class ResultImporter(Protocol):
    def load(self, request: ResultImportRequest) -> OperationResult[LoadedResult]:
        """Preserve exact job, revision, grid, report-time, and unit identity."""
        ...
