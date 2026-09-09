"""Reusable engineering inputs and session-specific creation requests."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveFloat, model_validator

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import ActiveCellMap, CellIndex
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.wells import WellControl, WellName
from resinsight_mcp.models.imports import ImportReceipt

from .grid import Equilibrium, LayeredGrid


class SyntheticWell(Record):
    name: WellName
    cell: CellIndex
    diameter_ft: PositiveFloat
    reference_depth_ft: float
    control: WellControl


class SyntheticModelSpec(Record):
    template_version: Literal["spe1-field-synthetic-v1"] = "spe1-field-synthetic-v1"
    unit_system: Literal["FIELD"] = "FIELD"
    grid: LayeredGrid
    initial: Equilibrium
    wells: tuple[SyntheticWell, SyntheticWell]
    start_date: date
    report_intervals_days: Annotated[tuple[PositiveFloat, ...], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def check_model(self) -> Self:
        if sum(self.report_intervals_days) > 3660:
            raise ValueError("The schedule must not exceed 3,660 days.")
        if self.wells[0].name == self.wells[1].name:
            raise ValueError("The two well names must differ.")
        if self.wells[0].cell == self.wells[1].cell:
            raise ValueError("The two wells must occupy different cells.")
        if {well.control.kind for well in self.wells} != {"producer", "injector"}:
            raise ValueError("The model requires one injector and one producer.")
        nx, ny, nz = self.grid.dimensions
        if any(well.cell.i >= nx or well.cell.j >= ny or well.cell.k >= nz for well in self.wells):
            raise ValueError("Each well completion must lie inside the active grid.")
        return self


class SyntheticModelRequest(Record):
    session_id: SessionId
    datum: Text
    specification: SyntheticModelSpec


class SyntheticModelReceipt(Record):
    imported: ImportReceipt
    specification_source: ArtifactRef
    active_cells: ActiveCellMap
