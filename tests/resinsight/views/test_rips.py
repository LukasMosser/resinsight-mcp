"""Fixture-only native validation checks do not establish image or application acceptance."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import cast

import pytest

from resinsight_mcp.contracts.engineering import CellIndex, ReportTime, Unit
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.observations import Property, ViewContext
from resinsight_mcp.resinsight.sessions.rips import RipsApplication
from resinsight_mcp.resinsight.views.rips import RipsNativeView, _Case, _Project, _View


@dataclass
class RecordingCalls:
    mutations: list[str] = field(default_factory=list)

    def call[T](self, action: Callable[[], T], *, mutation: bool = False) -> T:
        if mutation:
            self.mutations.append("mutation call")
        return action()


@dataclass
class Dimensions:
    i: int = 3
    j: int = 4
    k: int = 5


class Grid:
    def dimensions(self) -> Dimensions:
        return Dimensions()


@dataclass
class Case:
    properties: dict[str, list[str]]
    report: ReportTime

    def available_properties(self, category: str) -> list[str]:
        return self.properties.get(category, [])

    def time_steps(self) -> list[date]:
        return [self.report.calendar_date] * (self.report.index + 1)

    def days_since_start(self) -> list[float]:
        return [self.report.elapsed_days] * (self.report.index + 1)

    def grid(self, index: int) -> Grid:
        if index != 0:
            raise ValueError("The fixture contains only the main grid.")
        return Grid()


class Filters:
    combine_filter_mode = "AND"

    def cell_filters(self) -> list[object]:
        return []


class Colors:
    def result_var_legend_definition_list(self) -> list[object]:
        return []


@dataclass
class View:
    calls: RecordingCalls
    control_error: ContractError | None = None
    actual_camera_field_of_view_y_degrees: float = 40
    actual_camera_parallel_projection_height: float = 2000

    def address(self) -> int:
        return 11

    def validate_view_controls(self) -> None:
        if self.control_error is not None:
            raise self.control_error

    def set_camera_projection(
        self, perspective: bool, field_of_view_y_degrees: float, parallel_projection_height: float
    ) -> None:
        self.calls.mutations.append("projection")

    def update(self) -> None:
        self.calls.mutations.append("view update")

    def range_filters(self) -> Filters:
        return Filters()

    def cell_result(self) -> Colors:
        return Colors()


class UnpatchedView:
    def address(self) -> int:
        return 11


@dataclass
class Project:
    view: View | UnpatchedView

    def views(self) -> list[View | UnpatchedView]:
        return [self.view]


@dataclass
class Boundary:
    calls: RecordingCalls
    case: Case
    view: View
    project: Project

    def adapter(self) -> RipsNativeView:
        # These fixtures implement only the public methods used during validation.
        return RipsNativeView(
            cast(RipsApplication, self.calls),
            cast(_Project, self.project),
            cast(_Case, self.case),
            cast(_View, self.view),
        )


@pytest.fixture
def boundary(view_context: ViewContext) -> Boundary:
    calls = RecordingCalls()
    view = View(calls)
    case = Case({"DYNAMIC_NATIVE": ["SGAS"], "STATIC_NATIVE": ["PORO"]}, view_context.report_time)
    return Boundary(calls, case, view, Project(view))


@pytest.mark.parametrize("name", ["SGAS", "PORO"])
def test_validate_accepts_supported_property_report_and_main_grid_bounds(
    boundary: Boundary,
    view_context: ViewContext,
    name: str,
) -> None:
    request = view_context.model_copy(update={"property": Property(name=name, unit=Unit.ONE)})
    boundary.adapter().validate(request)
    assert boundary.calls.mutations == []


def test_validate_rejects_property_missing_from_its_native_category(
    boundary: Boundary,
    view_context: ViewContext,
) -> None:
    boundary.case.properties = {"STATIC_NATIVE": ["SGAS"]}
    with pytest.raises(ContractError) as raised:
        boundary.adapter().validate(view_context)
    assert raised.value.error.code == ErrorCode.INVALID_MODEL
    assert raised.value.error.effect == MutationEffect.NOT_APPLIED
    assert boundary.calls.mutations == []


@pytest.mark.parametrize("field", ["calendar_date", "elapsed_days"])
def test_validate_rejects_report_metadata_mismatch(
    boundary: Boundary,
    view_context: ViewContext,
    field: str,
) -> None:
    report = view_context.report_time
    changed = (
        report.calendar_date + timedelta(days=1)
        if field == "calendar_date"
        else report.elapsed_days + 1
    )
    boundary.case.report = report.model_copy(update={field: changed})
    with pytest.raises(ContractError) as raised:
        boundary.adapter().validate(view_context)
    assert raised.value.error.code == ErrorCode.INVALID_MODEL
    assert boundary.calls.mutations == []


@pytest.mark.parametrize("axis, outside", [("i", 3), ("j", 4), ("k", 5)])
def test_validate_rejects_filter_beyond_each_grid_boundary(
    boundary: Boundary,
    view_context: ViewContext,
    axis: str,
    outside: int,
) -> None:
    selected = view_context.filters[0]
    maximum = CellIndex.model_validate({**selected.maximum.model_dump(), axis: outside})
    request = view_context.model_copy(
        update={"filters": (selected.model_copy(update={"maximum": maximum}),)}
    )
    with pytest.raises(ContractError) as raised:
        boundary.adapter().validate(request)
    assert raised.value.error.code == ErrorCode.INVALID_MODEL
    assert boundary.calls.mutations == []


def test_validate_rejects_missing_p06_capabilities(
    boundary: Boundary,
    view_context: ViewContext,
) -> None:
    boundary.project.view = UnpatchedView()
    with pytest.raises(ContractError) as raised:
        boundary.adapter().validate(view_context)
    assert raised.value.error.code == ErrorCode.UNSUPPORTED_OPERATION
    assert boundary.calls.mutations == []


def test_validate_retains_native_control_rejection_without_editing(
    boundary: Boundary,
    view_context: ViewContext,
) -> None:
    rejected = Error(code=ErrorCode.EXECUTION_FAILED, message="Linked views are unsupported.")
    boundary.view.control_error = ContractError(rejected)
    with pytest.raises(ContractError) as raised:
        boundary.adapter().validate(view_context)
    assert raised.value.error.code == ErrorCode.UNSUPPORTED_OPERATION
    assert raised.value.error.message == rejected.message
    assert raised.value.error.effect == MutationEffect.NOT_APPLIED
    assert boundary.calls.mutations == []
