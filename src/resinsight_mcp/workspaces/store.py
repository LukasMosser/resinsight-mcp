"""One repository for durable records and immutable artifact files."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    CheckpointId,
    ObservationId,
    ResultId,
    RevisionId,
    SessionId,
)
from resinsight_mcp.contracts.jobs import Job, JobEvent, JobRef, JobState, Result
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision, Session
from resinsight_mcp.contracts.observations import Observation
from resinsight_mcp.contracts.workspace import (
    Artifact,
    ArtifactKind,
    ArtifactProblem,
    ProjectCheckpoint,
    RecoveryReport,
)

from . import _records as records
from ._database import Database
from ._files import FileArea
from ._records import fail


def _operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except ValidationError as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(code=ErrorCode.INVALID_MODEL, message=f"Invalid record: {error}")
                )
            )

    return run


def _session(connection: sqlite3.Connection, session_id: SessionId) -> Session:
    return records.require(connection, Session, str(session_id), str(session_id))


def _check_names(artifacts: tuple[Artifact, ...]) -> None:
    keys = {artifact.path_key for artifact in artifacts}
    if len(keys) != len(artifacts):
        raise fail(ErrorCode.INVALID_MODEL, "Model input filenames must not collide.")
    for key in keys:
        parts = key.split("/")
        if any("/".join(parts[:index]) in keys for index in range(1, len(parts))):
            raise fail(ErrorCode.INVALID_MODEL, "A model input filename also names a directory.")


def _check_execution_update(previous: Job, updated: Job) -> None:
    if previous.submission != updated.submission:
        raise fail(ErrorCode.INVALID_MODEL, "A stored submission cannot change.")
    for field in ("supervisor", "process", "process_group_id", "container_id", "logs"):
        retained = getattr(previous, field)
        if retained and retained != getattr(updated, field):
            raise fail(ErrorCode.INVALID_MODEL, f"Recorded job {field} cannot change.")
    if updated.events[: len(previous.events)] != previous.events:
        raise fail(ErrorCode.INVALID_TRANSITION, "Job events can only be appended.")


def _check_job_update(previous: Job, updated: Job) -> None:
    if (
        previous.model != updated.model
        or previous.backend != updated.backend
        or previous.job_id != updated.job_id
    ):
        raise fail(
            ErrorCode.INVALID_MODEL, "A stored job cannot change its model, backend, or identity."
        )
    if previous.cancel_requested and not updated.cancel_requested:
        raise fail(
            ErrorCode.INVALID_TRANSITION, "A job cannot clear its recorded cancellation intent."
        )
    if previous.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED}:
        raise fail(ErrorCode.INVALID_TRANSITION, "A terminal job cannot change.")
    _check_execution_update(previous, updated)
    candidate = previous
    if updated.cancel_requested and not candidate.cancel_requested:
        candidate = candidate.request_cancel()
    if candidate.state != updated.state:
        candidate = candidate.transition(
            updated.state,
            exit_code=updated.exit_code,
            error=updated.error,
            termination_confirmed=updated.termination_confirmed,
        )
    candidate = Job.model_validate(
        {
            **candidate.model_dump(),
            **updated.model_dump(
                include={
                    "supervisor",
                    "process",
                    "process_group_id",
                    "container_id",
                    "logs",
                    "events",
                }
            ),
        }
    )
    if candidate != updated:
        raise fail(
            ErrorCode.INVALID_TRANSITION, "The job update does not follow its state contract."
        )


class SqliteWorkspaceStore:
    """Store one workspace on a trusted local macOS or Linux filesystem."""

    def __init__(self, files: FileArea, timeout: float) -> None:
        self._files = files
        self._database = Database(files, timeout)

    @classmethod
    def create(cls, root: Path, *, timeout: float = 5.0) -> "SqliteWorkspaceStore":
        """Create a new directory under an existing parent; raise ContractError on failure."""
        Database.check_timeout(timeout)
        store = cls(FileArea.create(root), timeout)
        store._database.initialize()
        return store

    @classmethod
    def open(cls, root: Path, *, timeout: float = 5.0) -> "SqliteWorkspaceStore":
        """Open an existing compatible workspace without changing job states."""
        Database.check_timeout(timeout)
        store = cls(FileArea.open(root), timeout)
        store._database.inspect()
        return store

    @_operation
    def create_session(self, session: Session) -> Session:
        with self._database.transaction(write=True) as connection:
            return records.immutable(connection, session)

    @_operation
    def get_session(self, session_id: SessionId) -> Session:
        with self._database.transaction() as connection:
            return _session(connection, session_id)

    @_operation
    def list_sessions(self) -> tuple[Session, ...]:
        with self._database.transaction() as connection:
            return records.all_records(connection, Session)

    def _artifact(self, connection: sqlite3.Connection, ref: ArtifactRef) -> Artifact:
        artifact = records.require(connection, Artifact, str(ref.session_id), str(ref.artifact_id))
        self._files.check(ref)
        return artifact

    @_operation
    def write_artifact(self, artifact: Artifact, source: BinaryIO) -> Artifact:
        artifact = Artifact.model_validate(artifact)
        with self._database.transaction(write=True) as connection:
            _session(connection, artifact.ref.session_id)
            previous = records.find(
                connection, Artifact, str(artifact.ref.session_id), str(artifact.ref.artifact_id)
            )
            if previous is not None:
                raise fail(ErrorCode.CONFLICT, "An artifact already uses this identity.")
            self._files.write(artifact.ref, source)
            return records.insert(connection, artifact)

    @_operation
    def get_artifact(self, artifact: ArtifactRef) -> Artifact:
        with self._database.transaction() as connection:
            return self._artifact(connection, artifact)

    @_operation
    def list_artifacts(self, session_id: SessionId) -> tuple[Artifact, ...]:
        with self._database.transaction() as connection:
            _session(connection, session_id)
            return records.all_records(connection, Artifact, str(session_id))

    @contextmanager
    def open_artifact(self, artifact: ArtifactRef) -> Iterator[BinaryIO]:
        with self._database.transaction() as connection:
            records.require(
                connection, Artifact, str(artifact.session_id), str(artifact.artifact_id)
            )
        with self._files.reader(artifact) as stream:
            yield stream

    def _inputs(
        self, connection: sqlite3.Connection, revision: ModelRevision
    ) -> tuple[Artifact, ...]:
        artifacts = tuple(
            self._artifact(
                connection,
                ArtifactRef(session_id=revision.model.session_id, artifact_id=artifact_id),
            )
            for artifact_id in revision.inputs.artifacts
        )
        if any(artifact.kind != ArtifactKind.INPUT for artifact in artifacts):
            raise fail(ErrorCode.INVALID_MODEL, "A model revision requires input artifacts.")
        _check_names(artifacts)
        return artifacts

    def _revision(self, connection: sqlite3.Connection, model: ModelRef) -> ModelRevision:
        revision = records.require(
            connection, ModelRevision, str(model.session_id), str(model.revision_id)
        )
        self._inputs(connection, revision)
        return revision

    def _save_revision(
        self, connection: sqlite3.Connection, revision: ModelRevision
    ) -> ModelRevision:
        revision = ModelRevision.model_validate(revision)
        _session(connection, revision.model.session_id)
        self._inputs(connection, revision)
        if revision.parent is not None:
            records.require(
                connection,
                ModelRevision,
                str(revision.parent.session_id),
                str(revision.parent.revision_id),
            )
        return records.immutable(connection, revision)

    @_operation
    def save_revision(self, revision: ModelRevision) -> ModelRevision:
        with self._database.transaction(write=True) as connection:
            return self._save_revision(connection, revision)

    @_operation
    def get_revision(self, model: ModelRef) -> ModelRevision:
        with self._database.transaction() as connection:
            return self._revision(connection, model)

    @_operation
    def clone_revision(
        self,
        source: ModelRef,
        revision_id: RevisionId,
        *,
        replacements: tuple[ArtifactId, ...] = (),
    ) -> ModelRevision:
        with self._database.transaction(write=True) as connection:
            parent = self._revision(connection, source)
            original = self._inputs(connection, parent)
            changed = tuple(
                self._artifact(
                    connection, ArtifactRef(session_id=source.session_id, artifact_id=item)
                )
                for item in replacements
            )
            _check_names(changed)
            by_path = {artifact.relative_path: artifact for artifact in original}
            entrypoint_path = next(
                item.relative_path
                for item in original
                if item.ref.artifact_id == parent.inputs.entrypoint
            )
            by_path.update({artifact.relative_path: artifact for artifact in changed})
            clone = ModelRevision(
                model=ModelRef(session_id=source.session_id, revision_id=revision_id),
                inputs=ModelInputs(
                    artifacts=tuple(item.ref.artifact_id for item in by_path.values()),
                    entrypoint=by_path[entrypoint_path].ref.artifact_id,
                ),
                unit_system=parent.unit_system,
                coordinates=parent.coordinates,
                parent=source,
            )
            return self._save_revision(connection, clone)

    def _job_artifacts(self, connection: sqlite3.Connection, job: Job) -> None:
        if job.submission is not None and job.submission.run_metadata is not None:
            if (
                self._artifact(connection, job.submission.run_metadata).kind
                != ArtifactKind.METADATA
            ):
                raise fail(ErrorCode.INVALID_MODEL, "Run metadata requires a metadata artifact.")
        for ref in job.logs:
            if self._artifact(connection, ref).kind != ArtifactKind.LOG:
                raise fail(ErrorCode.INVALID_MODEL, "Job logs require log artifacts.")

    @_operation
    def save_job(self, job: Job, *, expected: Job | None = None) -> Job:
        job = Job.model_validate(job)
        with self._database.transaction(write=True) as connection:
            self._revision(connection, job.model)
            if job.events and job.events[-1].state != job.state:
                raise fail(
                    ErrorCode.INVALID_TRANSITION, "The final event must match the job state."
                )
            self._job_artifacts(connection, job)
            previous = records.find(connection, Job, str(job.model.session_id), str(job.job_id))
            if previous is None:
                if expected is not None:
                    raise fail(ErrorCode.CONFLICT, "The expected prior job does not exist.")
                if (
                    job.state != JobState.QUEUED
                    or job.cancel_requested
                    or job.supervisor is not None
                    or job.process is not None
                    or job.container_id is not None
                    or job.logs
                ):
                    raise fail(
                        ErrorCode.INVALID_TRANSITION,
                        "A new job must be queued without cancellation or execution metadata.",
                    )
                return records.insert(connection, job)
            if previous == job:
                return previous
            if expected != previous:
                raise fail(
                    ErrorCode.CONFLICT, "The stored job differs from the expected prior record."
                )
            _check_job_update(previous, job)
            records.replace_job(connection, job)
            return job

    @_operation
    def get_job(self, job: JobRef) -> Job:
        with self._database.transaction() as connection:
            return records.require(connection, Job, str(job.session_id), str(job.job_id))

    @_operation
    def list_jobs(self, session_id: SessionId) -> tuple[Job, ...]:
        with self._database.transaction() as connection:
            _session(connection, session_id)
            return records.all_records(connection, Job, str(session_id))

    @_operation
    def save_result(self, result: Result) -> Result:
        result = Result.model_validate(result)
        with self._database.transaction(write=True) as connection:
            self._revision(connection, result.model)
            job = records.require(connection, Job, str(result.model.session_id), str(result.job_id))
            if job.model != result.model or job.state != JobState.SUCCEEDED:
                raise fail(
                    ErrorCode.INVALID_MODEL,
                    "A result requires its exact successfully completed job.",
                )
            if result.manifest is not None:
                for output in result.manifest.outputs:
                    if self._artifact(connection, output.artifact).kind != ArtifactKind.OUTPUT:
                        raise fail(
                            ErrorCode.INVALID_MODEL, "Result outputs require output artifacts."
                        )
                for ref in (result.manifest.numerical_data, result.manifest.assessment_evidence):
                    if self._artifact(connection, ref).kind != ArtifactKind.METADATA:
                        raise fail(
                            ErrorCode.INVALID_MODEL, "Result evidence requires metadata artifacts."
                        )
            return records.immutable(connection, result)

    @_operation
    def get_result(self, session_id: SessionId, result_id: ResultId) -> Result:
        with self._database.transaction() as connection:
            return records.require(connection, Result, str(session_id), str(result_id))

    @_operation
    def save_observation(self, observation: Observation) -> Observation:
        observation = Observation.model_validate(observation)
        with self._database.transaction(write=True) as connection:
            context = observation.context
            result = records.require(
                connection, Result, str(context.model.session_id), str(context.result_id)
            )
            try:
                context.require_result(result)
            except ValueError as error:
                raise fail(ErrorCode.INVALID_MODEL, str(error)) from error
            self._revision(connection, context.model)
            artifact = self._artifact(connection, observation.image.artifact)
            if artifact.kind != ArtifactKind.IMAGE:
                raise fail(ErrorCode.INVALID_MODEL, "An observation requires an image artifact.")
            return records.immutable(connection, observation)

    @_operation
    def get_observation(self, session_id: SessionId, observation_id: ObservationId) -> Observation:
        with self._database.transaction() as connection:
            observation = records.require(
                connection, Observation, str(session_id), str(observation_id)
            )
            self._files.check(observation.image.artifact)
            return observation

    @_operation
    def save_checkpoint(self, checkpoint: ProjectCheckpoint) -> ProjectCheckpoint:
        checkpoint = ProjectCheckpoint.model_validate(checkpoint)
        with self._database.transaction(write=True) as connection:
            self._revision(connection, checkpoint.model)
            artifact = self._artifact(connection, checkpoint.project)
            if artifact.kind != ArtifactKind.PROJECT:
                raise fail(
                    ErrorCode.INVALID_MODEL, "A checkpoint requires a saved-project artifact."
                )
            for result_id in checkpoint.result_ids:
                records.require(
                    connection, Result, str(checkpoint.model.session_id), str(result_id)
                )
            return records.immutable(connection, checkpoint)

    @_operation
    def get_checkpoint(
        self, session_id: SessionId, checkpoint_id: CheckpointId
    ) -> ProjectCheckpoint:
        with self._database.transaction() as connection:
            checkpoint = records.require(
                connection, ProjectCheckpoint, str(session_id), str(checkpoint_id)
            )
            self._revision(connection, checkpoint.model)
            self._files.check(checkpoint.project)
            return checkpoint

    def _recovery_jobs(
        self, connection: sqlite3.Connection, session_id: SessionId, expected: tuple[Job, ...]
    ) -> tuple[Job, ...]:
        if len({job.job_id for job in expected}) != len(expected):
            raise fail(ErrorCode.INVALID_MODEL, "Each recovery job must be listed once.")
        recovered = []
        for job in expected:
            if job.model.session_id != session_id:
                raise fail(ErrorCode.INVALID_MODEL, "Recovery jobs must belong to this session.")
            current = records.require(connection, Job, str(session_id), str(job.job_id))
            if current != job:
                raise fail(ErrorCode.CONFLICT, "A recovery job differs from its expected record.")
            if current.state in {JobState.QUEUED, JobState.RUNNING}:
                current = current.transition(JobState.UNKNOWN)
                if current.events:
                    event = JobEvent(
                        at=max(datetime.now(UTC), current.events[-1].at),
                        state=JobState.UNKNOWN,
                        message="Recovery could not confirm the execution outcome.",
                    )
                    current = Job.model_validate(
                        {**current.model_dump(), "events": (*current.events, event)}
                    )
            recovered.append(current)
        return tuple(recovered)

    @_operation
    def reconcile(
        self, session_id: SessionId, *, expected_jobs: tuple[Job, ...] = ()
    ) -> RecoveryReport:
        with self._database.transaction(write=True) as connection:
            _session(connection, session_id)
            recovered = self._recovery_jobs(connection, session_id, expected_jobs)
            artifacts = records.all_records(connection, Artifact, str(session_id))
            unavailable = []
            for artifact in artifacts:
                try:
                    self._files.check(artifact.ref)
                except ContractError as error:
                    unavailable.append(ArtifactProblem(artifact=artifact.ref, error=error.error))
            for job in recovered:
                records.replace_job(connection, job)
            removed = self._files.reconcile(
                session_id, frozenset(artifact.ref.artifact_id for artifact in artifacts)
            )
            return RecoveryReport(
                session_id=session_id,
                jobs=recovered,
                removed_artifacts=removed,
                unavailable_artifacts=tuple(unavailable),
            )
