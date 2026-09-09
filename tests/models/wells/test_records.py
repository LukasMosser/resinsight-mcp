"""Keep FIELD well records explicit before any native or schedule mutation."""

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import CoordinateFrame, DepthDirection, ModelRef, Unit
from resinsight_mcp.contracts.identifiers import ArtifactId, ConnectionId, RevisionId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.wells import ProducerControl, WellStatus
from resinsight_mcp.models.wells.records import (
    ModeledWell,
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCase,
    ScheduledControl,
    ScheduledWell,
    TrajectoryPoint,
    TrajectorySample,
    WellScheduleRequest,
)


def definition() -> ModeledWellDefinition:
    return ModeledWellDefinition(
        name="PROD",
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT, depth_direction=DepthDirection.POSITIVE_DOWN, datum="Local"
        ),
        targets=(
            TrajectoryPoint(x_ft=0.0, y_ft=0.0, depth_ft=0.0),
            TrajectoryPoint(x_ft=0.0, y_ft=0.0, depth_ft=8500.0),
        ),
        perforations=(PerforationInterval(start_md_ft=8325.0, end_md_ft=8450.0, diameter_ft=0.5),),
    )


def test_observed_well_retains_positive_down_depth_and_measured_depth() -> None:
    session = SessionId.new()
    context = ApplicationContext(
        session_id=session, connection_id=ConnectionId.new(), project_generation=1
    )
    binding = PreparedCase(
        model=ModelRef(session_id=session, revision_id=RevisionId.new()),
        case=ObjectRef(context=context, kind=ObjectKind.CASE, object_id="case"),
    )
    well = ModeledWell(
        binding=binding,
        well=ObjectRef(context=context, kind=ObjectKind.WELL, object_id="well"),
        version=0,
        definition=definition(),
        trajectory=(
            TrajectorySample(x_ft=0.0, y_ft=0.0, depth_ft=0.0, measured_depth_ft=0.0),
            TrajectorySample(x_ft=0.0, y_ft=0.0, depth_ft=8500.0, measured_depth_ft=8500.0),
        ),
    )
    assert ModeledWell.model_validate_json(well.model_dump_json()) == well
    with pytest.raises(ValidationError, match="increase"):
        ModeledWell.model_validate(
            {**well.model_dump(), "trajectory": tuple(reversed(well.trajectory))}
        )
    with pytest.raises(ValidationError, match="fit"):
        ModeledWell.model_validate(
            {
                **well.model_dump(),
                "trajectory": (
                    well.trajectory[0],
                    TrajectorySample(x_ft=0.0, y_ft=0.0, depth_ft=8400.0, measured_depth_ft=8400.0),
                ),
            }
        )


def test_upward_frame_and_overlapping_perforations_are_rejected() -> None:
    original = definition()
    with pytest.raises(ValidationError, match="positive-down"):
        ModeledWellDefinition.model_validate(
            {
                **original.model_dump(),
                "coordinates": CoordinateFrame(
                    length_unit=Unit.FOOT, depth_direction=DepthDirection.POSITIVE_UP, datum="Local"
                ),
            }
        )
    with pytest.raises(ValidationError, match="nonoverlapping"):
        ModeledWellDefinition.model_validate(
            {
                **original.model_dump(),
                "perforations": (
                    *original.perforations,
                    PerforationInterval(start_md_ft=8400.0, end_md_ft=8460.0, diameter_ft=0.5),
                ),
            }
        )


def test_prepared_case_rejects_another_session() -> None:
    with pytest.raises(ValidationError, match="model session"):
        PreparedCase(
            model=ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new()),
            case=ObjectRef(
                context=ApplicationContext(
                    session_id=SessionId.new(),
                    connection_id=ConnectionId.new(),
                    project_generation=0,
                ),
                kind=ObjectKind.CASE,
                object_id="case",
            ),
        )


def test_schedule_has_one_ordered_control_per_report_and_matching_exports() -> None:
    session = SessionId.new()
    artifact = ArtifactRef(session_id=session, artifact_id=ArtifactId.new())
    control = ScheduledControl(
        report_index=0, control=ProducerControl(status=WellStatus.OPEN, mode="BHP", bhp_psia=1000.0)
    )
    well = ScheduledWell(export=artifact, controls=(control,))
    request = WellScheduleRequest(
        parent=ModelRef(session_id=session, revision_id=RevisionId.new()), wells=(well,)
    )
    assert WellScheduleRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError, match="without duplicates"):
        ScheduledWell(export=artifact, controls=(control, control))
    with pytest.raises(ValidationError, match="once"):
        WellScheduleRequest(parent=request.parent, wells=(well, well))
    with pytest.raises(ValidationError, match="parent session"):
        WellScheduleRequest(
            parent=ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new()), wells=(well,)
        )
