"""Durable submission and cancellation without a client lifetime dependency."""

import subprocess
import sys
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import Annotated, Self

from pydantic import Field, model_validator

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import JobId, SessionId
from resinsight_mcp.contracts.jobs import (
    Job,
    JobRef,
    JobRequest,
    JobState,
    JobSubmission,
    ResourcePolicy,
)
from resinsight_mcp.contracts.workspace import RecoveryReport
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._common import event, job_directory, lease, operation, require, update

TERMINAL = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED})


class JobCommand(Record):
    """A trusted adapter supplies the executable and an existing run directory."""

    argv: Annotated[tuple[str, ...], Field(min_length=1)]
    working_directory: Path

    @model_validator(mode="after")
    def check_paths(self) -> Self:
        if not Path(self.argv[0]).is_absolute() or not self.working_directory.is_absolute():
            raise ValueError("Use an absolute executable and working directory.")
        if any("\0" in argument for argument in self.argv):
            raise ValueError("Command arguments cannot contain a null character.")
        return self


type CommandResolver = Callable[[JobRequest], JobCommand]


class DurableJobController:
    """Supervise trusted local commands on macOS and Linux."""

    def __init__(self, workspace: Path, resolver: CommandResolver) -> None:
        if sys.platform not in {"darwin", "linux"}:
            raise ContractError(
                Error(code=ErrorCode.UNSUPPORTED_OPERATION, message="Jobs require macOS or Linux.")
            )
        self.workspace = workspace.resolve(strict=True)
        self.store = SqliteWorkspaceStore.open(self.workspace)
        self.resolver = resolver
        (self.workspace / "jobs-runtime").mkdir(mode=0o700, exist_ok=True)

    def _session_directory(self, session_id: SessionId) -> Path:
        require(self.store.get_session(session_id))
        directory = self.workspace / "jobs-runtime" / str(session_id)
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    @operation
    def submit(self, request: JobRequest) -> Job:
        if request.resource_policy != ResourcePolicy.WALL_TIME_ONLY:
            raise ContractError(
                Error(
                    code=ErrorCode.UNSUPPORTED_OPERATION,
                    message="Select wall_time_only. CPU and memory enforcement is unavailable.",
                )
            )
        stored = require(self.store.get_revision(request.prepared.revision.model))
        if stored != request.prepared.revision:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="Submission differs from the stored revision.",
                )
            )
        command = self.resolver(request)
        if not command.working_directory.is_dir():
            raise ContractError(
                Error(code=ErrorCode.INVALID_PATH, message="The run directory is missing.")
            )
        job = Job(
            job_id=JobId.new(),
            model=stored.model,
            backend=request.prepared.backend,
            state=JobState.QUEUED,
            submission=JobSubmission(
                limits=request.limits,
                argv=command.argv,
                working_directory=str(command.working_directory),
                submitted_at=datetime.now(UTC),
                resource_policy=request.resource_policy,
            ),
        )
        job = event(job, "Submission recorded before supervisor launch.")
        ref = JobRef(session_id=job.model.session_id, job_id=job.job_id)
        session_directory = self._session_directory(ref.session_id)
        with lease(session_directory / "controller.lock"):
            directory = job_directory(self.workspace, ref)
            directory.mkdir(mode=0o700)
            with lease(directory / "supervisor.lock") as descriptor:
                require(self.store.save_job(job))
                self._start_supervisor(ref, descriptor, directory)
        return job

    def _start_supervisor(self, ref: JobRef, descriptor: int, directory: Path) -> None:
        try:
            with (directory / "supervisor.log").open("xb") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-m",
                        "resinsight_mcp.jobs._supervisor",
                        str(self.workspace),
                        str(ref.session_id),
                        str(ref.job_id),
                        str(descriptor),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    pass_fds=(descriptor,),
                    close_fds=True,
                )
        except OSError as error:
            try:
                update(
                    self.store,
                    ref,
                    lambda job: event(
                        job.transition(JobState.UNKNOWN), "Supervisor launch was not acknowledged."
                    ),
                )
            except ContractError:
                # The queued record already exists, even if uncertainty cannot be published.
                pass
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message=f"Supervisor launch is uncertain for {ref.job_id}: {error}",
                    effect=MutationEffect.UNKNOWN,
                )
            ) from error
        try:
            Thread(target=process.wait, daemon=True).start()
        except RuntimeError as error:
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message=f"Supervisor started for {ref.job_id}, but its waiter failed: {error}",
                    effect=MutationEffect.UNKNOWN,
                )
            ) from error

    @operation
    def poll(self, job: JobRef) -> Job:
        return require(self.store.get_job(job))

    @operation
    def request_cancel(self, job: JobRef) -> Job:
        return update(
            self.store,
            job,
            lambda current: (
                current
                if current.state in TERMINAL or current.cancel_requested
                else event(current.request_cancel(), "Cancellation requested.")
            ),
        )

    @operation
    def reconcile(self, session_id: SessionId) -> RecoveryReport:
        """Require stopped supervisors before reconciling selected interrupted jobs."""
        directory = self._session_directory(session_id)
        with lease(directory / "controller.lock"), ExitStack() as locks:
            jobs = require(self.store.list_jobs(session_id))
            selected = tuple(job for job in jobs if job.state not in TERMINAL)
            for job in jobs:
                ref = JobRef(session_id=session_id, job_id=job.job_id)
                runtime = job_directory(self.workspace, ref)
                if not runtime.is_dir():
                    if job.state in TERMINAL and job.submission is None:
                        continue
                    raise ContractError(
                        Error(
                            code=ErrorCode.NOT_FOUND,
                            message="The supervisor lease directory is missing.",
                        )
                    )
                locks.enter_context(lease(runtime / "supervisor.lock"))
            return require(self.store.reconcile(session_id, expected_jobs=selected))
