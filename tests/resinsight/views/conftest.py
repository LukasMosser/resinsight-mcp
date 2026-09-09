"""Build stored result context through public workspace operations."""

from io import BytesIO
from pathlib import Path

import pytest

from resinsight_mcp.contracts.engineering import (
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.jobs import Job, JobState, Result
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision, Session
from resinsight_mcp.contracts.observations import (
    Camera,
    CellRangeFilter,
    Legend,
    Projection,
    Property,
    ViewContext,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump(mode="json")
    return result.outcome.value


@pytest.fixture
def store(tmp_path: Path) -> SqliteWorkspaceStore:
    return SqliteWorkspaceStore.create(tmp_path / "workspace")


@pytest.fixture
def view_context(
    store: SqliteWorkspaceStore,
    result: Result,
    running_job: Job,
    context: ApplicationContext,
) -> ViewContext:
    value(store.create_session(Session(session_id=result.model.session_id, name="Capture study")))
    artifact = value(
        store.write_artifact(
            Artifact(
                ref=ArtifactRef(session_id=result.model.session_id, artifact_id=ArtifactId.new()),
                relative_path="model.DATA",
                kind=ArtifactKind.INPUT,
            ),
            BytesIO(b"RUNSPEC\nFIELD\n"),
        )
    )
    coordinates = CoordinateFrame(
        length_unit=Unit.FOOT,
        depth_direction=DepthDirection.POSITIVE_DOWN,
        datum="Local origin",
    )
    value(
        store.save_revision(
            ModelRevision(
                model=result.model,
                inputs=ModelInputs(
                    artifacts=(artifact.ref.artifact_id,), entrypoint=artifact.ref.artifact_id
                ),
                unit_system=UnitSystem.FIELD,
                coordinates=coordinates,
            )
        )
    )
    queued = value(store.save_job(running_job.model_copy(update={"state": JobState.QUEUED})))
    running = value(store.save_job(queued.transition(JobState.RUNNING), expected=queued))
    value(store.save_job(running.transition(JobState.SUCCEEDED, exit_code=0), expected=running))
    value(store.save_result(result))
    return ViewContext(
        model=result.model,
        result_id=result.result_id,
        grid_id=result.grid_id,
        case=ObjectRef(context=context, kind=ObjectKind.CASE, object_id="0"),
        view=ObjectRef(context=context, kind=ObjectKind.VIEW, object_id="1"),
        scene_version=7,
        property=Property(name="SGAS", unit=Unit.ONE),
        report_time=result.report_series.reports[-1],
        coordinates=coordinates,
        camera=Camera(
            position=(10.0, 20.0, 30.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 0.0, 1.0),
            projection=Projection.ORTHOGRAPHIC,
            parallel_scale=1000.0,
        ),
        vertical_exaggeration=20.0,
        legend=Legend(minimum=0.1, maximum=0.8),
        filters=(
            CellRangeFilter(
                grid_id=result.grid_id,
                minimum=CellIndex(i=0, j=0, k=0),
                maximum=CellIndex(i=2, j=3, k=4),
                include=True,
            ),
        ),
    )
