"""Public records for the bounded OPM import service."""

from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    NonNegativeFloat,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from resinsight_mcp.contracts.engineering import CellIndex, ModelRef
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision, PreparedModel


class ImportRequest(BaseModel):
    """Import files below one trusted local directory without editing them."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: SessionId
    source_root: Path
    entrypoint: str
    datum: str


class IncludeEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    target: str


class ModelSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parser_version: Literal["2025.10"] = "2025.10"
    support_profile: Literal["spe1-field-v1", "spe1-field-v2"] = "spe1-field-v1"
    unit_system: Literal["FIELD"] = "FIELD"
    dimensions: tuple[PositiveInt, PositiveInt, PositiveInt]
    active_cells: PositiveInt
    wells: tuple[str, ...]
    report_steps: PositiveInt
    elapsed_days: float
    keywords: tuple[str, ...]


class ImportReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prepared: PreparedModel
    record: ArtifactRef
    summary: ModelSummary


class ImportRecord(BaseModel):
    """Source artifacts belong to the revision and changes stay separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model: ModelRef
    source_entrypoint: str
    sources: dict[str, ArtifactRef]
    includes: tuple[IncludeEdge, ...]
    changes: tuple[()] = ()
    summary: ModelSummary


class DerivedModelRequest(BaseModel):
    """Publish changed inputs with the stored parent's identity and coordinates."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    parent: ModelRef
    source_root: Path
    entrypoint: str


class FieldCellProperties(BaseModel):
    """Expanded properties use global cell order, with I changing fastest."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    dx_ft: tuple[PositiveFloat, ...]
    dy_ft: tuple[PositiveFloat, ...]
    dz_ft: tuple[PositiveFloat, ...]
    porosity: tuple[Annotated[float, Field(gt=0, lt=1)], ...]
    permx_millidarcy: tuple[PositiveFloat, ...]
    permy_millidarcy: tuple[PositiveFloat, ...]
    permz_millidarcy: tuple[PositiveFloat, ...]

    def keyword_arrays(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        """Return the explicit FIELD properties consumed by native input cases."""
        return (
            ("DX", self.dx_ft),
            ("DY", self.dy_ft),
            ("DZ", self.dz_ft),
            ("PORO", self.porosity),
            ("PERMX", self.permx_millidarcy),
            ("PERMY", self.permy_millidarcy),
            ("PERMZ", self.permz_millidarcy),
        )


class ModelInspection(BaseModel):
    """Parser-derived values describe the fixed revision in explicit FIELD units."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    summary: ModelSummary
    active_cells: tuple[CellIndex, ...]
    cell_depths_ft: tuple[FiniteFloat, ...]
    cell_volumes_ft3: tuple[PositiveFloat, ...]
    properties: FieldCellProperties
    report_elapsed_days: tuple[NonNegativeFloat, ...]

    @model_validator(mode="after")
    def check_layout(self) -> Self:
        ni, nj, nk = self.summary.dimensions
        total = ni * nj * nk
        arrays = (self.cell_depths_ft, self.cell_volumes_ft3) + tuple(
            values for _, values in self.properties.keyword_arrays()
        )
        if any(len(values) != total for values in arrays):
            raise ValueError("Each inspected property requires one value per global cell.")
        if len(self.active_cells) != self.summary.active_cells:
            raise ValueError("The active-cell count differs from the summary.")
        if any(cell.i >= ni or cell.j >= nj or cell.k >= nk for cell in self.active_cells):
            raise ValueError("Inspected active cells must fit the grid dimensions.")
        positions = tuple(cell.k * ni * nj + cell.j * ni + cell.i for cell in self.active_cells)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("Active cells must appear once in global cell order.")
        reports = self.report_elapsed_days
        if (
            len(reports) != self.summary.report_steps + 1
            or reports[0] != 0
            or reports[-1] != self.summary.elapsed_days
            or any(later <= earlier for earlier, later in pairwise(reports))
        ):
            raise ValueError("Inspected report times must match the summary and increase.")
        return self


class MaterializedModel(BaseModel):
    """Staged files remain valid only inside the materialization context."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    revision: ModelRevision
    directory: Path
    entrypoint: Path
    property_file: Path
    inspection: ModelInspection
