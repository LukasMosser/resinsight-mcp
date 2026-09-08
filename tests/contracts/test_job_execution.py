"""Execution records retain explicit commands, identities, and event times."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.jobs import (
    Job,
    JobEvent,
    JobState,
    JobSubmission,
    ResourceLimits,
    ResourcePolicy,
)
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ProcessIdentity


def submission() -> JobSubmission:
    return JobSubmission(
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=60),
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        argv=("/usr/bin/true",),
        working_directory="/tmp",
        submitted_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"argv": ()},
        {"argv": ("true",)},
        {"argv": ("/usr/bin/true", "bad\0argument")},
        {"working_directory": "relative"},
        {"submitted_at": datetime(2026, 1, 1)},
        {"submitted_at": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_submission_rejects_ambiguous_command_and_time(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        JobSubmission.model_validate({**submission().model_dump(), **change})


def test_execution_metadata_round_trips(running_job: Job) -> None:
    identity = ProcessIdentity(pid=123, start_marker="start-123")
    event = JobEvent(at=datetime.now(UTC), state=JobState.RUNNING, message="Started.")
    job = Job.model_validate(
        {
            **running_job.model_dump(),
            "submission": submission(),
            "process": identity,
            "process_group_id": identity.pid,
            "events": (event,),
        }
    )
    assert Job.model_validate_json(job.model_dump_json()) == job
    assert job.transition(JobState.UNKNOWN).events == (event,)


def test_job_rejects_wrong_process_group_and_log_lineage(running_job: Job) -> None:
    identity = ProcessIdentity(pid=123, start_marker="start-123")
    foreign = ArtifactRef(session_id=SessionId.new(), artifact_id=ArtifactId.new())
    for change in (
        {"process": identity},
        {"process": identity, "process_group_id": 456},
        {"logs": (foreign,)},
    ):
        with pytest.raises(ValidationError):
            Job.model_validate({**running_job.model_dump(), **change})


def test_events_reject_blank_messages_and_backward_time(running_job: Job) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        JobEvent(at=now, state=JobState.RUNNING, message=" ")
    first = JobEvent(at=now, state=JobState.RUNNING, message="Started.")
    earlier = JobEvent(at=now - timedelta(seconds=1), state=JobState.RUNNING, message="Earlier.")
    with pytest.raises(ValidationError):
        Job.model_validate({**running_job.model_dump(), "events": (first, earlier)})
