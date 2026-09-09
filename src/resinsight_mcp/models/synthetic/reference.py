"""Named SPE1 reference inputs for the constrained physics template."""

from datetime import date

from resinsight_mcp.contracts.engineering import CellIndex
from resinsight_mcp.contracts.wells import (
    FieldSurfaceRate,
    InjectorControl,
    ProducerControl,
    WellStatus,
)

from .grid import Equilibrium, Layer, LayeredGrid
from .records import SyntheticModelSpec, SyntheticWell


def reference_specification() -> SyntheticModelSpec:
    return SyntheticModelSpec(
        grid=LayeredGrid(
            nx=10,
            ny=10,
            dx_ft=1000,
            dy_ft=1000,
            top_depth_ft=8325,
            layers=tuple(
                Layer(
                    thickness_ft=thickness,
                    porosity=0.3,
                    permeability_x_md=permeability,
                    permeability_y_md=permeability,
                    permeability_z_md=permeability,
                )
                for thickness, permeability in ((20, 500), (30, 50), (50, 200))
            ),
        ),
        initial=Equilibrium(
            reference_depth_ft=8400,
            reference_pressure_psia=4800,
            water_oil_contact_depth_ft=8450,
            gas_oil_contact_depth_ft=8300,
            dissolved_gas_ratio_mscf_stb=1.27,
        ),
        wells=(
            SyntheticWell(
                name="PROD",
                cell=CellIndex(i=9, j=9, k=2),
                diameter_ft=0.5,
                reference_depth_ft=8400,
                control=ProducerControl(
                    status=WellStatus.OPEN,
                    mode="ORAT",
                    oil_rate=FieldSurfaceRate(value=20000, unit="stb/day"),
                    bhp_psia=1000,
                ),
            ),
            SyntheticWell(
                name="INJ",
                cell=CellIndex(i=0, j=0, k=0),
                diameter_ft=0.5,
                reference_depth_ft=8335,
                control=InjectorControl(
                    status=WellStatus.OPEN,
                    phase="GAS",
                    mode="RATE",
                    surface_rate=FieldSurfaceRate(value=100000, unit="Mscf/day"),
                    bhp_psia=9014,
                ),
            ),
        ),
        start_date=date(2015, 1, 1),
        report_intervals_days=(1, 1),
    )
