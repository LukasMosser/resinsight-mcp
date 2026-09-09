"""Bounded layered geometry and equilibrium inputs in FIELD units."""

from typing import Annotated, Self

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import ActiveCellMap, CellIndex, ModelRef
from resinsight_mcp.contracts.identifiers import GridId


class Layer(Record):
    thickness_ft: PositiveFloat
    porosity: Annotated[float, Field(gt=0, lt=1)]
    permeability_x_md: PositiveFloat
    permeability_y_md: PositiveFloat
    permeability_z_md: PositiveFloat


class LayeredGrid(Record):
    """Each horizontal layer has uniform rock properties and thickness."""

    nx: PositiveInt
    ny: PositiveInt
    dx_ft: PositiveFloat
    dy_ft: PositiveFloat
    top_depth_ft: float
    layers: Annotated[tuple[Layer, ...], Field(min_length=1, max_length=10_000)]

    @model_validator(mode="after")
    def check_size(self) -> Self:
        if self.nx * self.ny * len(self.layers) > 10_000:
            raise ValueError("The grid must contain at most 10,000 cells.")
        return self

    @property
    def dimensions(self) -> tuple[int, int, int]:
        return self.nx, self.ny, len(self.layers)

    def active_cells(self, model: ModelRef, grid_id: GridId) -> ActiveCellMap:
        """Map all cells with I varying fastest, followed by J and K."""
        return ActiveCellMap(
            model=model,
            grid_id=grid_id,
            dimensions=self.dimensions,
            cells=tuple(
                CellIndex(i=i, j=j, k=k)
                for k in range(len(self.layers))
                for j in range(self.ny)
                for i in range(self.nx)
            ),
        )


class Equilibrium(Record):
    """Contacts use feet and positive-down depth in the caller's datum."""

    reference_depth_ft: float
    reference_pressure_psia: PositiveFloat
    water_oil_contact_depth_ft: float
    gas_oil_contact_depth_ft: float
    dissolved_gas_ratio_mscf_stb: PositiveFloat

    @model_validator(mode="after")
    def check_contacts(self) -> Self:
        if self.gas_oil_contact_depth_ft >= self.water_oil_contact_depth_ft:
            raise ValueError("The gas-oil contact must lie above the water-oil contact.")
        return self


def _keyword(name: str, values: list[float]) -> str:
    return f"{name}\n " + " ".join(format(value, ".17g") for value in values) + " /\n"


def render_grid(grid: LayeredGrid) -> str:
    """Write explicit Cartesian properties without interpreting source decks."""
    plane = grid.nx * grid.ny
    count = plane * len(grid.layers)
    values = "GRID\nINIT\n"
    values += _keyword("DX", [grid.dx_ft] * count)
    values += _keyword("DY", [grid.dy_ft] * count)
    values += _keyword("DZ", [layer.thickness_ft for layer in grid.layers for _ in range(plane)])
    values += _keyword("TOPS", [grid.top_depth_ft] * plane)
    for name, properties in (
        ("PORO", [layer.porosity for layer in grid.layers]),
        ("PERMX", [layer.permeability_x_md for layer in grid.layers]),
        ("PERMY", [layer.permeability_y_md for layer in grid.layers]),
        ("PERMZ", [layer.permeability_z_md for layer in grid.layers]),
    ):
        values += _keyword(name, [value for value in properties for _ in range(plane)])
    return values


def render_equilibrium(initial: Equilibrium) -> str:
    """Use one equilibrium region with a constant dissolved-gas ratio."""
    return (
        "SOLUTION\n"
        + _keyword(
            "EQUIL",
            [
                initial.reference_depth_ft,
                initial.reference_pressure_psia,
                initial.water_oil_contact_depth_ft,
                0,
                initial.gas_oil_contact_depth_ft,
                0,
                1,
                0,
                0,
            ],
        )
        + _keyword(
            "RSVD",
            [
                initial.gas_oil_contact_depth_ft,
                initial.dissolved_gas_ratio_mscf_stb,
                initial.water_oil_contact_depth_ft,
                initial.dissolved_gas_ratio_mscf_stb,
            ],
        )
    )
