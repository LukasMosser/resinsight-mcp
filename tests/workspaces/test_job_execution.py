"""Stored execution history cannot be replaced by a competing controller."""

from datetime import UTC, datetime

import pytest

from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.identifiers import ArtifactId, JobId
from resinsight_mcp.contracts.jobs import (
    Job,
    JobEvent,
    JobState,
    JobSubmission,
    ResourceLimits,
    ResourcePolicy,
)
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.sessions import ProcessIdentity
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value, write_json


def changed(job: Job, **updates: object) -> Job:
    return Job.model_validate({**job.model_dump(), **updates})


@pytest.fixture
def recorded(store: SqliteWorkspaceStore, queued_job: Job) -> Job:
    job = changed(
        queued_job,
        job_id=JobId.new(),
        submission=JobSubmission(
            limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=60),
            resource_policy=ResourcePolicy.WALL_TIME_ONLY,
            argv=("/usr/bin/true",),
            working_directory="/tmp",
            submitted_at=datetime.now(UTC),
        ),
        events=(JobEvent(at=datetime.now(UTC), state=JobState.QUEUED, message="Queued."),),
    )
    return value(store.save_job(job))


def test_recovery_preserves_execution_metadata_and_appends_history(
    store: SqliteWorkspaceStore, recorded: Job, session: Session
) -> None:
    log = write_json(store, session, "stdout.log", {"message": "started"}, ArtifactKind.LOG)
    process = ProcessIdentity(pid=123, start_marker="child")
    running = changed(
        recorded.transition(JobState.RUNNING),
        process=process,
        process_group_id=process.pid,
        supervisor=ProcessIdentity(pid=124, start_marker="supervisor"),
        logs=(log.ref,),
        events=(
            *recorded.events,
            JobEvent(at=datetime.now(UTC), state=JobState.RUNNING, message="Started."),
        ),
    )
    value(store.save_job(running, expected=recorded))
    recovered = value(store.reconcile(session.session_id, expected_jobs=(running,))).jobs[0]
    assert recovered.state == JobState.UNKNOWN
    assert recovered.submission == running.submission
    assert recovered.process == process and recovered.supervisor == running.supervisor
    assert recovered.logs == (log.ref,)
    assert recovered.events[:-1] == running.events
    assert recovered.events[-1].state == JobState.UNKNOWN
    stale = store.save_job(running.request_cancel(), expected=running)
    assert isinstance(stale.outcome, Failure)
    assert stale.outcome.error.code == ErrorCode.CONFLICT


def test_store_rejects_submission_and_history_replacement(
    store: SqliteWorkspaceStore, recorded: Job
) -> None:
    for update in ({"submission": None}, {"events": ()}):
        assert isinstance(
            store.save_job(changed(recorded, **update), expected=recorded).outcome, Failure
        )
    assert isinstance(
        store.save_job(recorded.transition(JobState.RUNNING), expected=recorded).outcome, Failure
    )


def test_logs_require_existing_log_artifacts_and_cannot_change(
    store: SqliteWorkspaceStore, recorded: Job, session: Session
) -> None:
    missing = ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new())
    wrong = write_json(store, session, "input.json", {})
    log = write_json(store, session, "stdout.log", {}, ArtifactKind.LOG)
    for ref in (missing, wrong.ref):
        assert isinstance(
            store.save_job(changed(recorded, logs=(ref,)), expected=recorded).outcome, Failure
        )
    attached = value(store.save_job(changed(recorded, logs=(log.ref,)), expected=recorded))
    assert isinstance(
        store.save_job(changed(attached, logs=()), expected=attached).outcome, Failure
    )
    terminal = changed(
        attached.transition(JobState.CANCELED, termination_confirmed=True),
        events=(
            *attached.events,
            JobEvent(at=datetime.now(UTC), state=JobState.CANCELED, message="Stopped."),
        ),
    )
    value(store.save_job(terminal, expected=attached))
    extra = JobEvent(at=datetime.now(UTC), state=JobState.CANCELED, message="Changed.")
    assert isinstance(
        store.save_job(
            changed(terminal, events=(*terminal.events, extra)), expected=terminal
        ).outcome,
        Failure,
    )


def test_new_job_cannot_claim_execution_metadata(
    store: SqliteWorkspaceStore, recorded: Job
) -> None:
    new = changed(
        recorded, job_id=JobId.new(), supervisor=ProcessIdentity(pid=124, start_marker="start")
    )
    assert isinstance(store.save_job(new).outcome, Failure)


def test_recorded_process_identities_cannot_be_replaced(
    store: SqliteWorkspaceStore, recorded: Job
) -> None:
    process = ProcessIdentity(pid=123, start_marker="first")
    assigned = value(
        store.save_job(
            changed(recorded, process=process, process_group_id=123, supervisor=process),
            expected=recorded,
        )
    )
    replacement = ProcessIdentity(pid=123, start_marker="reused")
    for update in (
        {"process": replacement},
        {"process": None, "process_group_id": None},
        {"supervisor": replacement},
    ):
        outcome = store.save_job(changed(assigned, **update), expected=assigned)
        assert isinstance(outcome.outcome, Failure)
