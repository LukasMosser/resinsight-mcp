"""Execution state and result lineage, separate from numerical acceptance."""

from datetime import timedelta
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Self

from pydantic import AwareDatetime, PositiveInt, field_validator, model_validator

from ._base import Record, Text
from .engineering import ModelRef, ReportSeries
from .errors import ContractError, Error, ErrorCode
from .identifiers import GridId, JobId, ResultId, SessionId
from .models import ArtifactRef, Backend, PreparedModel
from .sessions import ApplicationContext, ObjectKind, ObjectRef, ProcessIdentity


class ResourceLimits(Record):
    cpu_count: PositiveInt
    memory_mib: PositiveInt
    wall_time_seconds: PositiveInt


class ResourcePolicy(StrEnum):
    ENFORCE = "enforce"
    WALL_TIME_ONLY = "wall_time_only"


class JobSubmission(Record):
    limits: ResourceLimits
    resource_policy: ResourcePolicy
    argv: tuple[str, ...]
    working_directory: str
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def check_command(self) -> Self:
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise ValueError("A submission requires an absolute executable path.")
        if any("\0" in argument for argument in self.argv):
            raise ValueError("Command arguments cannot contain null characters.")
        if not Path(self.working_directory).is_absolute() or "\0" in self.working_directory:
            raise ValueError("A submission requires an absolute working directory.")
        return self

    @field_validator("submitted_at")
    @classmethod
    def check_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Submission timestamps must use UTC.")
        return value


class JobRequest(Record):
    prepared: PreparedModel
    limits: ResourceLimits
    resource_policy: ResourcePolicy = ResourcePolicy.ENFORCE


class JobRef(Record):
    session_id: SessionId
    job_id: JobId


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class JobEvent(Record):
    at: AwareDatetime
    state: JobState
    message: Text

    @field_validator("at")
    @classmethod
    def check_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Event timestamps must use UTC.")
        return value


_TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED})
_JOB_TRANSITIONS = {
    JobState.QUEUED: frozenset(
        {JobState.RUNNING, JobState.FAILED, JobState.CANCELED, JobState.UNKNOWN}
    ),
    JobState.RUNNING: _TERMINAL_STATES | {JobState.UNKNOWN},
    JobState.UNKNOWN: _TERMINAL_STATES | {JobState.RUNNING},
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELED: frozenset(),
}


class Job(Record):
    job_id: JobId
    model: ModelRef
    backend: Backend
    state: JobState
    cancel_requested: bool = False
    termination_confirmed: bool = False
    exit_code: int | None = None
    error: Error | None = None
    submission: JobSubmission | None = None
    supervisor: ProcessIdentity | None = None
    process: ProcessIdentity | None = None
    process_group_id: PositiveInt | None = None
    logs: tuple[ArtifactRef, ...] = ()
    events: tuple[JobEvent, ...] = ()

    @model_validator(mode="after")
    def check_execution_metadata(self) -> Self:
        if (self.process is None) != (self.process_group_id is None):
            raise ValueError("Process identity and process group must be recorded together.")
        if self.process is not None and self.process_group_id != self.process.pid:
            raise ValueError("The job process must lead its process group.")
        if any(log.session_id != self.model.session_id for log in self.logs):
            raise ValueError("Job logs must belong to the job session.")
        if len(set(self.logs)) != len(self.logs):
            raise ValueError("Job logs must be unique.")
        if any(right.at < left.at for left, right in pairwise(self.events)):
            raise ValueError("Job event timestamps cannot move backward.")
        return self

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.state == JobState.SUCCEEDED and self.exit_code != 0:
            raise ValueError("Successful execution requires a confirmed zero exit code.")
        if self.state == JobState.CANCELED and not self.termination_confirmed:
            raise ValueError("Cancellation requires confirmation that no job process remains.")
        if self.state == JobState.FAILED and self.error is None:
            raise ValueError("A failed job requires its error record.")
        if self.state not in _TERMINAL_STATES and (
            self.exit_code is not None or self.termination_confirmed or self.error is not None
        ):
            raise ValueError("An active or unknown job cannot claim a terminal outcome.")
        if self.state != JobState.FAILED and self.error is not None:
            raise ValueError("Only a failed job carries an execution error.")
        return self

    def request_cancel(self) -> Self:
        """Record intent without claiming that execution has stopped."""
        if self.state in _TERMINAL_STATES:
            raise ContractError(
                Error(code=ErrorCode.INVALID_TRANSITION, message="The job is already terminal.")
            )
        return type(self).model_validate({**self.model_dump(), "cancel_requested": True})

    def transition(
        self,
        state: JobState,
        *,
        exit_code: int | None = None,
        error: Error | None = None,
        termination_confirmed: bool = False,
    ) -> Self:
        """The caller must obtain execution evidence before recording a new state."""
        if state not in _JOB_TRANSITIONS[self.state]:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_TRANSITION,
                    message=f"A job cannot change from {self.state} to {state}.",
                )
            )
        return type(self).model_validate(
            {
                **self.model_dump(),
                "state": state,
                "exit_code": exit_code,
                "error": error,
                "termination_confirmed": termination_confirmed,
            }
        )


class NumericalAssessment(StrEnum):
    NOT_ASSESSED = "not_assessed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Result(Record):
    result_id: ResultId
    job_id: JobId
    model: ModelRef
    grid_id: GridId
    report_series: ReportSeries
    assessment: NumericalAssessment = NumericalAssessment.NOT_ASSESSED


class ResultImportRequest(Record):
    context: ApplicationContext
    job: Job
    result: Result

    @model_validator(mode="after")
    def check_lineage(self) -> Self:
        if self.context.session_id != self.result.model.session_id:
            raise ValueError("The result and application must belong to the same session.")
        if self.job.model != self.result.model or self.job.job_id != self.result.job_id:
            raise ValueError("The result must identify this job and its exact model revision.")
        if self.job.state != JobState.SUCCEEDED:
            raise ValueError("Result import requires confirmed successful execution.")
        return self


class LoadedResult(Record):
    case: ObjectRef
    result: Result

    @model_validator(mode="after")
    def check_case(self) -> Self:
        if self.case.kind != ObjectKind.CASE:
            raise ValueError("A loaded result requires a case reference.")
        if self.case.context.session_id != self.result.model.session_id:
            raise ValueError("The loaded case must belong to the result session.")
        return self
