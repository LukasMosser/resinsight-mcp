"""Public engineering examples preserve identity, units and array meaning."""

import json
from datetime import date

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import (
    ActiveCellMap,
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    Dimension,
    MeasuredDepthInterval,
    ModelRef,
    Quantity,
    ReportSeries,
    ReportTime,
    Unit,
)
from resinsight_mcp.contracts.identifiers import GridId, RevisionId, SessionId


def test_model_identity_survives_json_without_accepting_other_identifier_kinds(
    model: ModelRef,
) -> None:
    assert ModelRef.model_validate_json(model.model_dump_json()) == model
    payload = json.loads(model.model_dump_json())
    payload["revision_id"] = payload["session_id"]
    with pytest.raises(ValidationError):
        ModelRef.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        RevisionId(str(model.session_id))
    with pytest.raises(ValidationError):
        SessionId("session_not-a-uuid")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "4800"])
def test_pressure_rejects_nonfinite_or_coerced_values(value: object) -> None:
    with pytest.raises(ValidationError):
        Quantity.model_validate({"value": value, "unit": Unit.PSI, "dimension": Dimension.PRESSURE})


def test_pressure_cannot_be_labeled_as_length() -> None:
    assert Quantity(value=4800.0, unit=Unit.PSI, dimension=Dimension.PRESSURE).value == 4800.0
    with pytest.raises(ValidationError):
        Quantity(value=4800.0, unit=Unit.FOOT, dimension=Dimension.PRESSURE)


def test_fixture_depth_interval_keeps_feet_and_explicit_direction() -> None:
    frame = CoordinateFrame(
        length_unit=Unit.FOOT,
        depth_direction=DepthDirection.POSITIVE_DOWN,
        datum="SPE1 local origin",
    )
    interval = MeasuredDepthInterval(start=8326.0, end=8424.0, unit=Unit.FOOT)
    assert interval.end - interval.start == 98.0
    assert frame.depth_direction == DepthDirection.POSITIVE_DOWN
    assert MeasuredDepthInterval.model_validate_json(interval.model_dump_json()).unit == Unit.FOOT
    with pytest.raises(ValidationError):
        CoordinateFrame(
            length_unit=Unit.PSI, depth_direction=DepthDirection.POSITIVE_DOWN, datum="local"
        )


@pytest.mark.parametrize(
    ("start", "end", "unit"),
    [
        (8424.0, 8326.0, Unit.FOOT),
        (8326.0, 8326.0, Unit.FOOT),
        (-1.0, 1.0, Unit.FOOT),
        (0.0, 1.0, Unit.DAY),
        (0.0, float("inf"), Unit.FOOT),
    ],
)
def test_invalid_measured_depth_intervals(start: float, end: float, unit: Unit) -> None:
    with pytest.raises(ValidationError):
        MeasuredDepthInterval(start=start, end=end, unit=unit)


def test_active_array_order_is_explicit_and_can_skip_inactive_cells(model: ModelRef) -> None:
    grid = GridId.new()
    mapping = ActiveCellMap(
        model=model,
        grid_id=grid,
        dimensions=(10, 10, 3),
        cells=(CellIndex(i=4, j=4, k=2), CellIndex(i=4, j=4, k=0)),
    )
    assert mapping.cell_at(0).index == CellIndex(i=4, j=4, k=2)
    assert mapping.cell_at(1).index == CellIndex(i=4, j=4, k=0)
    assert mapping.cell_at(0).grid_id == grid
    assert ActiveCellMap.model_validate_json(mapping.model_dump_json()) == mapping
    for bad_index in (-1, 2, True):
        with pytest.raises(IndexError):
            mapping.cell_at(bad_index)


@pytest.mark.parametrize(
    "cells", [(CellIndex(i=4, j=4, k=0), CellIndex(i=4, j=4, k=0)), (CellIndex(i=4, j=4, k=3),)]
)
def test_mapping_rejects_duplicate_or_outside_cells(
    model: ModelRef, cells: tuple[CellIndex, ...]
) -> None:
    with pytest.raises(ValidationError):
        ActiveCellMap(model=model, grid_id=GridId.new(), dimensions=(10, 10, 3), cells=cells)


def test_cell_indices_do_not_accept_negative_or_boolean_indices() -> None:
    for value in (-1, True):
        with pytest.raises(ValidationError):
            CellIndex(i=value, j=0, k=0)


@pytest.mark.parametrize(
    ("index", "days", "calendar"),
    [(0, 31.0, date(2015, 2, 1)), (1, 0.0, date(2015, 2, 1)), (1, 31.0, date(2014, 12, 31))],
)
def test_report_series_rejects_regressing_simulation_history(
    index: int, days: float, calendar: date
) -> None:
    with pytest.raises(ValidationError):
        ReportSeries(
            reports=(
                ReportTime(index=0, elapsed_days=0.0, calendar_date=date(2015, 1, 1)),
                ReportTime(index=index, elapsed_days=days, calendar_date=calendar),
            )
        )
