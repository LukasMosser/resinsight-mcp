"""Read back native grid and summary results through supported RIPS calls."""

from datetime import UTC, date, datetime, time, timedelta
from math import floor, isclose, isfinite, log2
from pathlib import Path
from typing import Protocol, cast

import rips

from resinsight_mcp.contracts.engineering import CellIndex, DepthDirection
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.results import ResultDataset, SummaryCurve
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication

from ._bundles import ResultBundle
from ._common import fail
from .records import CurveValues

GEOMETRY_ABSOLUTE_TOLERANCE = 1e-6


class _IJK(Protocol):
    i: int
    j: int
    k: int


class _Cell(Protocol):
    grid_index: int
    local_ijk: _IJK


class _Point(Protocol):
    x: float
    y: float
    z: float


class _Corners(Protocol):
    c0: _Point
    c1: _Point
    c2: _Point
    c3: _Point
    c4: _Point
    c5: _Point
    c6: _Point
    c7: _Point


class _Date(Protocol):
    year: int
    month: int
    day: int


class _Grid(Protocol):
    def dimensions(self) -> _IJK: ...


class _Case(Protocol):
    file_path: str
    name_setting: str
    name: str

    def address(self) -> int: ...
    def update(self) -> None: ...
    def create_view(self) -> object: ...
    def grid(self) -> _Grid: ...
    def cell_info_for_active_cells(self) -> list[_Cell]: ...
    def active_cell_corners(self) -> list[_Corners]: ...
    def days_since_start(self) -> list[float]: ...
    def time_steps(self) -> list[_Date]: ...
    def active_cell_property(self, category: str, name: str, index: int) -> list[float]: ...


class _Values[T](Protocol):
    values: list[T]


class _Summary(Protocol):
    summary_header_filename: str

    def available_time_steps(self) -> _Values[int]: ...
    def summary_vector_values(self, address: str) -> _Values[float]: ...


class _Plot(Protocol):
    is_using_auto_name: bool
    plot_description: str
    normalize_curve_y_values: bool

    def address(self) -> int: ...
    def update(self) -> None: ...
    def export_snapshot(self, *, export_folder: str, width: int, height: int) -> None: ...


class _Collection(Protocol):
    def new_summary_plot(self, *, summary_cases: list[_Summary], address: str) -> _Plot: ...


class _Project(Protocol):
    def cases(self) -> list[_Case]: ...
    def load_case(self, path: str) -> _Case: ...
    def import_summary_case(self, *, file_name: str) -> _Summary: ...
    def summary_cases(self) -> list[_Summary]: ...
    def descendants(self, cls: object) -> list[_Collection]: ...


def _client(access: ApplicationAccess) -> tuple[RipsApplication, _Project]:
    application = access.application
    if not isinstance(application, RipsApplication):
        fail(
            ErrorCode.UNSUPPORTED_OPERATION, "Native results require the RIPS application backend."
        )
    return application, cast(_Project, application.project())


def _matching(values: list[float], expected: tuple[float, ...]) -> None:
    if len(values) != len(expected):
        fail(ErrorCode.INVALID_MODEL, "Native result arrays have a different length.")
    for actual, reference in zip(values, expected, strict=True):
        # Two single-precision steps allow native serialization rounding.
        tolerance = 2.0 ** (floor(log2(abs(reference))) - 22) if reference else 2.0**-148
        if not isfinite(actual) or abs(actual - reference) > tolerance:
            fail(ErrorCode.INVALID_MODEL, "Native result values differ from the accepted dataset.")


def _address(curve: SummaryCurve | CurveValues) -> str:
    return curve.keyword if curve.scope == "field" else f"{curve.keyword}:{curve.well_name}"


def _summary(project: _Project, bundle: ResultBundle) -> _Summary:
    matches = [
        item
        for item in project.summary_cases()
        if item.summary_header_filename == str(bundle.smspec)
    ]
    if len(matches) != 1:
        fail(ErrorCode.STALE_OBJECT, "The result requires one summary case at its trusted path.")
    return matches[0]


def _verify_summary(summary: _Summary, dataset: ResultDataset) -> None:
    timestamps = summary.available_time_steps().values
    indices = []
    for report in dataset.report_series.reports:
        expected = datetime.combine(report.calendar_date, time(), UTC) + timedelta(
            days=report.elapsed_days % 1
        )
        matches = [
            index for index, stamp in enumerate(timestamps) if stamp == round(expected.timestamp())
        ]
        if len(matches) != 1:
            fail(
                ErrorCode.INVALID_MODEL,
                "Native summary dates do not uniquely match accepted report dates.",
            )
        indices.append(matches[0])
    for curve in dataset.curves:
        values = summary.summary_vector_values(_address(curve)).values
        if len(values) != len(timestamps):
            fail(ErrorCode.INVALID_MODEL, "Native summary values and dates have different lengths.")
        _matching([values[index] for index in indices], curve.values)


class RipsResultBackend:
    def load(self, access: ApplicationAccess, bundle: ResultBundle, dataset: ResultDataset) -> str:
        application, project = _client(access)

        def change() -> str:
            if any(case.file_path == str(bundle.egrid) for case in project.cases()):
                fail(ErrorCode.CONFLICT, "This result already has a native case.")
            if any(
                case.summary_header_filename == str(bundle.smspec)
                for case in project.summary_cases()
            ):
                fail(ErrorCode.CONFLICT, "This result already has a native summary case.")
            case = project.load_case(str(bundle.egrid))
            case.name_setting = "CUSTOM_NAME"
            case.name = f"{bundle.result.result_id} ({bundle.result.model.revision_id})"
            case.update()
            case.create_view()
            project.import_summary_case(file_name=str(bundle.smspec))
            return str(case.address())

        return application.call(change, mutation=True)

    def verify(
        self,
        access: ApplicationAccess,
        case_address: str,
        bundle: ResultBundle,
        dataset: ResultDataset,
    ) -> None:
        application, project = _client(access)

        def read() -> None:
            matches = [case for case in project.cases() if str(case.address()) == case_address]
            if len(matches) != 1:
                fail(ErrorCode.STALE_OBJECT, "The native result case is no longer current.")
            self._verify(project, matches[0], bundle, dataset)

        application.call(read)

    @staticmethod
    def _verify(
        project: _Project, case: _Case, bundle: ResultBundle, dataset: ResultDataset
    ) -> None:
        if case.file_path != str(bundle.egrid):
            fail(
                ErrorCode.INVALID_MODEL,
                "The native case path differs from the trusted result bundle.",
            )
        dimensions = case.grid().dimensions()
        if (dimensions.i, dimensions.j, dimensions.k) != dataset.active_cells.dimensions:
            fail(
                ErrorCode.INVALID_MODEL,
                "The native grid dimensions differ from the accepted model.",
            )
        cells = case.cell_info_for_active_cells()
        if any(item.grid_index != 0 for item in cells):
            fail(ErrorCode.UNSUPPORTED_OPERATION, "Result loading supports the main grid only.")
        mapping = tuple(
            CellIndex(i=item.local_ijk.i, j=item.local_ijk.j, k=item.local_ijk.k) for item in cells
        )
        if mapping != dataset.active_cells.cells:
            fail(
                ErrorCode.INVALID_MODEL,
                "The native active cell order differs from the accepted mapping.",
            )
        RipsResultBackend._verify_geometry(case, dataset)
        RipsResultBackend._verify_reports(case, dataset)
        for prop in dataset.cell_properties:
            for report, expected in zip(dataset.report_series.reports, prop.values, strict=True):
                _matching(
                    case.active_cell_property("DYNAMIC_NATIVE", prop.name, report.index), expected
                )
        _verify_summary(_summary(project, bundle), dataset)

    @staticmethod
    def _verify_geometry(case: _Case, dataset: ResultDataset) -> None:
        if dataset.geometry.coordinates.depth_direction != DepthDirection.POSITIVE_DOWN:
            fail(
                ErrorCode.UNSUPPORTED_OPERATION,
                "Native result geometry requires positive-down depth.",
            )
        corners = case.active_cell_corners()
        if len(corners) != len(dataset.geometry.cell_corners):
            fail(ErrorCode.INVALID_MODEL, "The native geometry has a different active cell count.")
        # RifReaderOpmCommon uses this OPM-to-ResInsight corner mapping.
        for actual, expected in zip(corners, dataset.geometry.cell_corners, strict=True):
            points = (
                actual.c0,
                actual.c1,
                actual.c3,
                actual.c2,
                actual.c4,
                actual.c5,
                actual.c7,
                actual.c6,
            )
            for point, reference in zip(points, expected, strict=True):
                if any(
                    not isclose(observed, wanted, rel_tol=0, abs_tol=GEOMETRY_ABSOLUTE_TOLERANCE)
                    for observed, wanted in zip((point.x, point.y, point.z), reference, strict=True)
                ):
                    fail(
                        ErrorCode.INVALID_MODEL,
                        "The native cell corners differ from the accepted geometry.",
                    )

    @staticmethod
    def _verify_reports(case: _Case, dataset: ResultDataset) -> None:
        days, dates = case.days_since_start(), case.time_steps()
        if len(days) != len(dates):
            fail(
                ErrorCode.INVALID_MODEL,
                "Native report dates and elapsed times have different lengths.",
            )
        for report in dataset.report_series.reports:
            index = report.index
            if index >= len(days) or days[index] != report.elapsed_days:
                fail(
                    ErrorCode.INVALID_MODEL, "The native report index has a different elapsed time."
                )
            observed = dates[index]
            if date(observed.year, observed.month, observed.day) != report.calendar_date:
                fail(
                    ErrorCode.INVALID_MODEL,
                    "The native report index has a different calendar date.",
                )

    def show_curve(
        self,
        access: ApplicationAccess,
        bundle: ResultBundle,
        dataset: ResultDataset,
        curve: CurveValues,
        folder: Path,
        width: int,
        height: int,
    ) -> str:
        application, project = _client(access)

        def change() -> str:
            summary = _summary(project, bundle)
            _verify_summary(summary, dataset)
            collections = project.descendants(rips.SummaryPlotCollection)
            if len(collections) != 1:
                fail(
                    ErrorCode.UNSUPPORTED_OPERATION,
                    "The native project requires one summary plot collection.",
                )
            plot = collections[0].new_summary_plot(summary_cases=[summary], address=_address(curve))
            try:
                plot.is_using_auto_name = False
                plot.normalize_curve_y_values = False
                plot.plot_description = (
                    f"{curve.result.result_id} {_address(curve)} ({curve.unit.value})"
                )
                plot.update()
                _verify_summary(summary, dataset)
                plot.export_snapshot(export_folder=str(folder), width=width, height=height)
            except ContractError as error:
                raise ContractError(
                    Error(
                        code=error.error.code,
                        message="The summary plot changed, but its verification failed.",
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from error
            return str(plot.address())

        return application.call(change, mutation=True)
