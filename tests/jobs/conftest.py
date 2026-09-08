"""Real workspaces and fixed input revisions for process acceptance."""

import io
from pathlib import Path

import pytest

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId, SessionId
from resinsight_mcp.contracts.jobs import JobRequest, ResourceLimits, ResourcePolicy
from resinsight_mcp.contracts.models import (
    ArtifactRef,
    Backend,
    ModelInputs,
    ModelRevision,
    PreparedModel,
    Session,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.jobs._common import require
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, JobRequest]:
    root = tmp_path / "workspace"
    store = SqliteWorkspaceStore.create(root)
    session = Session(session_id=SessionId.new(), name="Job acceptance")
    require(store.create_session(session))
    artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        kind=ArtifactKind.INPUT,
        relative_path="input.txt",
    )
    require(store.write_artifact(artifact, io.BytesIO(b"Fixed job input revision.\n")))
    revision = ModelRevision(
        model=ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
        inputs=ModelInputs(
            artifacts=(artifact.ref.artifact_id,), entrypoint=artifact.ref.artifact_id
        ),
        unit_system=UnitSystem.METRIC,
        coordinates=CoordinateFrame(
            length_unit=Unit.METER,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum="Local origin",
        ),
    )
    require(store.save_revision(revision))
    request = JobRequest(
        prepared=PreparedModel(revision=revision, backend=Backend.OPM_FLOW),
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=10),
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
    )
    return root, request
