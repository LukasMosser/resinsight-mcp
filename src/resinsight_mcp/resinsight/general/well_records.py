"""Native well receipts reference immutable, bounded array outputs."""

from typing import Literal, Self

from pydantic import PositiveInt, model_validator

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ObjectKind, ObjectRef
from resinsight_mcp.models.general.arrays import ArrayInfo
from resinsight_mcp.models.general.records import NamedArray
from resinsight_mcp.models.general.wells import GeneralWellhead, WellPlan

from .records import LoadedGrid


class GeneralWellLoad(Record):
    loaded: LoadedGrid
    plan: ArtifactRef


class GeneralWellBinding(Record):
    loaded: LoadedGrid
    well: ObjectRef
    receipt: ArtifactRef

    @model_validator(mode="after")
    def check_ownership(self) -> Self:
        if self.well.kind != ObjectKind.WELL or self.well.context != self.loaded.case.context:
            raise ValueError("The well and loaded grid must share the current native context.")
        if self.receipt.session_id != self.loaded.model.session_id:
            raise ValueError("The well receipt must belong to the grid session.")
        return self


class GeneralWellReceipt(Record):
    artifact: ArtifactRef
    version: Literal["native-general-well-v1"] = "native-general-well-v1"
    plan: ArtifactRef
    grid_receipt: ArtifactRef
    trajectory: ArrayInfo


class GeneralWellState(Record):
    binding: GeneralWellBinding
    plan: WellPlan
    trajectory: ArrayInfo


class GeneralWellConnections(Record):
    artifact: ArtifactRef
    version: Literal["general-connections-v1"] = "general-connections-v1"
    well_receipt: ArtifactRef
    plan: ArtifactRef
    model: ModelRef
    wellhead: GeneralWellhead
    length_unit: Literal["m", "ft"]
    count: PositiveInt
    measured_depth_semantics: str = (
        "Native aggregate bounds can span gaps between intervals in one cell."
    )
    columns: tuple[NamedArray, ...]
