"""Public job behavior with small real commands and independent clients."""

import json
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
import pytest

from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.jobs import (
    Job,
    JobRequest,
    JobState,
    ResourceLimits,
    ResourcePolicy,
)
from resinsight_mcp.jobs import DurableJobController, JobCommand
from resinsight_mcp.jobs._common import job_directory, require

from ._support import controller, reference, wait_file, wait_job


def test_default_enforcement_rejected_before_launch(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = controller(root, "raise RuntimeError('Must not launch')")
    default = JobRequest(prepared=request.prepared, limits=request.limits)
    outcome = service.submit(default).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.UNSUPPORTED_OPERATION
    assert require(service.store.list_jobs(request.prepared.revision.model.session_id)) == ()


@pytest.mark.parametrize("code", [0, 7])
def test_exit_status_logs_and_policy(workspace: tuple[Path, JobRequest], code: int) -> None:
    root, request = workspace
    service = controller(
        root,
        f"import sys; print('job output'); print('job error', file=sys.stderr); sys.exit({code})",
    )
    job = require(service.submit(request))
    assert job.state == JobState.QUEUED
    completed = wait_job(service, job)
    assert completed.exit_code == code
    assert completed.state == (JobState.SUCCEEDED if code == 0 else JobState.FAILED)
    assert completed.model == request.prepared.revision.model
    assert completed.submission is not None
    assert completed.submission.resource_policy == ResourcePolicy.WALL_TIME_ONLY
    assert completed.process is not None and completed.supervisor is not None
    assert [item.state for item in completed.events] == [
        JobState.QUEUED,
        JobState.QUEUED,
        JobState.RUNNING,
        completed.state,
    ]
    logs = []
    for artifact in completed.logs:
        with service.store.open_artifact(artifact) as source:
            logs.append(source.read().decode())
    assert logs[0].strip() == "job output"
    assert logs[1].strip() == "job error"
    assert "Resource policy: wall_time_only" in logs[2]
    restarted = controller(root, "raise RuntimeError('Must not relaunch')")
    assert require(restarted.poll(reference(job))) == completed


def test_cancel_tree_and_preserve_terminal(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    child = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)"
    source = (
        "import json,pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "pathlib.Path('child.json').write_text(json.dumps(child.pid)); time.sleep(20)"
    )
    service = controller(root, source)
    job = require(service.submit(request))
    wait_file(root / "child.json")
    child_pid = json.loads((root / "child.json").read_text())
    canceled = require(service.request_cancel(reference(job)))
    assert canceled.cancel_requested
    completed = wait_job(service, job)
    assert completed.state == JobState.CANCELED and completed.termination_confirmed
    assert (
        not psutil.pid_exists(child_pid)
        or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    )
    assert require(service.request_cancel(reference(job))) == completed


def test_wall_deadline_requires_confirmed_termination(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    request = JobRequest(
        prepared=request.prepared,
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=1),
    )
    service = controller(
        root, "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)"
    )
    job = require(service.submit(request))
    completed = wait_job(service, job)
    assert completed.state == JobState.FAILED and completed.termination_confirmed
    assert completed.exit_code == -signal.SIGKILL
    assert completed.error is not None and "wall deadline" in completed.error.message


def test_service_process_disconnect_preserves_job(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    payload = root / "request.json"
    payload.write_text(request.model_dump_json())
    source = """
import sys
from pathlib import Path
from resinsight_mcp.contracts.jobs import JobRequest
from resinsight_mcp.jobs import DurableJobController, JobCommand
root=Path(sys.argv[1])
command="import pathlib,time; time.sleep(1); pathlib.Path('ran').touch()"
service=DurableJobController(root, lambda request: JobCommand(
    argv=(sys.executable,'-c',command),working_directory=root))
result=service.submit(JobRequest.model_validate_json((root/'request.json').read_text()))
print(result.model_dump_json(),flush=True)
"""
    client = subprocess.run(
        [sys.executable, "-c", source, str(root)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    from resinsight_mcp.contracts.errors import OperationResult

    job = require(OperationResult[Job].model_validate_json(client.stdout))
    restarted = controller(root, "raise RuntimeError('Must not relaunch')")
    completed = wait_job(restarted, job)
    assert completed.state == JobState.SUCCEEDED
    assert completed.job_id == job.job_id and completed.model == job.model
    assert completed.submission == job.submission
    assert (root / "ran").exists()


def test_recovery_refuses_live_supervisor(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = controller(root, "import time; time.sleep(20)")
    job = require(service.submit(request))
    try:
        wait_job(service, job, {JobState.RUNNING})
        result = service.reconcile(job.model.session_id).outcome
        assert isinstance(result, Failure) and result.error.code == ErrorCode.BUSY
    finally:
        require(service.request_cancel(reference(job)))
        wait_job(service, job)


def test_concurrent_cancel_keeps_intent(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = controller(root, "import time; time.sleep(0.3)")
    job = require(service.submit(request))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(lambda _: service.request_cancel(reference(job)), range(4)))
    assert all(require(result).cancel_requested for result in results)
    completed = wait_job(service, job)
    assert completed.cancel_requested
    assert completed.state in {JobState.CANCELED, JobState.SUCCEEDED}


def test_missing_executable_records_failed_launch(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = DurableJobController(
        root, lambda request: JobCommand(argv=(str(root / "missing"),), working_directory=root)
    )
    job = require(service.submit(request))
    failed = wait_job(service, job)
    assert failed.state == JobState.FAILED
    assert failed.exit_code is None and failed.termination_confirmed
    assert failed.process is None
    assert failed.error is not None and "could not start" in failed.error.message
    runtime = job_directory(root, reference(job))
    assert (runtime / "supervisor.log").is_file()


def test_supervisor_rejects_caller_module_shadowing(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, request = workspace
    untrusted = root / "caller-directory"
    package = untrusted / "resinsight_mcp"
    package.mkdir(parents=True)
    marker = root / "shadow-executed"
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    service = controller(root, "print('The trusted supervisor ran')")
    with monkeypatch.context() as patch:
        patch.chdir(untrusted)
        patch.setenv("PYTHONPATH", str(untrusted))
        job = require(service.submit(request))
    completed = wait_job(service, job)
    assert completed.state == JobState.SUCCEEDED
    assert not marker.exists()
