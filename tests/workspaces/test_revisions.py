"""Saved inputs and cloned scenarios remain independent after reopening."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.identifiers import ArtifactId, CheckpointId, RevisionId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision, Session
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind, ProjectCheckpoint
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value, write_json


def test_clone_and_checkpoint_preserve_parent_in_a_fresh_process(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision, tmp_path: Path
) -> None:
    project = write_json(
        store,
        session,
        "project.rsp",
        {"revision": str(revision.model.revision_id)},
        ArtifactKind.PROJECT,
    )
    checkpoint = ProjectCheckpoint(
        checkpoint_id=CheckpointId.new(),
        name="Before interval edit",
        model=revision.model,
        project=project.ref,
    )
    value(store.save_checkpoint(checkpoint))
    replacement = write_json(
        store, session, "SPE1.DATA", {"unit_system": "FIELD", "perforation_end": 8424.0}
    )
    clone = value(
        store.clone_revision(
            revision.model, RevisionId.new(), replacements=(replacement.ref.artifact_id,)
        )
    )
    assert clone.parent == revision.model
    assert clone.inputs.entrypoint == replacement.ref.artifact_id
    assert value(store.get_revision(revision.model)) == revision
    payload = tmp_path / "reopen.json"
    payload.write_text(
        json.dumps(
            {
                "revision": revision.model_dump(mode="json"),
                "checkpoint": checkpoint.model_dump(mode="json"),
                "clone": clone.model_dump(mode="json"),
            }
        )
    )
    child = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("worker.py")),
            "reopen",
            str(tmp_path / "workspace"),
            str(payload),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    reopened = json.loads(child.stdout)
    assert reopened["content"]["perforation_end"] == 8374.0
    assert reopened["clone"]["outcome"]["value"]["parent"] == revision.model.model_dump(mode="json")
    assert reopened["revision"]["outcome"]["value"]["model"] == revision.model.model_dump(
        mode="json"
    )
    assert reopened["checkpoint"]["outcome"]["value"]["model"] == revision.model.model_dump(
        mode="json"
    )
    reopened_store = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert value(reopened_store.get_revision(clone.model)).parent == revision.model
    with reopened_store.open_artifact(replacement.ref) as stream:
        assert json.load(stream)["perforation_end"] == 8424.0


def test_revision_retries_are_equal_but_changed_content_conflicts(
    store: SqliteWorkspaceStore, revision: ModelRevision
) -> None:
    assert value(store.save_revision(revision)) == revision
    changed = ModelRevision.model_validate(
        {
            **revision.model_dump(),
            "coordinates": {**revision.coordinates.model_dump(), "datum": "different origin"},
        }
    )
    outcome = store.save_revision(changed)
    assert isinstance(outcome.outcome, Failure)
    assert outcome.outcome.error.code == ErrorCode.CONFLICT
    assert value(store.get_revision(revision.model)) == revision


@pytest.mark.parametrize(
    ("first", "second"),
    [("A.DATA", "a.data"), ("café.DATA", "cafe\u0301.DATA"), ("A", "a/child.DATA")],
)
def test_revision_rejects_portable_name_collisions(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision, first: str, second: str
) -> None:
    artifacts = tuple(
        write_json(store, session, name, {"name": name}).ref.artifact_id for name in (first, second)
    )
    candidate = ModelRevision.model_validate(
        {
            **revision.model_dump(),
            "model": ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
            "inputs": ModelInputs(artifacts=artifacts, entrypoint=artifacts[0]),
        }
    )
    outcome = store.save_revision(candidate)
    assert isinstance(outcome.outcome, Failure)
    assert outcome.outcome.error.code == ErrorCode.INVALID_MODEL
    assert isinstance(store.get_revision(candidate.model).outcome, Failure)


def test_checkpoint_requires_a_saved_project_and_revision(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision
) -> None:
    wrong_kind = write_json(store, session, "not-project.json", {"value": 1})
    checkpoint = ProjectCheckpoint(
        checkpoint_id=CheckpointId.new(),
        name="Invalid checkpoint",
        model=revision.model,
        project=wrong_kind.ref,
    )
    outcome = store.save_checkpoint(checkpoint)
    assert isinstance(outcome.outcome, Failure)
    assert isinstance(
        store.get_checkpoint(session.session_id, checkpoint.checkpoint_id).outcome, Failure
    )
    project = write_json(
        store, session, "project.rsp", {"revision": "missing"}, ArtifactKind.PROJECT
    )
    missing = ProjectCheckpoint(
        checkpoint_id=CheckpointId.new(),
        name="Missing revision",
        model=ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
        project=project.ref,
    )
    assert isinstance(store.save_checkpoint(missing).outcome, Failure)


def test_sessions_and_roots_keep_records_and_files_separate(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision, tmp_path: Path
) -> None:
    second = value(store.create_session(Session(session_id=SessionId.new(), name=session.name)))
    artifact = write_json(store, second, "SPE1.DATA", {"perforation_end": 100.0})
    wrong_ref = ArtifactRef(session_id=second.session_id, artifact_id=revision.inputs.entrypoint)
    assert isinstance(store.get_artifact(wrong_ref).outcome, Failure)
    assert {item.ref for item in value(store.list_artifacts(second.session_id))} == {artifact.ref}
    isolated = SqliteWorkspaceStore.create(tmp_path / "other-workspace")
    assert value(isolated.list_sessions()) == ()
    value(isolated.create_session(session))
    other_artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=revision.inputs.entrypoint),
        relative_path="SPE1.DATA",
        kind=ArtifactKind.INPUT,
    )
    value(
        isolated.write_artifact(
            other_artifact, io.BytesIO(json.dumps({"perforation_end": 5.0}).encode())
        )
    )
    with (
        store.open_artifact(other_artifact.ref) as parent_stream,
        isolated.open_artifact(other_artifact.ref) as other_stream,
    ):
        assert json.load(parent_stream)["perforation_end"] == 8374.0
        assert json.load(other_stream)["perforation_end"] == 5.0
    assert isinstance(isolated.get_revision(revision.model).outcome, Failure)


def test_revision_requires_existing_input_artifacts(
    store: SqliteWorkspaceStore, session: Session, revision: ModelRevision
) -> None:
    absent = ArtifactId.new()
    for artifact in (
        absent,
        write_json(
            store, session, "output.json", {"value": 1}, ArtifactKind.OUTPUT
        ).ref.artifact_id,
    ):
        candidate = ModelRevision.model_validate(
            {
                **revision.model_dump(),
                "model": ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
                "inputs": ModelInputs(artifacts=(artifact,), entrypoint=artifact),
            }
        )
        assert isinstance(store.save_revision(candidate).outcome, Failure)
        assert isinstance(store.get_revision(candidate.model).outcome, Failure)
