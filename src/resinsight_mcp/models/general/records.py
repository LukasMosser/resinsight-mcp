"""General corner-point geometry and optional procedural authoring inputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, PositiveFloat, PositiveInt, model_validator

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef

from .arrays import ArrayInfo, AuthoringPolicy


class GridShape(Record):
    nx: PositiveInt
    ny: PositiveInt
    nz: PositiveInt

    @property
    def cells(self) -> int:
        return self.nx * self.ny * self.nz


class CellField(Record):
    name: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")]
    array: ArtifactRef


class CornerPointRequest(Record):
    session_id: SessionId
    name: Text
    shape: GridShape
    coord: ArtifactRef
    zcorn: ArtifactRef
    actnum: ArtifactRef
    fields: tuple[CellField, ...] = ()
    length_unit: Literal["m", "ft"]
    datum: Text
    parent: ModelRef | None = None


class Fault(Record):
    """Offset cells beyond x = intercept + slope * y."""

    intercept: FiniteFloat
    slope: FiniteFloat = 0
    throw: FiniteFloat


class Fold(Record):
    amplitude: FiniteFloat
    wavelength_x: PositiveFloat
    wavelength_y: PositiveFloat
    phase: FiniteFloat = 0


class RockBand(Record):
    """One band gives explicit cell properties over a fraction of model thickness."""

    bottom_fraction: Annotated[float, Field(gt=0, le=1)]
    porosity: Annotated[float, Field(gt=0, lt=1)]
    permeability_md: PositiveFloat


class Channel(Record):
    center_y: FiniteFloat
    amplitude: FiniteFloat
    wavelength: PositiveFloat
    width: PositiveFloat
    permeability_multiplier: PositiveFloat
    porosity_increment: FiniteFloat = 0


class GeologicalRequest(Record):
    session_id: SessionId
    name: Text
    shape: GridShape
    extent_x: PositiveFloat
    extent_y: PositiveFloat
    top_depth: FiniteFloat
    thickness: PositiveFloat
    length_unit: Literal["m", "ft"]
    datum: Text
    folds: tuple[Fold, ...] = ()
    faults: tuple[Fault, ...] = ()
    bands: tuple[RockBand, ...]
    channel: Channel | None = None
    active_ellipse: bool = False
    thickness_variation: Annotated[float, Field(ge=0, lt=1)] = 0
    parent: ModelRef | None = None

    @model_validator(mode="after")
    def ordered_bands(self) -> Self:
        bottoms = [band.bottom_fraction for band in self.bands]
        if (
            not bottoms
            or bottoms[-1] != 1
            or any(b <= a for a, b in zip(bottoms, bottoms[1:], strict=False))
        ):
            raise ValueError("Rock bands must increase and end at fraction one.")
        return self


class NamedArray(Record):
    name: str
    array: ArrayInfo


class GeologicalModel(Record):
    model: ModelRef
    name: str
    shape: GridShape
    active_cells: PositiveInt
    arrays: tuple[NamedArray, ...]
    source: ArtifactRef | None = None


class GeometryManifest(CornerPointRequest):
    version: Literal["corner-point-v1"] = "corner-point-v1"
    source: ArtifactRef | None = None
    active_cells: PositiveInt


class GeneralCapabilities(Record):
    geometry: tuple[str, ...] = ("eclipse_corner_point",)
    generators: tuple[str, ...] = ("folded_faulted_layers", "channel_properties")
    model_cell_ceiling: None = None
    well_count_ceiling: None = None
    schedule_report_ceiling: None = None
    schedule_event_ceiling: None = None
    schedule_controls: tuple[str, ...] = ("producer:ORAT/BHP", "injector:RATE/BHP", "OPEN/SHUT")
    physics_profiles: tuple[str, ...] = ("black_oil_disgas_rsvd",)
    well_coordinate_units: tuple[str, ...] = ("m", "ft")
    well_geometry: str = "Native curves through target points. Independent paths without branches."
    array_order: str = "I fastest, then J, then K. ZCORN uses Eclipse corner ordering."
    policy: AuthoringPolicy
    simulation_ready: bool = False
    limitation: str = (
        "Authored grids, wells, schedules, and regional physics require "
        "complete inputs and validated simulator compilation before execution."
    )
