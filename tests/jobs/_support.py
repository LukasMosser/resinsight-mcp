"""Wait for public job outcomes without changing process ownership."""

import sys
import time
from pathlib import Path

import pytest

from resinsight_mcp.contracts.jobs import Job, JobRef, JobState
from resinsight_mcp.jobs import DurableJobController, JobCommand
from resinsight_mcp.jobs._common import require

TERMINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED}


def reference(job: Job) -> JobRef:
    return JobRef(session_id=job.model.session_id, job_id=job.job_id)


def controller(root: Path, source: str) -> DurableJobController:
    return DurableJobController(
        root,
        lambda request: JobCommand(argv=(sys.executable, "-c", source), working_directory=root),
    )


def wait_job(service: DurableJobController, job: Job, states: set[JobState] = TERMINAL) -> Job:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = require(service.poll(reference(job)))
        if current.state in states:
            return current
        if current.state == JobState.UNKNOWN:
            pytest.fail(f"Unexpected uncertainty: {current.model_dump_json()}")
        time.sleep(0.02)
    pytest.fail(f"Job timed out: {current.model_dump_json()}")


def wait_file(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, "The command did not publish readiness."
        time.sleep(0.02)
