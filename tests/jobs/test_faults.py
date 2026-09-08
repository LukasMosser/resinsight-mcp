"""Synchronized failures expose false success and unsafe recovery."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO

import psutil
import pytest

from resinsight_mcp.contracts.errors import (
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
)
from resinsight_mcp.contracts.jobs import Job, JobRequest, JobState, ResourceLimits, ResourcePolicy
from resinsight_mcp.contracts.sessions import ProcessIdentity
from resinsight_mcp.jobs import DurableJobController, _supervisor
from resinsight_mcp.jobs import service as service_module
from resinsight_mcp.jobs._common import event, job_directory, lease, require
from resinsight_mcp.jobs._process import OwnedProcess, ProcessOwnershipError

from ._support import controller, reference, wait_file, wait_job


def queued(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch, source: str
) -> tuple[DurableJobController, Job, Path]:
    root, request = workspace
    service = controller(root, source)

    def hold_launch(ref: object, descriptor: int, directory: Path) -> None:
        (directory / "supervisor.log").write_text("Controlled supervisor test.\n")

    monkeypatch.setattr(service, "_start_supervisor", hold_launch)
    job = require(service.submit(request))
    return service, job, job_directory(root, reference(job))


def test_cancel_during_supervisor_claim_preserves_intent(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job, directory = queued(workspace, monkeypatch, "raise RuntimeError('Must not run')")
    save = service.store.save_job
    raced = False

    def save_with_cancel(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        nonlocal raced
        if updated.supervisor is not None and not raced:
            raced = True
            require(service.request_cancel(reference(job)))
        return save(updated, expected=expected)

    monkeypatch.setattr(service.store, "save_job", save_with_cancel)
    with lease(directory / "supervisor.lock"):
        _supervisor._execute(service.store, reference(job), directory)
    completed = require(service.poll(reference(job)))
    assert completed.state == JobState.CANCELED and completed.cancel_requested
    assert completed.termination_confirmed and completed.process is None
    assert raced


def test_failed_uncertainty_write_still_reports_committed_job(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    service = controller(root, "raise RuntimeError('Must not run')")
    save = service.store.save_job

    def save_without_updates(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        if expected is not None:
            return OperationResult(
                outcome=Failure(error=Error(code=ErrorCode.BUSY, message="Storage is busy."))
            )
        return save(updated, expected=expected)

    def fail_spawn(*args: object, **kwargs: object) -> None:
        raise OSError("Injected supervisor launch failure.")

    monkeypatch.setattr(service.store, "save_job", save_without_updates)
    monkeypatch.setattr(subprocess, "Popen", fail_spawn)
    outcome = service.submit(request).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.effect == MutationEffect.UNKNOWN
    jobs = require(service.store.list_jobs(request.prepared.revision.model.session_id))
    assert len(jobs) == 1 and str(jobs[0].job_id) in outcome.error.message
    assert jobs[0].state == JobState.QUEUED


def test_wall_deadline_runs_during_blocked_state_publication(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    request = JobRequest(
        prepared=request.prepared,
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=1),
    )
    service, job, directory = queued(
        (root, request),
        monkeypatch,
        "import pathlib,time; time.sleep(1.5); pathlib.Path('overran').touch(); time.sleep(10)",
    )
    save = service.store.save_job

    def delayed_save(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        if updated.state == JobState.RUNNING:
            time.sleep(2)
        return save(updated, expected=expected)

    monkeypatch.setattr(service.store, "save_job", delayed_save)
    with lease(directory / "supervisor.lock"):
        _supervisor._execute(service.store, reference(job), directory)
    completed = require(service.poll(reference(job)))
    assert completed.state == JobState.FAILED and completed.termination_confirmed
    assert completed.exit_code == -signal.SIGTERM
    assert not (root / "overran").exists()


def test_lost_supervisor_preserves_unknown_and_never_relaunches(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    service = controller(
        root, "import pathlib,time; pathlib.Path('started').touch(); time.sleep(1)"
    )
    popen = subprocess.Popen
    supervisors: list[subprocess.Popen[bytes]] = []

    def capture(
        args: list[str],
        *,
        stdin: int,
        stdout: BinaryIO,
        stderr: int,
        start_new_session: bool,
        pass_fds: tuple[int, ...],
        close_fds: bool,
    ) -> subprocess.Popen[bytes]:
        child = popen(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            start_new_session=start_new_session,
            pass_fds=pass_fds,
            close_fds=close_fds,
        )
        supervisors.append(child)
        return child

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", capture)
        job = require(service.submit(request))
    running = wait_job(service, job, {JobState.RUNNING})
    wait_file(root / "started")
    supervisors[0].kill()
    supervisors[0].wait(timeout=5)
    restarted = controller(root, "raise RuntimeError('Must not relaunch')")
    report = require(restarted.reconcile(job.model.session_id))
    unknown = report.jobs[0]
    assert unknown.state == JobState.UNKNOWN
    assert unknown.job_id == running.job_id and unknown.model == running.model
    assert unknown.submission == running.submission and unknown.process == running.process
    canceled = require(restarted.request_cancel(reference(job)))
    assert canceled.state == JobState.UNKNOWN and not canceled.termination_confirmed
    assert canceled.cancel_requested and canceled.exit_code is None
    assert running.process is not None
    deadline = time.monotonic() + 5
    while psutil.pid_exists(running.process.pid):
        if psutil.Process(running.process.pid).status() == psutil.STATUS_ZOMBIE:
            break
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_stale_persisted_identity_never_authorizes_signal(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job, _ = queued(workspace, monkeypatch, "raise RuntimeError('Must not run')")
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True
    ) as unrelated:
        try:
            stale = ProcessIdentity(pid=unrelated.pid, start_marker="stale lifetime")
            previous = require(service.poll(reference(job)))
            recorded = event(
                Job.model_validate(
                    {
                        **previous.transition(JobState.RUNNING).model_dump(),
                        "process": stale,
                        "process_group_id": stale.pid,
                    }
                ),
                "Interrupted test ownership record.",
            )
            require(service.store.save_job(recorded, expected=previous))
            require(service.reconcile(job.model.session_id))
            canceled = require(service.request_cancel(reference(job)))
            assert canceled.state == JobState.UNKNOWN and not canceled.termination_confirmed
            assert unrelated.poll() is None
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)


def test_uncertain_update_is_not_retried(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job, _ = queued(workspace, monkeypatch, "raise RuntimeError('Must not run')")
    calls = 0

    def uncertain(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        nonlocal calls
        calls += 1
        return OperationResult(
            outcome=Failure(
                error=Error(
                    code=ErrorCode.CONFLICT,
                    message="Commit acknowledgement was lost.",
                    effect=MutationEffect.UNKNOWN,
                )
            )
        )

    monkeypatch.setattr(service.store, "save_job", uncertain)
    result = service.request_cancel(reference(job)).outcome
    assert isinstance(result, Failure) and result.error.effect == MutationEffect.UNKNOWN
    assert calls == 1


def test_recovery_after_interrupted_launch(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    (root / "request.json").write_text(request.model_dump_json())
    source = """
import os,sys
from pathlib import Path
from resinsight_mcp.jobs import DurableJobController,JobCommand
from resinsight_mcp.contracts.jobs import JobRequest
root=Path(sys.argv[1])
service=DurableJobController(root,lambda request: JobCommand(
    argv=(sys.executable,'-c',"from pathlib import Path; Path('unexpected').touch()"),
    working_directory=root))
service._start_supervisor=lambda *args: os._exit(23)
service.submit(JobRequest.model_validate_json((root/'request.json').read_text()))
"""
    client = subprocess.run([sys.executable, "-c", source, str(root)], check=False, timeout=10)
    assert client.returncode == 23
    service = controller(root, "raise RuntimeError('Must not relaunch')")
    jobs = require(service.store.list_jobs(request.prepared.revision.model.session_id))
    assert len(jobs) == 1 and jobs[0].state == JobState.QUEUED
    recovered = require(service.reconcile(jobs[0].model.session_id)).jobs[0]
    assert recovered.state == JobState.UNKNOWN and recovered.job_id == jobs[0].job_id
    assert recovered.model == jobs[0].model and recovered.process is None
    assert not (root / "unexpected").exists()


def controlled_run(
    service: DurableJobController, job: Job, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setattr(_supervisor.SqliteWorkspaceStore, "open", lambda root: service.store)
    with lease(directory / "supervisor.lock") as descriptor:
        return _supervisor.run(service.workspace, reference(job), os.dup(descriptor))


def test_deadline_escalates_despite_unavailable_census(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    request = JobRequest(
        prepared=request.prepared,
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=1),
    )
    service, job, directory = queued(
        (root, request),
        monkeypatch,
        "import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "time.sleep(2); pathlib.Path('overran').touch(); time.sleep(10)",
    )
    saved = service.store.save_job
    members = OwnedProcess.live_members
    start = time.monotonic()

    def delayed_save(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        if updated.state == JobState.RUNNING:
            time.sleep(2)
        return saved(updated, expected=expected)

    def unavailable(self: OwnedProcess) -> tuple[int, ...]:
        if time.monotonic() - start < 1.8:
            raise ProcessOwnershipError("An unrelated process could not be inspected.")
        return members(self)

    monkeypatch.setattr(service.store, "save_job", delayed_save)
    monkeypatch.setattr(OwnedProcess, "live_members", unavailable)
    assert controlled_run(service, job, directory, monkeypatch) == 1
    unknown = require(service.poll(reference(job)))
    assert unknown.state == JobState.UNKNOWN and unknown.exit_code is None
    assert not unknown.termination_confirmed
    assert not (root / "overran").exists()
    assert unknown.process is not None and not psutil.pid_exists(unknown.process.pid)


def test_failed_deadline_thread_cleans_owned_command(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job, directory = queued(workspace, monkeypatch, "import time; time.sleep(10)")
    start = OwnedProcess.start
    owned: list[OwnedProcess] = []

    def capture(
        argv: tuple[str, ...], cwd: Path, stdout: BinaryIO, stderr: BinaryIO
    ) -> OwnedProcess:
        process = start(argv, cwd, stdout, stderr)
        owned.append(process)
        return process

    def failed_timer(timer: object) -> None:
        raise RuntimeError("The deadline thread could not start.")

    monkeypatch.setattr(OwnedProcess, "start", capture)
    monkeypatch.setattr(_supervisor.Timer, "start", failed_timer)
    assert controlled_run(service, job, directory, monkeypatch) == 1
    unknown = require(service.poll(reference(job)))
    assert unknown.state == JobState.UNKNOWN
    assert len(owned) == 1 and not psutil.pid_exists(owned[0].identity.pid)


def test_failed_log_publication_never_reports_success(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job, directory = queued(workspace, monkeypatch, "print('Command completed')")

    def unavailable(*args: object) -> OperationResult[object]:
        return OperationResult(
            outcome=Failure(
                error=Error(
                    code=ErrorCode.STORAGE_FAILED,
                    message="The log commit acknowledgement was lost.",
                    effect=MutationEffect.UNKNOWN,
                )
            )
        )

    monkeypatch.setattr(service.store, "write_artifact", unavailable)
    assert controlled_run(service, job, directory, monkeypatch) == 1
    unknown = require(service.poll(reference(job)))
    assert unknown.state == JobState.UNKNOWN and unknown.exit_code is None
    assert unknown.logs == ()
    assert (directory / "stdout.log").read_text().strip() == "Command completed"


def test_failed_supervisor_waiter_retains_job_identity(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    service = controller(root, "print('Job survives waiter failure')")

    def unavailable(thread: object) -> None:
        raise RuntimeError("The waiter thread could not start.")

    with monkeypatch.context() as patch:
        patch.setattr(service_module.Thread, "start", unavailable)
        outcome = service.submit(request).outcome
    assert isinstance(outcome, Failure) and outcome.error.effect == MutationEffect.UNKNOWN
    jobs = require(service.store.list_jobs(request.prepared.revision.model.session_id))
    assert len(jobs) == 1 and str(jobs[0].job_id) in outcome.error.message
    completed = wait_job(service, jobs[0])
    assert completed.state == JobState.SUCCEEDED
