"""Use the session's existing native client for complete view operations."""

from datetime import date
from math import isclose
from pathlib import Path
from typing import Protocol, cast

import rips

from resinsight_mcp.contracts.engineering import CellIndex, ReportTime
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.observations import CellRangeFilter, Legend, Property, ViewContext
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication

from ._camera import camera_matches, read_camera, view_matrix
from ._properties import PROPERTY_CATEGORIES


class _Object(Protocol):
    def address(self) -> int: ...
    def update(self) -> None: ...
    def delete(self) -> None: ...


class _Legend(_Object, Protocol):
    result_variable_usage: str
    range_type: str
    user_defined_min: float
    user_defined_max: float
    mapping_mode: str
    center_legend_around_zero: bool
    precision: int
    actual_minimum: float
    actual_maximum: float


class _Colors(_Object, Protocol):
    result_type: str
    result_variable: str
    porosity_model_type: str

    def result_var_legend_definition_list(self) -> list[_Legend]: ...


class _Range(_Object, Protocol):
    is_checked: bool
    filter_type: str
    grid_index: int
    start_index_i: int
    start_index_j: int
    start_index_k: int
    cell_count_i: int
    cell_count_j: int
    cell_count_k: int


class _Filters(_Object, Protocol):
    active: bool
    combine_filter_mode: str

    def cell_filters(self) -> list[_Range]: ...
    def add_new_object(self, cls: object, field: str) -> _Range: ...


class _Dimensions(Protocol):
    i: int
    j: int
    k: int


class _Grid(Protocol):
    def dimensions(self) -> _Dimensions: ...


class _Date(Protocol):
    year: int
    month: int
    day: int


class _Case(_Object, Protocol):
    def available_properties(self, category: str) -> list[str]: ...
    def time_steps(self) -> list[_Date]: ...
    def days_since_start(self) -> list[float]: ...
    def grid(self, index: int) -> _Grid: ...


class _View(_Object, Protocol):
    camera_matrix: list[float]
    camera_point_of_interest: list[float]
    perspective_projection: bool
    actual_camera_field_of_view_y_degrees: float
    actual_camera_parallel_projection_height: float
    grid_z_scale: float
    current_time_step: int

    def set_camera_projection(
        self, perspective: bool, field_of_view_y_degrees: float, parallel_projection_height: float
    ) -> None: ...
    def validate_view_controls(self) -> None: ...
    def case(self) -> _Case: ...
    def cell_result(self) -> _Colors: ...
    def range_filters(self) -> _Filters: ...
    def export_snapshot(self, prefix: str, export_folder: str, width: int, height: int) -> None: ...


class _Project(Protocol):
    def cases(self) -> list[_Case]: ...
    def views(self) -> list[_View]: ...
    def well_paths(self) -> list[_Object]: ...


def _fail(
    message: str, *, uncertain: bool = False, code: ErrorCode = ErrorCode.EXECUTION_FAILED
) -> ContractError:
    return ContractError(
        Error(
            code=code,
            message=message,
            effect=MutationEffect.UNKNOWN if uncertain else MutationEffect.NOT_APPLIED,
        )
    )


def _one[T: _Object](objects: list[T], address: str) -> T:
    matches = [item for item in objects if str(item.address()) == address]
    if len(matches) != 1:
        raise _fail(
            "The selected native object is absent or ambiguous.", code=ErrorCode.STALE_OBJECT
        )
    return matches[0]


class RipsViewBackend:
    def select(self, access: ApplicationAccess, context: ViewContext) -> "RipsNativeView":
        if not isinstance(access.application, RipsApplication):
            raise _fail("The view backend requires the session's native RipsApplication.")
        application = access.application

        def resolve() -> "RipsNativeView":
            project = cast(_Project, application.project())
            if len(access.objects) != 2 + len(context.selected_wells):
                raise _fail("The session did not resolve every selected object.")
            case = _one(project.cases(), access.objects[0].address)
            view = _one(project.views(), access.objects[1].address)
            if view.case().address() != case.address():
                raise _fail(
                    "The selected view belongs to another native case.", code=ErrorCode.STALE_OBJECT
                )
            wells = project.well_paths()
            for selected in access.objects[2:]:
                _one(wells, selected.address)
            return RipsNativeView(application, project, case, view)

        try:
            return application.call(resolve)
        except (AttributeError, ValueError, TypeError) as error:
            raise _fail(f"The selected native objects could not be resolved: {error}") from error


class RipsNativeView:
    def __init__(
        self, application: RipsApplication, project: _Project, case: _Case, view: _View
    ) -> None:
        self._application = application
        self._project = project
        self._case = case
        self._view = view

    def _fresh(self) -> _View:
        return _one(self._project.views(), str(self._view.address()))

    def _category(self, context: ViewContext) -> str:
        category = PROPERTY_CATEGORIES.get(context.property.name)
        if category is None:
            raise _fail(
                "The native adapter has no trusted unit rule for this property.",
                code=ErrorCode.INVALID_MODEL,
            )
        if context.property.name not in self._case.available_properties(category):
            raise _fail(
                "The property is absent from its supported native category.",
                code=ErrorCode.INVALID_MODEL,
            )
        return category

    def _report(self, index: int) -> ReportTime:
        dates = self._case.time_steps()
        days = self._case.days_since_start()
        if not 0 <= index < min(len(dates), len(days)):
            raise _fail(
                "The report index is outside the native case.", code=ErrorCode.INVALID_MODEL
            )
        item = dates[index]
        return ReportTime(
            index=index,
            elapsed_days=days[index],
            calendar_date=date(item.year, item.month, item.day),
        )

    def _legend(self, colors: _Colors) -> _Legend:
        matches = [
            item
            for item in colors.result_var_legend_definition_list()
            if item.result_variable_usage == colors.result_variable
        ]
        if len(matches) != 1:
            raise _fail("The native result has no unique legend.")
        return matches[0]

    def _controls(self, view: _View) -> None:
        try:
            self._application.call(view.validate_view_controls)
        except ContractError as error:
            if error.error.code != ErrorCode.EXECUTION_FAILED:
                raise
            raise ContractError(
                error.error.model_copy(update={"code": ErrorCode.UNSUPPORTED_OPERATION})
            ) from error

    def validate(self, context: ViewContext) -> None:
        def check() -> None:
            self._category(context)
            if self._report(context.report_time.index) != context.report_time:
                raise _fail(
                    "The requested report differs from the native case.",
                    code=ErrorCode.INVALID_MODEL,
                )
            view = self._fresh()
            required = (
                "set_camera_projection",
                "validate_view_controls",
                "actual_camera_field_of_view_y_degrees",
                "actual_camera_parallel_projection_height",
                "range_filters",
            )
            if any(not hasattr(view, name) for name in required):
                raise _fail(
                    "The native application lacks the required P06 view capabilities.",
                    code=ErrorCode.UNSUPPORTED_OPERATION,
                )
            self._controls(view)
            collection = view.range_filters()
            if not hasattr(collection, "combine_filter_mode") or not hasattr(
                collection, "cell_filters"
            ):
                raise _fail(
                    "The native application lacks the required display filter capabilities.",
                    code=ErrorCode.UNSUPPORTED_OPERATION,
                )
            if not hasattr(view.cell_result(), "result_var_legend_definition_list"):
                raise _fail(
                    "The native application lacks the required legend capability.",
                    code=ErrorCode.UNSUPPORTED_OPERATION,
                )
            dimensions = self._case.grid(0).dimensions()
            for item in context.filters:
                if (
                    item.maximum.i >= dimensions.i
                    or item.maximum.j >= dimensions.j
                    or item.maximum.k >= dimensions.k
                ):
                    raise _fail(
                        "A display filter exceeds the native main grid.",
                        code=ErrorCode.INVALID_MODEL,
                    )

        try:
            self._application.call(check)
        except (AttributeError, ValueError, TypeError) as error:
            raise _fail(f"The native view capabilities could not be validated: {error}") from error

    def apply(self, context: ViewContext) -> ViewContext:
        try:
            self._application.call(lambda: self._apply(context), mutation=True)
            actual = self.inspect(context)
            if (
                not camera_matches(context.camera, actual.camera)
                or not isclose(context.legend.minimum, actual.legend.minimum, rel_tol=1e-14)
                or not isclose(context.legend.maximum, actual.legend.maximum, rel_tol=1e-14)
                or actual.model_copy(update={"camera": context.camera, "legend": context.legend})
                != context
            ):
                raise _fail(
                    "The native view did not retain the requested settings.", uncertain=True
                )
            return actual
        except ContractError as error:
            raise ContractError(
                error.error.model_copy(update={"effect": MutationEffect.UNKNOWN})
            ) from error
        except Exception as error:
            raise _fail(
                f"The native view edit could not be confirmed: {error}", uncertain=True
            ) from error

    def _apply(self, context: ViewContext) -> None:
        view = self._fresh()
        colors = view.cell_result()
        colors.result_type = self._category(context)
        colors.porosity_model_type = "MATRIX_MODEL"
        colors.result_variable = context.property.name
        colors.update()
        legend = self._legend(self._fresh().cell_result())
        legend.range_type = "USER_DEFINED_MAX_MIN"
        legend.mapping_mode = "LinearContinuous"
        legend.center_legend_around_zero = False
        legend.precision = 15
        legend.update()
        legend = self._legend(self._fresh().cell_result())
        legend.user_defined_min = context.legend.minimum
        legend.user_defined_max = context.legend.maximum
        legend.update()
        collection = view.range_filters()
        for item in collection.cell_filters():
            item.delete()
        collection.active = True
        collection.combine_filter_mode = "AND"
        collection.update()
        for requested in context.filters:
            item = collection.add_new_object(rips.CellRangeFilter, "CellFilters")
            item.is_checked = True
            item.grid_index = 0
            item.filter_type = "INCLUDE" if requested.include else "EXCLUDE"
            item.start_index_i, item.start_index_j, item.start_index_k = (
                requested.minimum.i + 1,
                requested.minimum.j + 1,
                requested.minimum.k + 1,
            )
            item.cell_count_i = requested.maximum.i - requested.minimum.i + 1
            item.cell_count_j = requested.maximum.j - requested.minimum.j + 1
            item.cell_count_k = requested.maximum.k - requested.minimum.k + 1
            item.update()
        view.grid_z_scale = context.vertical_exaggeration
        view.current_time_step = context.report_time.index
        view.update()
        view.set_camera_projection(
            perspective=context.camera.projection == "perspective",
            field_of_view_y_degrees=context.camera.field_of_view_degrees or 40,
            parallel_projection_height=2 * (context.camera.parallel_scale or 1),
        )
        view = self._fresh()
        view.camera_matrix = view_matrix(context.camera)
        view.camera_point_of_interest = list(context.camera.target)
        view.update()

    def inspect(self, context: ViewContext) -> ViewContext:
        try:
            return self._application.call(lambda: self._inspect(context))
        except ContractError as error:
            if error.error.code in (
                ErrorCode.LOST_CONNECTION,
                ErrorCode.BUSY,
                ErrorCode.UNSUPPORTED_OPERATION,
            ):
                raise
            raise ContractError(
                Error(
                    code=ErrorCode.STALE_OBJECT,
                    message=f"The native view cannot be represented: {error}",
                )
            ) from error
        except (AttributeError, ValueError, TypeError) as error:
            raise ContractError(
                Error(
                    code=ErrorCode.STALE_OBJECT,
                    message=f"The native view cannot be represented: {error}",
                )
            ) from error

    def _inspect(self, context: ViewContext) -> ViewContext:
        view = self._fresh()
        if not hasattr(view, "validate_view_controls"):
            raise _fail(
                "The native application lacks view validation.",
                code=ErrorCode.UNSUPPORTED_OPERATION,
            )
        self._controls(view)
        colors = view.cell_result()
        if (
            colors.result_type != self._category(context)
            or colors.porosity_model_type != "MATRIX_MODEL"
        ):
            raise _fail("The native result category or porosity model changed.")
        legend = self._legend(colors)
        if (
            legend.range_type != "USER_DEFINED_MAX_MIN"
            or legend.mapping_mode != "LinearContinuous"
            or legend.center_legend_around_zero
        ):
            raise _fail("The native legend no longer uses explicit linear bounds.")
        collection = view.range_filters()
        if not collection.active or collection.combine_filter_mode != "AND":
            raise _fail("The native filter collection uses unsupported settings.")
        filters = []
        for item in collection.cell_filters():
            if (
                not isinstance(item, rips.CellRangeFilter)
                or not item.is_checked
                or item.grid_index != 0
                or item.filter_type not in ("INCLUDE", "EXCLUDE")
            ):
                raise _fail("The native view contains an unsupported display filter.")
            filters.append(
                CellRangeFilter(
                    grid_id=context.grid_id,
                    minimum=CellIndex(
                        i=item.start_index_i - 1, j=item.start_index_j - 1, k=item.start_index_k - 1
                    ),
                    maximum=CellIndex(
                        i=item.start_index_i + item.cell_count_i - 2,
                        j=item.start_index_j + item.cell_count_j - 2,
                        k=item.start_index_k + item.cell_count_k - 2,
                    ),
                    include=item.filter_type == "INCLUDE",
                )
            )
        return ViewContext.model_validate(
            {
                **context.model_dump(),
                "property": Property(name=colors.result_variable, unit=context.property.unit),
                "report_time": self._report(view.current_time_step),
                "camera": read_camera(
                    view.camera_matrix,
                    view.camera_point_of_interest,
                    view.perspective_projection,
                    view.actual_camera_field_of_view_y_degrees,
                    view.actual_camera_parallel_projection_height,
                ),
                "vertical_exaggeration": view.grid_z_scale,
                "legend": Legend(minimum=legend.actual_minimum, maximum=legend.actual_maximum),
                "filters": tuple(filters),
            }
        )

    def export(self, folder: Path, width: int, height: int) -> None:
        self._application.call(
            lambda: self._fresh().export_snapshot(
                prefix="observation", export_folder=str(folder), width=width, height=height
            )
        )
