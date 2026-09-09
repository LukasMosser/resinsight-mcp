"""A fresh image proves a particular scene; failed renders never erase edits."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    MeasuredDepthInterval,
    ModelRef,
    ReportTime,
    Unit,
)
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    EditId,
    GridId,
    ObservationId,
    ResultId,
    RevisionId,
    SessionId,
)
from resinsight_mcp.contracts.jobs import LoadedResult, Result
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import (
    Camera,
    EditedView,
    EditReceipt,
    ImageArtifact,
    Legend,
    Observation,
    PerforationEditRequest,
    Projection,
    Property,
    RenderRequest,
    ResultViewState,
    ViewContext,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef


@pytest.fixture
def view(context: ApplicationContext, result: Result) -> ViewContext:
    return ViewContext(
        model=result.model,
        result_id=result.result_id,
        grid_id=result.grid_id,
        case=ObjectRef(context=context, kind=ObjectKind.CASE, object_id="0"),
        view=ObjectRef(context=context, kind=ObjectKind.VIEW, object_id="1"),
        scene_version=2,
        property=Property(name="SGAS", unit=Unit.ONE),
        report_time=result.report_series.reports[-1],
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_UP,
            datum="SPE1 local origin",
        ),
        camera=Camera(
            position=(20000.0, 20000.0, 0.0),
            target=(5000.0, 5000.0, -8375.0),
            up=(0.0, 0.0, 1.0),
            projection=Projection.ORTHOGRAPHIC,
            parallel_scale=10000.0,
        ),
        vertical_exaggeration=20.0,
        legend=Legend(minimum=0.0, maximum=1.0),
        filters=(),
    )


@pytest.fixture
def observation(view: ViewContext) -> Observation:
    return Observation(
        observation_id=ObservationId.new(),
        context=view,
        image=ImageArtifact(
            artifact=ArtifactRef(session_id=view.model.session_id, artifact_id=ArtifactId.new()),
            width=1280,
            height=900,
        ),
        captured_at=datetime(2026, 9, 8, 12, 12, tzinfo=UTC),
    )


@pytest.fixture
def receipt(view: ViewContext) -> EditReceipt:
    request = PerforationEditRequest(
        model=view.model,
        well=ObjectRef(context=view.view.context, kind=ObjectKind.WELL, object_id="P01IMPORT"),
        interval=MeasuredDepthInterval(start=8326.0, end=8424.0, unit=Unit.FOOT),
        expected_scene_version=1,
    )
    return EditReceipt(edit_id=EditId.new(), request=request, scene_version=2)


def test_observation_preserves_simulator_date_separately_from_capture_instant(
    observation: Observation, result: Result
) -> None:
    restored = Observation.model_validate_json(observation.model_dump_json())
    restored.context.require_result(result)
    assert restored.captured_at == datetime(2026, 9, 8, 12, 12, tzinfo=UTC)
    assert restored.context.report_time.calendar_date == date(2024, 12, 29)
    assert restored.context.report_time.index == 120
    assert restored.context.report_time.elapsed_days == 3650.0
    assert restored.context.property.name == "SGAS"
    assert (restored.image.width, restored.image.height) == (1280, 900)


def test_result_view_state_retains_trusted_identity_and_observed_camera(
    view: ViewContext, result: Result
) -> None:
    state = ResultViewState(
        loaded=LoadedResult(case=view.case, result=result),
        view=view.view,
        camera=view.camera,
        vertical_exaggeration=view.vertical_exaggeration,
        scene_version=0,
    )
    restored = ResultViewState.model_validate_json(state.model_dump_json())
    assert restored.loaded.result == result
    assert restored.camera == view.camera
    assert restored.view.context == restored.loaded.case.context
    for wrong in (
        view.case,
        view.view.model_copy(
            update={"context": view.view.context.model_copy(update={"project_generation": 99})}
        ),
    ):
        with pytest.raises(ValidationError, match="current application context"):
            ResultViewState.model_validate({**state.model_dump(), "view": wrong})


@pytest.mark.parametrize(
    "captured_at",
    [
        datetime(2026, 9, 8, 12, 12),
        datetime(2026, 9, 8, 14, 12, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_capture_timestamp_requires_explicit_utc(
    observation: Observation, captured_at: datetime
) -> None:
    with pytest.raises(ValidationError):
        Observation.model_validate({**observation.model_dump(), "captured_at": captured_at})


@pytest.mark.parametrize("mismatch", ["result", "revision", "grid", "report"])
def test_render_requires_exact_stored_result_context(
    view: ViewContext, result: Result, mismatch: str
) -> None:
    changes = {
        "result": {"result_id": ResultId.new()},
        "revision": {
            "model": ModelRef(session_id=view.model.session_id, revision_id=RevisionId.new())
        },
        "grid": {"grid_id": GridId.new()},
        "report": {
            "report_time": ReportTime(
                index=120, elapsed_days=3651.0, calendar_date=date(2024, 12, 30)
            )
        },
    }
    wrong_view = ViewContext.model_validate({**view.model_dump(), **changes[mismatch]})
    with pytest.raises(ValidationError):
        RenderRequest(result=result, context=wrong_view, width=1280, height=900)
    with pytest.raises(ValueError):
        wrong_view.require_result(result)
    assert RenderRequest(result=result, context=view, width=1280, height=900).context == view


def test_observation_cannot_use_another_sessions_image(observation: Observation) -> None:
    image = ImageArtifact(
        artifact=ArtifactRef(session_id=SessionId.new(), artifact_id=ArtifactId.new()),
        width=1280,
        height=900,
    )
    with pytest.raises(ValidationError):
        Observation.model_validate({**observation.model_dump(), "image": image})


def test_applied_edit_survives_failed_render_without_old_observation(receipt: EditReceipt) -> None:
    failure = Failure(
        error=Error(
            code=ErrorCode.RENDER_FAILED, message="Image export failed after the interval changed."
        )
    )
    outcome = EditedView(edit=receipt, observation=OperationResult[Observation](outcome=failure))
    restored = EditedView.model_validate_json(outcome.model_dump_json())
    assert isinstance(restored.edit, EditReceipt)
    assert restored.edit.edit_id == receipt.edit_id
    assert restored.edit.effect == "applied"
    assert restored.edit.request.interval.end == 8424.0
    assert restored.edit.scene_version == 2
    assert isinstance(restored.observation.outcome, Failure)
    assert restored.observation.outcome.error.code == ErrorCode.RENDER_FAILED
    assert "value" not in restored.observation.outcome.model_dump()


def test_edit_observation_must_show_resulting_scene(
    receipt: EditReceipt, observation: Observation
) -> None:
    successful = EditedView(
        edit=receipt, observation=OperationResult[Observation](outcome=Success(value=observation))
    )
    assert isinstance(successful.observation.outcome, Success)
    assert successful.observation.outcome.value.context.scene_version == receipt.scene_version
    stale_context = ViewContext.model_validate(
        {**observation.context.model_dump(), "scene_version": 1}
    )
    stale_image = Observation.model_validate({**observation.model_dump(), "context": stale_context})
    with pytest.raises(ValidationError):
        EditedView(
            edit=receipt,
            observation=OperationResult[Observation](outcome=Success(value=stale_image)),
        )
    with pytest.raises(ValidationError):
        EditReceipt(edit_id=EditId.new(), request=receipt.request, scene_version=1)


def test_view_rejects_cross_session_case_handles(view: ViewContext) -> None:
    other = ApplicationContext(
        session_id=SessionId.new(),
        connection_id=view.case.context.connection_id,
        project_generation=1,
    )
    wrong_case = ObjectRef(context=other, kind=ObjectKind.CASE, object_id="0")
    with pytest.raises(ValidationError):
        ViewContext.model_validate({**view.model_dump(), "case": wrong_case})
