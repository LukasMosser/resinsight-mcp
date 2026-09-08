"""Competing writers cannot erase cancellation, lineage, or terminal outcomes."""

from pathlib import Path

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import ErrorCode, Failure, MutationEffect
from resinsight_mcp.contracts.identifiers import RevisionId, SessionId
from resinsight_mcp.contracts.jobs import Job, JobRef, JobState, Result
from resinsight_mcp.contracts.models import ModelRevision, Session
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value, workers


def test_independent_process_writers_preserve_both_sessions(
    store: SqliteWorkspaceStore, tmp_path: Path
) -> None:
    sessions = [Session(session_id=SessionId.new(), name="Concurrent study") for _ in range(2)]
    outcomes = workers(
        "create-session",
        tmp_path / "workspace",
        [item.model_dump(mode="json") for item in sessions],
        tmp_path,
    )
    assert [item["outcome"]["status"] for item in outcomes] == ["success", "success"]
    assert {item.session_id for item in value(store.list_sessions())} == {
        item.session_id for item in sessions
    }


def test_competing_job_updates_accept_one_and_report_the_stale_snapshot(
    store: SqliteWorkspaceStore, queued_job: Job, tmp_path: Path
) -> None:
    running = value(store.save_job(queued_job.transition(JobState.RUNNING), expected=queued_job))
    candidates = [running.request_cancel(), running.transition(JobState.SUCCEEDED, exit_code=0)]
    outcomes = workers(
        "update-job",
        tmp_path / "workspace",
        [
            {"expected": running.model_dump(mode="json"), "job": candidate.model_dump(mode="json")}
            for candidate in candidates
        ],
        tmp_path,
    )
    assert sorted(item["outcome"]["status"] for item in outcomes) == ["failure", "success"]
    rejected = next(item["outcome"] for item in outcomes if item["outcome"]["status"] == "failure")
    assert rejected["error"]["code"] == ErrorCode.CONFLICT
    accepted = next(
        item["outcome"]["value"] for item in outcomes if item["outcome"]["status"] == "success"
    )
    persisted = value(
        store.get_job(JobRef(session_id=running.model.session_id, job_id=running.job_id))
    )
    assert persisted.model_dump(mode="json") == accepted


def test_job_changes_need_expected_snapshot_and_cannot_clear_cancellation(
    store: SqliteWorkspaceStore, queued_job: Job
) -> None:
    running = queued_job.transition(JobState.RUNNING)
    missing_expected = store.save_job(running)
    assert isinstance(missing_expected.outcome, Failure)
    assert missing_expected.outcome.error.code == ErrorCode.CONFLICT
    running = value(store.save_job(running, expected=queued_job))
    canceled_intent = value(store.save_job(running.request_cancel(), expected=running))
    cleared = Job.model_validate({**canceled_intent.model_dump(), "cancel_requested": False})
    assert isinstance(store.save_job(cleared, expected=canceled_intent).outcome, Failure)
    assert value(
        store.get_job(JobRef(session_id=running.model.session_id, job_id=running.job_id))
    ).cancel_requested
    success = value(
        store.save_job(
            canceled_intent.transition(JobState.SUCCEEDED, exit_code=0), expected=canceled_intent
        )
    )
    assert value(store.save_job(success)) == success
    assert value(store.reconcile(success.model.session_id, expected_jobs=(success,))).jobs == (
        success,
    )
    assert isinstance(store.save_job(running, expected=success).outcome, Failure)


def test_open_does_not_reconcile_jobs_and_recovery_uses_explicit_snapshots(
    store: SqliteWorkspaceStore, queued_job: Job, tmp_path: Path
) -> None:
    requested = value(store.save_job(queued_job.request_cancel(), expected=queued_job))
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    reference = JobRef(session_id=requested.model.session_id, job_id=requested.job_id)
    assert value(reopened.get_job(reference)).state == JobState.QUEUED
    value(reopened.reconcile(requested.model.session_id))
    assert value(reopened.get_job(reference)).state == JobState.QUEUED
    report = value(reopened.reconcile(requested.model.session_id, expected_jobs=(requested,)))
    recovered = value(reopened.get_job(reference))
    assert recovered.state == JobState.UNKNOWN and recovered.cancel_requested
    assert not recovered.termination_confirmed and recovered.exit_code is None
    assert report.jobs == (recovered,)
    assert value(
        reopened.reconcile(requested.model.session_id, expected_jobs=(recovered,))
    ).jobs == (recovered,)


def test_recovery_rejects_all_stale_snapshots_before_changing_any_job(
    store: SqliteWorkspaceStore, queued_job: Job
) -> None:
    from resinsight_mcp.contracts.identifiers import JobId

    second = Job.model_validate({**queued_job.model_dump(), "job_id": JobId.new()})
    value(store.save_job(second))
    changed = value(store.save_job(queued_job.transition(JobState.RUNNING), expected=queued_job))
    outcome = store.reconcile(queued_job.model.session_id, expected_jobs=(second, queued_job))
    assert isinstance(outcome.outcome, Failure)
    assert outcome.outcome.error.code == ErrorCode.CONFLICT
    jobs = {item.job_id: item for item in value(store.list_jobs(queued_job.model.session_id))}
    assert jobs[second.job_id].state == JobState.QUEUED
    assert jobs[changed.job_id].state == JobState.RUNNING


def test_result_requires_stored_success_and_exact_revision(
    store: SqliteWorkspaceStore, queued_job: Job, result: Result, revision: ModelRevision
) -> None:
    assert isinstance(store.save_result(result).outcome, Failure)
    running = value(store.save_job(queued_job.transition(JobState.RUNNING), expected=queued_job))
    success = value(
        store.save_job(running.transition(JobState.SUCCEEDED, exit_code=0), expected=running)
    )
    wrong = Result.model_validate(
        {
            **result.model_dump(),
            "model": ModelRef(session_id=revision.model.session_id, revision_id=RevisionId.new()),
        }
    )
    assert isinstance(store.save_result(wrong).outcome, Failure)
    assert value(store.save_result(result)) == result
    assert (
        value(store.get_result(success.model.session_id, result.result_id)).model == revision.model
    )
    assert isinstance(store.get_result(SessionId.new(), result.result_id).outcome, Failure)


def test_writer_timeout_reports_busy_without_applying_the_write(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path
) -> None:
    import sqlite3

    contender = SqliteWorkspaceStore.open(tmp_path / "workspace", timeout=0.0)
    new_session = Session(session_id=SessionId.new(), name="Waiting study")
    with sqlite3.connect(tmp_path / "workspace" / "workspace.sqlite3") as lock:
        lock.execute("BEGIN IMMEDIATE")
        assert value(contender.get_session(session.session_id)) == session
        blocked = contender.create_session(new_session)
        assert isinstance(blocked.outcome, Failure)
        assert blocked.outcome.error.code == ErrorCode.BUSY
        assert blocked.outcome.error.effect == MutationEffect.NOT_APPLIED
    assert isinstance(store.get_session(new_session.session_id).outcome, Failure)
    assert value(contender.create_session(new_session)) == new_session
