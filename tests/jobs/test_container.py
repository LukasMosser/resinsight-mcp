"""Exercise durable container completion and ownership through a command fixture."""

import json
import sys
from pathlib import Path

import pytest

from resinsight_mcp.contracts.jobs import DockerExecution, JobRequest, JobState, ResourcePolicy
from resinsight_mcp.jobs import DurableJobController, JobCommand
from resinsight_mcp.jobs._common import require
from resinsight_mcp.jobs._container import LABEL, ContainerOwnershipError, OwnedContainer

from ._support import reference, wait_job


def docker_service(root: Path, duration: float, exit_code: int = 0) -> DurableJobController:
    fixture = Path(__file__).with_name("docker_fixture.py").read_text()
    executable = root / "docker"
    executable.write_text(f"#!{sys.executable}\n{fixture}")
    executable.chmod(0o700)
    (root / "settings.json").write_text(json.dumps({"duration": duration, "exit_code": exit_code}))
    execution = DockerExecution(
        image_digest="fixture/example@sha256:" + "1" * 64,
        platform="linux/arm64",
        container_name="owned-job",
        ownership_token="unique-owner",
        program_version="fixture 1",
        docker_client_version="fixture 1",
        docker_server_version="fixture 1",
        command=("example",),
        mounts=(),
        working_directory="/run",
    )
    return DurableJobController(
        root,
        lambda request: JobCommand(
            argv=(str(executable),), working_directory=root, execution=execution
        ),
    )


@pytest.mark.parametrize("exit_code,expected", [(0, JobState.SUCCEEDED), (7, JobState.FAILED)])
def test_container_exit_is_durable(
    workspace: tuple[Path, JobRequest], exit_code: int, expected: JobState
) -> None:
    root, request = workspace
    service = docker_service(root, 0.2, exit_code)
    request = request.model_copy(update={"resource_policy": ResourcePolicy.ENFORCE})
    job = require(service.submit(request))
    completed = wait_job(service, job)
    assert completed.state == expected
    assert completed.exit_code == exit_code
    assert completed.container_id == "a" * 64
    reopened = DurableJobController(root, service.resolver)
    assert require(reopened.poll(reference(job))) == completed
    assert json.loads((root / "container.json").read_text())["State"]["Running"] is False


def test_cancel_stops_container_and_keeps_evidence(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = docker_service(root, 60)
    job = require(service.submit(request))
    wait_job(service, job, {JobState.RUNNING})
    require(service.request_cancel(reference(job)))
    completed = wait_job(service, job)
    assert completed.state == JobState.CANCELED
    assert completed.exit_code == 137
    assert completed.termination_confirmed
    assert completed.submission is not None
    container = OwnedContainer(completed.submission, completed.container_id)
    assert not container.inspect().state.running
    container.remove()
    assert not (root / "container.json").exists()


def test_foreign_label_blocks_stop(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = docker_service(root, 0.1)
    completed = wait_job(service, require(service.submit(request)))
    path = root / "container.json"
    record = json.loads(path.read_text())
    record["Config"]["Labels"][LABEL] = "another-owner"
    path.write_text(json.dumps(record))
    assert completed.submission is not None
    with pytest.raises(ContainerOwnershipError, match="differs"):
        OwnedContainer(completed.submission, completed.container_id).stop()
    assert path.exists()


def test_deadline_stops_daemon_work(workspace: tuple[Path, JobRequest]) -> None:
    root, request = workspace
    service = docker_service(root, 60)
    request = request.model_copy(
        update={"limits": request.limits.model_copy(update={"wall_time_seconds": 1})}
    )
    completed = wait_job(service, require(service.submit(request)))
    assert completed.state == JobState.FAILED
    assert completed.exit_code == 137
    assert completed.error is not None and "deadline" in completed.error.message
    assert not json.loads((root / "container.json").read_text())["State"]["Running"]


def test_uncertain_container_id_write_never_starts_work(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    from resinsight_mcp.contracts.errors import (
        Error,
        ErrorCode,
        Failure,
        MutationEffect,
        OperationResult,
    )
    from resinsight_mcp.contracts.jobs import Job
    from resinsight_mcp.jobs._common import job_directory

    from .test_faults import controlled_run

    root, request = workspace
    service = docker_service(root, 60)

    def hold_launch(ref: object, descriptor: int, directory: Path) -> None:
        (directory / "supervisor.log").write_text("Controlled Docker supervisor.\n")

    monkeypatch.setattr(service, "_start_supervisor", hold_launch)
    job = require(service.submit(request))
    save = service.store.save_job

    def uncertain_id(updated: Job, *, expected: Job | None = None) -> OperationResult[Job]:
        result = save(updated, expected=expected)
        if (
            updated.container_id is not None
            and expected is not None
            and expected.container_id is None
        ):
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED,
                        message="The container ID acknowledgement was lost.",
                        effect=MutationEffect.UNKNOWN,
                    )
                )
            )
        return result

    monkeypatch.setattr(service.store, "save_job", uncertain_id)
    assert controlled_run(service, job, job_directory(root, reference(job)), monkeypatch) == 1
    current = require(service.poll(reference(job)))
    assert current.state == JobState.UNKNOWN and current.container_id is not None
    record = json.loads((root / "container.json").read_text())
    assert record["State"]["Status"] == "created" and not record["State"]["Running"]
    assert "until" not in record


def test_recovery_stops_container_after_supervisor_loss(workspace: tuple[Path, JobRequest]) -> None:
    import psutil

    root, request = workspace
    service = docker_service(root, 60)
    job = require(service.submit(request))
    running = wait_job(service, job, {JobState.RUNNING})
    assert running.supervisor is not None
    supervisor = psutil.Process(running.supervisor.pid)
    assert str(supervisor.create_time()) == running.supervisor.start_marker
    supervisor.kill()
    supervisor.wait(timeout=5)
    reopened = DurableJobController(root, service.resolver)
    recovered = require(reopened.reconcile(job.model.session_id)).jobs[0]
    assert recovered.state == JobState.UNKNOWN
    assert recovered.container_id == running.container_id
    assert recovered.submission == running.submission
    assert not json.loads((root / "container.json").read_text())["State"]["Running"]


def test_docker_failure_stops_local_log_reader(workspace: tuple[Path, JobRequest]) -> None:
    import psutil

    root, request = workspace
    service = docker_service(root, 60)
    job = require(service.submit(request))
    running = wait_job(service, job, {JobState.RUNNING})
    assert running.process is not None and running.submission is not None
    (root / "fail-inspect").touch()
    require(service.request_cancel(reference(job)))
    try:
        unknown = wait_job(service, job, {JobState.UNKNOWN})
        assert not unknown.termination_confirmed
        assert not psutil.pid_exists(running.process.pid)
        assert json.loads((root / "container.json").read_text())["State"]["Running"]
    finally:
        (root / "fail-inspect").unlink()
        OwnedContainer(running.submission, running.container_id).stop()


def test_recovery_distinguishes_absence_from_unavailable_daemon(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    from resinsight_mcp.contracts.errors import Failure

    root, request = workspace
    service = docker_service(root, 60)

    def hold_launch(ref: object, descriptor: int, directory: Path) -> None:
        (directory / "supervisor.log").write_text("Interrupted before container creation.\n")

    monkeypatch.setattr(service, "_start_supervisor", hold_launch)
    job = require(service.submit(request))
    (root / "fail-inspect").touch()
    assert isinstance(service.reconcile(job.model.session_id).outcome, Failure)
    assert require(service.poll(reference(job))).state == JobState.QUEUED
    (root / "fail-inspect").unlink()
    recovered = require(service.reconcile(job.model.session_id)).jobs[0]
    assert recovered.state == JobState.UNKNOWN
    assert recovered.container_id is None
    assert not (root / "container.json").exists()


def test_recovery_rejects_foreign_same_name_container(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    from resinsight_mcp.contracts.errors import Failure

    root, request = workspace
    service = docker_service(root, 60)

    def hold_launch(ref: object, descriptor: int, directory: Path) -> None:
        (directory / "supervisor.log").write_text("Interrupted before container creation.\n")

    monkeypatch.setattr(service, "_start_supervisor", hold_launch)
    job = require(service.submit(request))
    assert job.submission is not None
    OwnedContainer(job.submission).create(5)
    path = root / "container.json"
    record = json.loads(path.read_text())
    record["Config"]["Labels"][LABEL] = "foreign-owner"
    path.write_text(json.dumps(record))
    outcome = service.reconcile(job.model.session_id).outcome
    assert isinstance(outcome, Failure) and "differs" in outcome.error.message
    assert require(service.poll(reference(job))).state == JobState.QUEUED
    assert json.loads(path.read_text()) == record


def test_slow_start_inspection_cannot_launch_after_deadline(
    workspace: tuple[Path, JobRequest], monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from resinsight_mcp.jobs._common import job_directory
    from resinsight_mcp.jobs._container import ContainerSnapshot

    from .test_faults import controlled_run

    root, request = workspace
    request = request.model_copy(
        update={"limits": request.limits.model_copy(update={"wall_time_seconds": 1})}
    )
    service = docker_service(root, 60)

    def hold_launch(ref: object, descriptor: int, directory: Path) -> None:
        (directory / "supervisor.log").write_text("Controlled startup deadline.\n")

    monkeypatch.setattr(service, "_start_supervisor", hold_launch)
    job = require(service.submit(request))
    inspect = OwnedContainer.inspect
    calls = 0

    def delayed_inspection(container: OwnedContainer) -> ContainerSnapshot:
        nonlocal calls
        calls += 1
        if calls == 2:
            time.sleep(1.1)
        return inspect(container)

    monkeypatch.setattr(OwnedContainer, "inspect", delayed_inspection)
    assert controlled_run(service, job, job_directory(root, reference(job)), monkeypatch) == 1
    current = require(service.poll(reference(job)))
    assert current.state == JobState.UNKNOWN
    assert "wall deadline" in current.events[-1].message
    record = json.loads((root / "container.json").read_text())
    assert record["State"]["Status"] == "created" and "until" not in record
