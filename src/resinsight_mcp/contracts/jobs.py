"""Execution state and result lineage, separate from numerical acceptance."""

from enum import StrEnum
from typing import Self

from pydantic import PositiveInt, model_validator

from ._base import Record
from .engineering import ModelRef, ReportSeries
from .errors import ContractError, Error, ErrorCode
from .identifiers import GridId, JobId, ResultId, SessionId
from .models import Backend, PreparedModel
from .sessions import ApplicationContext, ObjectKind, ObjectRef


class ResourceLimits(Record):
    cpu_count: PositiveInt
    memory_mib: PositiveInt
    wall_time_seconds: PositiveInt


class JobRequest(Record):
    prepared: PreparedModel
    limits: ResourceLimits


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
