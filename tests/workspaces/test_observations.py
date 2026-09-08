"""Observation storage checks supplied metadata without claiming image decoding."""

from datetime import UTC, datetime

from resinsight_mcp.contracts.engineering import CoordinateFrame, DepthDirection, ModelRef, Unit
from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import ConnectionId, ObservationId, RevisionId
from resinsight_mcp.contracts.jobs import Job, JobState, Result
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.observations import (
    Camera,
    ImageArtifact,
    Legend,
    Observation,
    Projection,
    Property,
    ViewContext,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value, write_json


def test_observation_metadata_requires_stored_result_and_image_manifest(
    store: SqliteWorkspaceStore, session: Session, queued_job: Job, result: Result
) -> None:
    application = ApplicationContext(
        session_id=session.session_id, connection_id=ConnectionId.new(), project_generation=1
    )
    view = ViewContext(
        model=result.model,
        result_id=result.result_id,
        grid_id=result.grid_id,
        case=ObjectRef(context=application, kind=ObjectKind.CASE, object_id="0"),
        view=ObjectRef(context=application, kind=ObjectKind.VIEW, object_id="1"),
        scene_version=1,
        property=Property(name="SGAS", unit=Unit.ONE),
        report_time=result.report_series.reports[-1],
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_UP,
            datum="SPE1 local origin",
        ),
        camera=Camera(
            position=(1.0, 1.0, 1.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 0.0, 1.0),
            projection=Projection.ORTHOGRAPHIC,
            parallel_scale=10000.0,
        ),
        vertical_exaggeration=20.0,
        legend=Legend(minimum=0.0, maximum=1.0),
        filters=(),
    )
    image = write_json(
        store,
        session,
        "frame.png",
        {"opaque_artifact": "P03 does not decode images"},
        ArtifactKind.IMAGE,
    )
    observation = Observation(
        observation_id=ObservationId.new(),
        context=view,
        image=ImageArtifact(artifact=image.ref, width=1280, height=900),
        captured_at=datetime(2026, 9, 8, tzinfo=UTC),
    )
    assert isinstance(store.save_observation(observation).outcome, Failure)
    running = value(store.save_job(queued_job.transition(JobState.RUNNING), expected=queued_job))
    value(store.save_job(running.transition(JobState.SUCCEEDED, exit_code=0), expected=running))
    value(store.save_result(result))
    assert value(store.save_observation(observation)) == observation
    assert (
        value(
            store.get_observation(session.session_id, observation.observation_id)
        ).context.report_time.index
        == 120
    )
    wrong_context = ViewContext.model_validate(
        {
            **view.model_dump(),
            "model": ModelRef(session_id=session.session_id, revision_id=RevisionId.new()),
        }
    )
    wrong = Observation.model_validate(
        {
            **observation.model_dump(),
            "observation_id": ObservationId.new(),
            "context": wrong_context,
        }
    )
    assert isinstance(store.save_observation(wrong).outcome, Failure)
    wrong_kind = write_json(store, session, "log.txt", {"log": "No frame"}, ArtifactKind.LOG)
    wrong_image = Observation.model_validate(
        {
            **observation.model_dump(),
            "observation_id": ObservationId.new(),
            "image": ImageArtifact(artifact=wrong_kind.ref, width=1280, height=900),
        }
    )
    assert isinstance(store.save_observation(wrong_image).outcome, Failure)
