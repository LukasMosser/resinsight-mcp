"""Shared job operations and exclusive supervisor leases."""

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.jobs import Job, JobEvent, JobRef
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def require[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except OSError as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED,
                        message=str(error),
                        effect=MutationEffect.UNKNOWN,
                    )
                )
            )

    return run


def event(job: Job, message: str) -> Job:
    at = max(datetime.now(UTC), job.events[-1].at) if job.events else datetime.now(UTC)
    return Job.model_validate(
        {
            **job.model_dump(),
            "events": (
                *job.events,
                JobEvent(at=at, state=job.state, message=message),
            ),
        }
    )


def update(store: SqliteWorkspaceStore, ref: JobRef, change: Callable[[Job], Job]) -> Job:
    """Repeat only a rejected comparison, never an uncertain write."""
    for _ in range(8):
        previous = require(store.get_job(ref))
        outcome = store.save_job(change(previous), expected=previous)
        if isinstance(outcome.outcome, Success):
            return outcome.outcome.value
        if (
            outcome.outcome.error.code != ErrorCode.CONFLICT
            or outcome.outcome.error.effect != MutationEffect.NOT_APPLIED
        ):
            raise ContractError(outcome.outcome.error)
    raise ContractError(Error(code=ErrorCode.BUSY, message="Job updates continued to conflict."))


@contextmanager
def lease(path: Path, *, blocking: bool = False) -> Iterator[int]:
    """Keep the same lock file for every controller and supervisor."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(descriptor, flags)
        except BlockingIOError as error:
            raise ContractError(
                Error(
                    code=ErrorCode.BUSY,
                    message="A job supervisor or controller still owns this lease.",
                )
            ) from error
        yield descriptor
    finally:
        # Closing preserves an inherited supervisor lock until its final descriptor closes.
        os.close(descriptor)


def job_directory(workspace: Path, ref: JobRef) -> Path:
    return workspace / "jobs-runtime" / str(ref.session_id) / str(ref.job_id)
