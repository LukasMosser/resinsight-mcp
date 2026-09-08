"""Unsafe or interrupted files never appear as complete revision inputs."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import ContractError, ErrorCode, Failure
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId, SessionId
from resinsight_mcp.contracts.jobs import Job, JobState
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision, Session
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value, write_json


class FailedInput(io.BytesIO):
    """Fail after a producer supplies part of a file."""

    def __init__(self) -> None:
        super().__init__(json.dumps({"partial": True}).encode())
        self.read_count = 0

    def read(self, size: int | None = -1, /) -> bytes:
        self.read_count += 1
        if self.read_count > 1:
            raise OSError("Producer stopped before the complete input arrived.")
        return super().read(size)


@pytest.mark.parametrize(
    "name",
    [
        "../outside.json",
        "/outside.json",
        "include/../outside.json",
        "include//file",
        "./file",
        "C:input",
        "include\\file",
        "line\nfile",
    ],
)
def test_artifact_names_reject_traversal_and_nonportable_paths(session: Session, name: str) -> None:
    with pytest.raises(ValidationError):
        Artifact(
            ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
            relative_path=name,
            kind=ArtifactKind.INPUT,
        )


def test_incomplete_producer_is_not_published(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision
) -> None:
    artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path="incomplete.DATA",
        kind=ArtifactKind.INPUT,
    )
    outcome = store.write_artifact(artifact, FailedInput())
    assert isinstance(outcome.outcome, Failure)
    assert outcome.outcome.error.code == ErrorCode.STORAGE_FAILED
    assert isinstance(store.get_artifact(artifact.ref).outcome, Failure)
    assert artifact.ref not in {
        item.ref for item in value(store.list_artifacts(session.session_id))
    }
    candidate = ModelRevision.model_validate(
        {
            **revision.model_dump(),
            "model": ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
            "inputs": ModelInputs(
                artifacts=(artifact.ref.artifact_id,), entrypoint=artifact.ref.artifact_id
            ),
        }
    )
    assert isinstance(store.save_revision(candidate).outcome, Failure)
    assert isinstance(store.get_revision(candidate.model).outcome, Failure)
    assert value(store.get_revision(revision.model)) == revision
    with pytest.raises(ContractError):
        with store.open_artifact(artifact.ref):
            pytest.fail("An incomplete artifact became readable.")


def test_artifact_rewrite_is_rejected_without_changing_original_content(
    store: SqliteWorkspaceStore, session: Session
) -> None:
    artifact = write_json(store, session, "input.DATA", {"rate": 100})
    outcome = store.write_artifact(artifact, io.BytesIO(json.dumps({"rate": 200}).encode()))
    assert isinstance(outcome.outcome, Failure)
    assert outcome.outcome.error.code == ErrorCode.CONFLICT
    with store.open_artifact(artifact.ref) as stream:
        assert json.load(stream)["rate"] == 100
        assert not stream.writable()


def test_interrupted_process_leaves_no_manifest_and_stale_recovery_does_not_clean(
    store: SqliteWorkspaceStore, session: Session, queued_job: Job, tmp_path: Path
) -> None:
    artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path="interrupted.DATA",
        kind=ArtifactKind.INPUT,
    )
    payload = tmp_path / "interrupt.json"
    payload.write_text(artifact.model_dump_json())
    child = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("worker.py")),
            "interrupt",
            str(tmp_path / "workspace"),
            str(payload),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 23, child.stderr
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert isinstance(reopened.get_artifact(artifact.ref).outcome, Failure)
    running = value(store.save_job(queued_job.transition(JobState.RUNNING), expected=queued_job))
    stale = reopened.reconcile(session.session_id, expected_jobs=(queued_job,))
    assert isinstance(stale.outcome, Failure)
    assert stale.outcome.error.code == ErrorCode.CONFLICT
    recovered = value(reopened.reconcile(session.session_id, expected_jobs=(running,)))
    assert artifact.ref.artifact_id in recovered.removed_artifacts
    assert isinstance(reopened.get_artifact(artifact.ref).outcome, Failure)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_replaced_input_links_are_rejected_without_reading_outside_data(
    store: SqliteWorkspaceStore,
    session: Session,
    revision: ModelRevision,
    tmp_path: Path,
    link_kind: str,
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"secret": "outside workspace"}))
    stored = (
        tmp_path
        / "workspace"
        / "artifacts"
        / str(session.session_id)
        / f"{revision.inputs.entrypoint}.data"
    )
    stored.unlink()
    if link_kind == "symlink":
        stored.symlink_to(outside)
    else:
        os.link(outside, stored)
    ref = ArtifactRef(session_id=session.session_id, artifact_id=revision.inputs.entrypoint)
    with pytest.raises(ContractError):
        with store.open_artifact(ref):
            pytest.fail("An unsafe artifact became readable.")
    assert isinstance(store.get_revision(revision.model).outcome, Failure)
    assert json.loads(outside.read_text())["secret"] == "outside workspace"


def test_missing_input_is_reported_without_claiming_complete_revision(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision, tmp_path: Path
) -> None:
    stored = (
        tmp_path
        / "workspace"
        / "artifacts"
        / str(session.session_id)
        / f"{revision.inputs.entrypoint}.data"
    )
    stored.unlink()
    assert isinstance(store.get_revision(revision.model).outcome, Failure)
    recovery = value(store.reconcile(session.session_id))
    assert {problem.artifact.artifact_id for problem in recovery.unavailable_artifacts} == {
        revision.inputs.entrypoint
    }


def test_store_rejects_symlink_root_without_changing_target(
    store: SqliteWorkspaceStore, tmp_path: Path
) -> None:
    linked = tmp_path / "linked-workspace"
    linked.symlink_to(tmp_path / "workspace", target_is_directory=True)
    with pytest.raises(ContractError):
        SqliteWorkspaceStore.open(linked)
    assert value(store.list_sessions()) == ()


def test_artifact_parent_symlink_is_rejected(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision, tmp_path: Path
) -> None:
    directory = tmp_path / "workspace" / "artifacts" / str(session.session_id)
    preserved = tmp_path / "preserved-artifacts"
    directory.rename(preserved)
    directory.symlink_to(preserved, target_is_directory=True)
    reference = ArtifactRef(session_id=session.session_id, artifact_id=revision.inputs.entrypoint)
    with pytest.raises(ContractError):
        with store.open_artifact(reference):
            pytest.fail("An artifact directory symlink became readable.")
    assert isinstance(store.get_revision(revision.model).outcome, Failure)
    assert (
        json.loads((preserved / f"{revision.inputs.entrypoint}.data").read_text())[
            "perforation_end"
        ]
        == 8374.0
    )


def test_recovery_removes_only_the_requested_sessions_pending_files(
    store: SqliteWorkspaceStore, session: Session, tmp_path: Path
) -> None:
    second = value(store.create_session(Session(session_id=SessionId.new(), name="Other study")))
    pending_ids = (ArtifactId.new(), ArtifactId.new())
    for owner, artifact_id in zip((session, second), pending_ids, strict=True):
        write_json(store, owner, "input.DATA", {"owner": owner.name})
        pending = (
            tmp_path / "workspace" / "artifacts" / str(owner.session_id) / f"{artifact_id}.pending"
        )
        pending.write_text(json.dumps({"incomplete": owner.name}))
    first_report = value(store.reconcile(session.session_id))
    assert first_report.removed_artifacts == (pending_ids[0],)
    second_report = value(store.reconcile(second.session_id))
    assert second_report.removed_artifacts == (pending_ids[1],)
