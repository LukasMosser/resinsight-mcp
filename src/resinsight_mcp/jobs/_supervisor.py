"""One independent process owns one execution and its final publication."""

import fcntl
import os
import signal
import sys
import time
from pathlib import Path
from threading import Lock, Timer

import psutil

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode
from resinsight_mcp.contracts.identifiers import ArtifactId, JobId, SessionId
from resinsight_mcp.contracts.jobs import Job, JobRef, JobState
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ProcessIdentity
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._common import event, job_directory, require, update
from ._container import OwnedContainer
from ._process import (
    OwnedProcess,
    ProcessInspectionBusy,
    ProcessLaunchError,
    ProcessOwnershipError,
)

INTERVAL_SECONDS = 0.05
TERM_GRACE_SECONDS = 0.5
KILL_GRACE_SECONDS = 5.0


def _metadata(job: Job, **fields: object) -> Job:
    return Job.model_validate({**job.model_dump(), **fields})


def _publish_logs(
    store: SqliteWorkspaceStore, ref: JobRef, directory: Path
) -> tuple[ArtifactRef, ...]:
    artifacts = []
    for name in ("stdout", "stderr", "supervisor"):
        artifact = Artifact(
            ref=ArtifactRef(session_id=ref.session_id, artifact_id=ArtifactId.new()),
            relative_path=f"jobs/{ref.job_id}/{name}.log",
            kind=ArtifactKind.LOG,
        )
        with (directory / f"{name}.log").open("rb") as source:
            require(store.write_artifact(artifact, source))
        artifacts.append(artifact.ref)
    return tuple(artifacts)


def _empty(process: OwnedProcess, container: OwnedContainer | None = None) -> bool:
    try:
        local_empty = not process.live_members()
        return local_empty and (container is None or not container.inspect().state.running)
    except ProcessInspectionBusy:
        return False


def _await_empty(process: OwnedProcess, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if _empty(process):
                return True
        except ProcessOwnershipError:
            # A failed census cannot establish termination or prevent owned escalation.
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(INTERVAL_SECONDS)


def _stop(process: OwnedProcess) -> None:
    _signal(process, signal.SIGTERM)
    if _await_empty(process, TERM_GRACE_SECONDS):
        return
    _signal(process, signal.SIGKILL)
    if not _await_empty(process, KILL_GRACE_SECONDS):
        raise RuntimeError("Job termination could not be confirmed before the inspection deadline.")


def _signal(process: OwnedProcess, sig: int) -> None:
    try:
        process.signal_group(sig)
    except ProcessOwnershipError:
        # signal_group verifies ownership again before every attempted signal.
        # Failed confirmation does not prevent the next verified signal attempt.
        pass


class _Deadline:
    """Enforce the wall deadline even while workspace operations wait."""

    def __init__(
        self, process: OwnedProcess, deadline: float, container: OwnedContainer | None = None
    ) -> None:
        self.process = process
        self.container = container
        self.reason = "exit"
        self.error: Exception | None = None
        self.lock = Lock()
        self.timer = Timer(max(0.0, deadline - time.monotonic()), self._expire)
        self.timer.start()

    def _expire(self) -> None:
        try:
            self.stop("deadline")
        except Exception as error:
            self.error = error

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.reason != "exit":
                return
            inspection_error = None
            try:
                if _empty(self.process, self.container):
                    return
            except ProcessOwnershipError as error:
                inspection_error = error
            self.reason = reason
            try:
                if self.container is not None:
                    self.container.stop()
            finally:
                _stop(self.process)
            if inspection_error is not None:
                raise inspection_error

    def close(self) -> str:
        self.timer.cancel()
        self.timer.join()
        if self.error is not None:
            raise self.error
        return self.reason


def _observe(
    store: SqliteWorkspaceStore, ref: JobRef, process: OwnedProcess, deadline: _Deadline
) -> None:
    while not _empty(process, deadline.container):
        if deadline.error is not None:
            raise deadline.error
        job = require(store.get_job(ref))
        if job.state != JobState.RUNNING:
            raise RuntimeError("The stored job changed outside its active supervisor.")
        if job.cancel_requested:
            deadline.stop("cancel")
            return
        time.sleep(INTERVAL_SECONDS)


def _complete(job: Job, reason: str, code: int, logs: tuple[ArtifactRef, ...]) -> Job:
    if reason == "cancel":
        completed = job.transition(JobState.CANCELED, exit_code=code, termination_confirmed=True)
        message = "Cancellation completed with no live process in the owned group."
    elif reason == "deadline" or code != 0:
        message = (
            "The wall deadline terminated the job."
            if reason == "deadline"
            else f"The command exited with status {code}."
        )
        completed = job.transition(
            JobState.FAILED,
            exit_code=code,
            termination_confirmed=True,
            error=Error(code=ErrorCode.EXECUTION_FAILED, message=message),
        )
    else:
        completed = job.transition(JobState.SUCCEEDED, exit_code=code)
        message = "The command exited successfully with no live group members."
    return event(_metadata(completed, logs=logs), message)


def _claim(job: Job, identity: ProcessIdentity) -> Job:
    if job.state != JobState.QUEUED or job.supervisor is not None or job.submission is None:
        raise RuntimeError("Only an unclaimed queued submission can start a supervisor.")
    return event(
        _metadata(job, supervisor=identity), "The independent supervisor claimed execution."
    )


def _reap(process: OwnedProcess) -> int:
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while True:
        try:
            return process.finish()
        except ProcessInspectionBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(INTERVAL_SECONDS)


def _run_command(
    store: SqliteWorkspaceStore,
    ref: JobRef,
    process: OwnedProcess,
    end: float,
    container: OwnedContainer | None = None,
) -> tuple[str, int]:
    deadline: _Deadline | None = None
    try:
        deadline = _Deadline(process, end, container)
        update(
            store,
            ref,
            lambda previous: event(
                _metadata(
                    previous.transition(JobState.RUNNING),
                    process=process.identity,
                    process_group_id=process.group_id,
                ),
                "The owned command started.",
            ),
        )
        _observe(store, ref, process, deadline)
        reason = deadline.close()
        container_code = None
        if container is not None:
            snapshot = container.inspect()
            if snapshot.state.running or snapshot.state.status != "exited":
                raise RuntimeError("The container has no confirmed completed execution.")
            container_code = snapshot.state.exit_code
        code = _reap(process)
        if reason == "exit" and code == 0 and container_code is not None:
            code = container_code
        return reason, code
    except Exception:
        try:
            if deadline is not None:
                deadline.close()
        finally:
            try:
                if container is not None:
                    container.stop()
            finally:
                _stop(process)
                _reap(process)
        raise


def _execute(store: SqliteWorkspaceStore, ref: JobRef, directory: Path) -> None:
    identity = ProcessIdentity(pid=os.getpid(), start_marker=str(psutil.Process().create_time()))
    job = update(store, ref, lambda previous: _claim(previous, identity))
    submission = job.submission
    assert submission is not None
    print(f"Resource policy: {submission.resource_policy.value}", flush=True)
    print(f"Requested CPU count: {submission.limits.cpu_count}", flush=True)
    print(f"Requested memory MiB: {submission.limits.memory_mib}", flush=True)
    print(f"Wall deadline seconds: {submission.limits.wall_time_seconds}", flush=True)
    with (
        (directory / "stdout.log").open("xb") as stdout,
        (directory / "stderr.log").open("xb") as stderr,
    ):
        current = require(store.get_job(ref))
        if current.cancel_requested:
            reason, code = "cancel", 0
        else:
            end = time.monotonic() + submission.limits.wall_time_seconds
            container = None
            argv = submission.argv
            if submission.execution is not None:
                container = OwnedContainer(submission)
                container_id = container.create(min(10.0, submission.limits.wall_time_seconds))
                update(store, ref, lambda previous: _metadata(previous, container_id=container_id))
                if time.monotonic() >= end:
                    raise RuntimeError("The wall deadline expired before container start.")
                argv = container.start(end)
            try:
                process = OwnedProcess.start(
                    argv, Path(submission.working_directory), stdout, stderr
                )
            except ProcessLaunchError as error:
                if container is not None:
                    container.stop()
                print(f"Command launch failed: {error.__cause__}", flush=True)
                logs = _publish_logs(store, ref, directory)
                update(
                    store,
                    ref,
                    lambda previous: event(
                        _metadata(
                            previous.transition(
                                JobState.FAILED,
                                error=Error(
                                    code=ErrorCode.EXECUTION_FAILED,
                                    message="The command could not start.",
                                ),
                                termination_confirmed=True,
                            ),
                            logs=logs,
                        ),
                        "Command launch failed before execution started.",
                    ),
                )
                return
            except Exception:
                if container is not None:
                    container.stop()
                raise
            reason, code = _run_command(store, ref, process, end, container)
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
    print(f"Execution outcome: {reason}; exit status: {code}", flush=True)
    logs = _publish_logs(store, ref, directory)
    update(store, ref, lambda previous: _complete(previous, reason, code, logs))


def run(workspace: Path, ref: JobRef, descriptor: int) -> int:
    directory = job_directory(workspace, ref)
    expected = (directory / "supervisor.lock").stat()
    actual = os.fstat(descriptor)
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError("The inherited descriptor does not identify this supervisor lease.")
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = SqliteWorkspaceStore.open(workspace)
    try:
        _execute(store, ref, directory)
    except Exception as error:
        print(f"Supervision is uncertain: {error}", flush=True)
        detail = f"Supervision stopped without a confirmed outcome: {error}"
        try:
            update(
                store,
                ref,
                lambda job: event(
                    job if job.state == JobState.UNKNOWN else job.transition(JobState.UNKNOWN),
                    detail,
                ),
            )
        except ContractError as storage_error:
            print(f"The uncertain outcome could not be stored: {storage_error}", flush=True)
        return 1
    finally:
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(
        run(
            Path(sys.argv[1]),
            JobRef(session_id=SessionId(sys.argv[2]), job_id=JobId(sys.argv[3])),
            int(sys.argv[4]),
        )
    )
