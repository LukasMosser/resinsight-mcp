"""Create real inputs and records through the public workspace interface."""

from pathlib import Path

import pytest
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.jobs import Job, JobState
from resinsight_mcp.contracts.models import ModelInputs, ModelRevision, Session

from ._support import value, write_json


@pytest.fixture
def store(tmp_path: Path) -> SqliteWorkspaceStore:
    return SqliteWorkspaceStore.create(tmp_path / "workspace")


@pytest.fixture
def session(store: SqliteWorkspaceStore, model: ModelRef) -> Session:
    return value(store.create_session(Session(session_id=model.session_id, name="SPE1 study")))


@pytest.fixture
def revision(store: SqliteWorkspaceStore, session: Session, model: ModelRef) -> ModelRevision:
    artifact = write_json(
        store, session, "SPE1.DATA", {"unit_system": "FIELD", "perforation_end": 8374.0}
    )
    revision = ModelRevision(
        model=model,
        inputs=ModelInputs(
            artifacts=(artifact.ref.artifact_id,), entrypoint=artifact.ref.artifact_id
        ),
        unit_system=UnitSystem.FIELD,
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum="SPE1 local origin",
        ),
    )
    return value(store.save_revision(revision))


@pytest.fixture
def queued_job(store: SqliteWorkspaceStore, revision: ModelRevision, running_job: Job) -> Job:
    queued = Job.model_validate({**running_job.model_dump(), "state": JobState.QUEUED})
    return value(store.save_job(queued))
