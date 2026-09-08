"""Units, coordinates, cells, and simulator report times."""

from datetime import date
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Self

from pydantic import (
    Field,
    FiniteFloat,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from ._base import Record, Text
from .identifiers import GridId, RevisionId, SessionId


class ModelRef(Record):
    session_id: SessionId
    revision_id: RevisionId


class Dimension(StrEnum):
    LENGTH = "length"
    PRESSURE = "pressure"
    TIME = "time"
    DIMENSIONLESS = "dimensionless"


class Unit(StrEnum):
    METER = "m"
    FOOT = "ft"
    PASCAL = "Pa"
    BAR = "bar"
    PSI = "psi"
    SECOND = "s"
    DAY = "day"
    ONE = "1"

    @property
    def dimension(self) -> Dimension:
        return _UNIT_DIMENSIONS[self]


_UNIT_DIMENSIONS = {
    Unit.METER: Dimension.LENGTH,
    Unit.FOOT: Dimension.LENGTH,
    Unit.PASCAL: Dimension.PRESSURE,
    Unit.BAR: Dimension.PRESSURE,
    Unit.PSI: Dimension.PRESSURE,
    Unit.SECOND: Dimension.TIME,
    Unit.DAY: Dimension.TIME,
    Unit.ONE: Dimension.DIMENSIONLESS,
}


class UnitSystem(StrEnum):
    FIELD = "FIELD"
    METRIC = "METRIC"
    SI = "SI"


class Quantity(Record):
    value: FiniteFloat
    unit: Unit
    dimension: Dimension

    @model_validator(mode="after")
    def check_dimension(self) -> Self:
        if self.unit.dimension != self.dimension:
            raise ValueError("The unit must match the physical dimension.")
        return self


class DepthDirection(StrEnum):
    POSITIVE_UP = "positive_up"
    POSITIVE_DOWN = "positive_down"


class CoordinateFrame(Record):
    """Coordinates use a named local datum and an explicit Z direction."""

    length_unit: Unit
    depth_direction: DepthDirection
    datum: Text

    @model_validator(mode="after")
    def check_length_unit(self) -> Self:
        if self.length_unit.dimension != Dimension.LENGTH:
            raise ValueError("Coordinates require a length unit.")
        return self


class MeasuredDepthInterval(Record):
    """Distance along a well increases from its measured-depth origin."""

    start: NonNegativeFloat
    end: NonNegativeFloat
    unit: Unit

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.unit.dimension != Dimension.LENGTH:
            raise ValueError("Measured depth requires a length unit.")
        if self.end <= self.start:
            raise ValueError("The end depth must exceed the start depth.")
        return self


class CellIndex(Record):
    """I, J, and K are zero-based structured-grid indices."""

    i: NonNegativeInt
    j: NonNegativeInt
    k: NonNegativeInt


class CellAddress(Record):
    grid_id: GridId
    index: CellIndex


class ActiveCellMap(Record):
    """Tuple order defines the zero-based active-array index."""

    model: ModelRef
    grid_id: GridId
    dimensions: tuple[PositiveInt, PositiveInt, PositiveInt]
    cells: tuple[CellIndex, ...]

    @model_validator(mode="after")
    def check_cells(self) -> Self:
        if len(set(self.cells)) != len(self.cells):
            raise ValueError("Each active cell must appear once.")
        ni, nj, nk = self.dimensions
        if any(cell.i >= ni or cell.j >= nj or cell.k >= nk for cell in self.cells):
            raise ValueError("Active cell indices must fit the grid dimensions.")
        return self

    def cell_at(self, active_index: int) -> CellAddress:
        """Resolve an active-array index without assuming contiguous active cells."""
        if isinstance(active_index, bool) or not 0 <= active_index < len(self.cells):
            raise IndexError("The active-cell index is outside this mapping.")
        return CellAddress(grid_id=self.grid_id, index=self.cells[active_index])


class ReportTime(Record):
    """Simulator calendar dates have no implied timezone."""

    index: NonNegativeInt
    elapsed_days: NonNegativeFloat
    calendar_date: date


class ReportSeries(Record):
    reports: Annotated[tuple[ReportTime, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        for earlier, later in pairwise(self.reports):
            if later.index <= earlier.index or later.elapsed_days <= earlier.elapsed_days:
                raise ValueError("Report indices and elapsed times must increase.")
            if later.calendar_date < earlier.calendar_date:
                raise ValueError("Report dates must not move backward.")
        return self
