"""Native geological receipts remain separate from simulation results."""

from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import Camera, ImageArtifact
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef


class GridLoadRequest(Record):
    model: ModelRef
    context: ApplicationContext


class LoadedGrid(Record):
    receipt: ArtifactRef
    model: ModelRef
    case: ObjectRef
    view: ObjectRef
    source: Path
    global_cells: PositiveInt
    active_cells: PositiveInt
    verified_properties: tuple[str, ...]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if (
            self.receipt.session_id != self.model.session_id
            or self.case.context.session_id != self.model.session_id
        ):
            raise ValueError("The receipt, model, and native objects must share a session.")
        check_objects(self.case, self.view)
        if not self.source.is_absolute() or self.active_cells > self.global_cells:
            raise ValueError("A loaded grid requires an absolute source and valid cell counts.")
        return self


class GridRenderRequest(Record):
    loaded: LoadedGrid
    property: str
    camera: Camera
    vertical_exaggeration: PositiveFloat = 1
    slice_j: NonNegativeInt | None = None
    width: PositiveInt = 1200
    height: PositiveInt = 900


class GridObservation(Record):
    artifact: ArtifactRef
    request: GridRenderRequest
    image: ImageArtifact
    captured_at: AwareDatetime
    native_camera: Camera
    maximum_property_error: Annotated[float, Field(ge=0)]


class GridVerifyRequest(Record):
    loaded: LoadedGrid
    global_indices: tuple[NonNegativeInt, ...]


class VerifiedCell(Record):
    global_index: NonNegativeInt
    corners: tuple[tuple[float, float, float], ...]
    maximum_coordinate_error: Annotated[float, Field(ge=0)]


class GridVerification(Record):
    loaded: LoadedGrid
    cells: tuple[VerifiedCell, ...]
    maximum_property_error: Annotated[float, Field(ge=0)]
    coordinate_unit: str
    depth_direction: str = "positive_down"


class GridEdit(Record):
    request: GridRenderRequest
    native_camera: Camera
    applied_at: AwareDatetime


class EditedGrid(Record):
    edit: GridEdit
    observation: OperationResult[GridObservation]


class GridRestoreRequest(Record):
    receipt: ArtifactRef
    case: ObjectRef
    view: ObjectRef

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        check_objects(self.case, self.view)
        if self.receipt.session_id != self.case.context.session_id:
            raise ValueError("The receipt and native objects must share a session.")
        return self


def check_objects(case: ObjectRef, view: ObjectRef) -> None:
    if case.kind != ObjectKind.CASE or view.kind != ObjectKind.VIEW or case.context != view.context:
        raise ValueError("Use a case and view from the same native project context.")
