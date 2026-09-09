"""View context and image outcomes keep successful edits visible."""

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    FiniteFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from ._base import Record, Text
from .engineering import (
    CellIndex,
    CoordinateFrame,
    MeasuredDepthInterval,
    ModelRef,
    ReportTime,
    Unit,
)
from .errors import OperationResult, Success
from .identifiers import EditId, GridId, ObservationId, ResultId
from .jobs import LoadedResult, Result
from .models import ArtifactRef
from .sessions import ObjectKind, ObjectRef

type Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class Projection(StrEnum):
    PERSPECTIVE = "perspective"
    ORTHOGRAPHIC = "orthographic"


class Camera(Record):
    """Camera positions use native display coordinates; parallel scale is half the view height."""

    position: Vector3
    target: Vector3
    up: Vector3
    projection: Projection
    field_of_view_degrees: Annotated[float, Field(gt=0, lt=180)] | None = None
    parallel_scale: PositiveFloat | None = None

    @model_validator(mode="after")
    def check_camera(self) -> Self:
        direction = tuple(
            target - position for target, position in zip(self.target, self.position, strict=True)
        )
        if direction == (0, 0, 0) or self.up == (0, 0, 0):
            raise ValueError("The camera requires a viewing direction and a nonzero up vector.")
        x, y, z = direction
        u, v, w = self.up
        if (y * w - z * v, z * u - x * w, x * v - y * u) == (0, 0, 0):
            raise ValueError("The up vector cannot be parallel to the viewing direction.")
        if self.projection == Projection.PERSPECTIVE:
            if self.field_of_view_degrees is None or self.parallel_scale is not None:
                raise ValueError("Perspective requires a field of view and no parallel scale.")
        elif self.parallel_scale is None or self.field_of_view_degrees is not None:
            raise ValueError(
                "Orthographic projection requires a parallel scale and no field of view."
            )
        return self


class ResultViewState(Record):
    """Observed camera settings identify a view of one trusted loaded result."""

    loaded: LoadedResult
    view: ObjectRef
    camera: Camera
    vertical_exaggeration: PositiveFloat
    scene_version: NonNegativeInt

    @model_validator(mode="after")
    def check_view(self) -> Self:
        if self.view.kind != ObjectKind.VIEW or self.view.context != self.loaded.case.context:
            raise ValueError("The view and loaded case must share the current application context.")
        return self


class Property(Record):
    name: Text
    unit: Unit


class Legend(Record):
    """Legend bounds use the selected property's unit."""

    minimum: FiniteFloat
    maximum: FiniteFloat

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        if self.maximum <= self.minimum:
            raise ValueError("The legend maximum must exceed its minimum.")
        return self


class CellRangeFilter(Record):
    grid_id: GridId
    minimum: CellIndex
    maximum: CellIndex
    include: bool

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        if (
            self.minimum.i > self.maximum.i
            or self.minimum.j > self.maximum.j
            or self.minimum.k > self.maximum.k
        ):
            raise ValueError("Filter minimum indices must not exceed maximum indices.")
        return self


class ViewContext(Record):
    model: ModelRef
    result_id: ResultId
    grid_id: GridId
    case: ObjectRef
    view: ObjectRef
    scene_version: NonNegativeInt
    property: Property
    report_time: ReportTime
    coordinates: CoordinateFrame
    camera: Camera
    vertical_exaggeration: PositiveFloat
    legend: Legend
    filters: tuple[CellRangeFilter, ...]
    selected_wells: tuple[ObjectRef, ...] = ()

    @model_validator(mode="after")
    def check_context(self) -> Self:
        if self.case.kind != ObjectKind.CASE or self.view.kind != ObjectKind.VIEW:
            raise ValueError(
                "A view context requires case and view references of the correct kind."
            )
        if self.case.context != self.view.context:
            raise ValueError("The case and view must share an application context.")
        if self.model.session_id != self.view.context.session_id:
            raise ValueError("The view and model revision must belong to the same session.")
        if any(item.grid_id != self.grid_id for item in self.filters):
            raise ValueError("All filters must use the view's grid identity.")
        if len(set(self.selected_wells)) != len(self.selected_wells):
            raise ValueError("Select each well once.")
        if any(
            item.kind != ObjectKind.WELL or item.context != self.view.context
            for item in self.selected_wells
        ):
            raise ValueError("Selected wells must belong to the view's application context.")
        return self

    def require_result(self, result: Result) -> None:
        """Check this view against the stored result before rendering or saving an observation."""
        if (
            self.result_id != result.result_id
            or self.model != result.model
            or self.grid_id != result.grid_id
        ):
            raise ValueError("The view must identify the result's exact model revision and grid.")
        if self.report_time not in result.report_series.reports:
            raise ValueError("The view report must exist in the result's report series.")


class RenderRequest(Record):
    result: Result
    context: ViewContext
    width: PositiveInt
    height: PositiveInt

    @model_validator(mode="after")
    def check_result(self) -> Self:
        self.context.require_result(self.result)
        return self


class ImageArtifact(Record):
    """Declared saved-image metadata; the renderer must decode the actual image."""

    artifact: ArtifactRef
    media_type: Literal["image/png"] = "image/png"
    width: PositiveInt
    height: PositiveInt


class Observation(Record):
    observation_id: ObservationId
    context: ViewContext
    image: ImageArtifact
    captured_at: AwareDatetime

    @field_validator("captured_at")
    @classmethod
    def check_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Capture timestamps must use UTC.")
        return value

    @model_validator(mode="after")
    def check_image_owner(self) -> Self:
        if self.image.artifact.session_id != self.context.model.session_id:
            raise ValueError("The image artifact must belong to the observation session.")
        return self


class PerforationEditRequest(Record):
    """A visual well edit does not create or change a simulator revision."""

    model: ModelRef
    well: ObjectRef
    interval: MeasuredDepthInterval
    expected_scene_version: NonNegativeInt

    @model_validator(mode="after")
    def check_well(self) -> Self:
        if self.well.kind != ObjectKind.WELL:
            raise ValueError("A perforation edit requires a well reference.")
        if self.well.context.session_id != self.model.session_id:
            raise ValueError("The well and model revision must belong to the same session.")
        return self


class EditReceipt(Record):
    effect: Literal["applied"] = "applied"
    edit_id: EditId
    request: PerforationEditRequest
    scene_version: NonNegativeInt

    @model_validator(mode="after")
    def check_version(self) -> Self:
        if self.scene_version <= self.request.expected_scene_version:
            raise ValueError("An applied edit must advance the scene version.")
        return self


class ViewUpdateRequest(Record):
    context: ViewContext
    width: PositiveInt
    height: PositiveInt
    expected_observation_id: ObservationId | None = None


class ViewEditReceipt(Record):
    effect: Literal["applied"] = "applied"
    edit_id: EditId
    previous_scene_version: NonNegativeInt
    context: ViewContext

    @model_validator(mode="after")
    def check_version(self) -> Self:
        if self.context.scene_version != self.previous_scene_version + 1:
            raise ValueError("A view edit must advance the scene version once.")
        return self


class EditedView(Record):
    """An image failure preserves the applied edit receipt without an old image."""

    edit: EditReceipt | ViewEditReceipt
    observation: OperationResult[Observation]

    @model_validator(mode="after")
    def check_observation(self) -> Self:
        if isinstance(self.observation.outcome, Success):
            context = self.observation.outcome.value.context
            if isinstance(self.edit, ViewEditReceipt):
                if context != self.edit.context:
                    raise ValueError("The observation must show the complete applied view context.")
                return self
            if context.model != self.edit.request.model:
                raise ValueError("The observation must identify the edited model context.")
            if context.view.context != self.edit.request.well.context:
                raise ValueError("The observation must identify the edited application context.")
            if context.scene_version != self.edit.scene_version:
                raise ValueError("The observation must show the resulting scene version.")
        return self
