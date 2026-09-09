"""Layered geometry preserves property order through the supported OPM parser."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import CellIndex, ModelRef
from resinsight_mcp.contracts.identifiers import GridId, RevisionId, SessionId
from resinsight_mcp.models.synthetic import Equilibrium, Layer, LayeredGrid
from resinsight_mcp.models.synthetic.grid import render_equilibrium, render_grid


def layered_grid() -> LayeredGrid:
    return LayeredGrid(
        nx=2,
        ny=3,
        dx_ft=10,
        dy_ft=20,
        top_depth_ft=8300,
        layers=tuple(
            Layer(
                thickness_ft=thickness,
                porosity=porosity,
                permeability_x_md=permeability,
                permeability_y_md=permeability / 2,
                permeability_z_md=permeability / 10,
            )
            for thickness, porosity, permeability in ((20, 0.2, 100), (30, 0.3, 200))
        ),
    )


def test_active_cell_order_and_parsed_layer_properties(tmp_path: Path) -> None:
    grid = layered_grid()
    model = ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new())
    mapping = grid.active_cells(model, GridId.new())
    assert mapping.dimensions == (2, 3, 2)
    assert mapping.cell_at(1).index == CellIndex(i=1, j=0, k=0)
    assert mapping.cell_at(2).index == CellIndex(i=0, j=1, k=0)
    assert mapping.cell_at(6).index == CellIndex(i=0, j=0, k=1)
    assert mapping.cell_at(11).index == CellIndex(i=1, j=2, k=1)
    source = tmp_path / "grid.DATA"
    source.write_text("RUNSPEC\nDIMENS\n 2 3 2 /\nFIELD\n" + render_grid(grid))
    result = subprocess.run(
        [sys.executable, "-I", "-c", PARSE_PROPERTIES, str(source)],
        capture_output=True,
        text=True,
        check=True,
    )
    properties = json.loads(result.stdout)
    assert properties["DX"] == [10] * 12
    assert properties["DY"] == [20] * 12
    assert properties["DZ"] == [20] * 6 + [30] * 6
    assert properties["TOPS"] == [8300] * 6
    assert properties["PORO"] == [0.2] * 6 + [0.3] * 6
    assert properties["PERMX"] == [100] * 6 + [200] * 6
    assert properties["PERMY"] == [50] * 6 + [100] * 6
    assert properties["PERMZ"] == [10] * 6 + [20] * 6


PARSE_PROPERTIES = """
import json
import sys
from opm.io.parser import Parser
p = Parser().parse(sys.argv[1])
print(json.dumps({name: p[name].get_raw_array().tolist() for name in
                 ('DX', 'DY', 'DZ', 'TOPS', 'PORO', 'PERMX', 'PERMY', 'PERMZ')}))
"""


@pytest.mark.parametrize(
    "updates", [{"nx": 0}, {"nx": 10000}, {"dx_ft": float("inf")}, {"layers": ()}]
)
def test_invalid_grid_fails_before_generation(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LayeredGrid.model_validate(layered_grid().model_dump() | updates)


@pytest.mark.parametrize("porosity", [0, 1, float("nan")])
def test_invalid_rock_is_rejected(porosity: float) -> None:
    with pytest.raises(ValidationError):
        Layer.model_validate(layered_grid().layers[0].model_dump() | {"porosity": porosity})


def test_initial_contacts_require_positive_down_order() -> None:
    with pytest.raises(ValidationError, match="above"):
        Equilibrium(
            reference_depth_ft=8400,
            reference_pressure_psia=4800,
            water_oil_contact_depth_ft=8300,
            gas_oil_contact_depth_ft=8450,
            dissolved_gas_ratio_mscf_stb=1.27,
        )


def test_equilibrium_preserves_reference_values(tmp_path: Path) -> None:
    initial = Equilibrium(
        reference_depth_ft=8400,
        reference_pressure_psia=4800,
        water_oil_contact_depth_ft=8450,
        gas_oil_contact_depth_ft=8300,
        dissolved_gas_ratio_mscf_stb=1.27,
    )
    source = tmp_path / "initial.DATA"
    source.write_text("RUNSPEC\nFIELD\nEQLDIMS\n /\n" + render_equilibrium(initial))
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import json, sys, opm.io.deck; from opm.io.parser import Parser; "
            "p = Parser().parse(sys.argv[1]); "
            "print(json.dumps([item.value for item in list(p['EQUIL'][0])[:6]]))",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)[:6] == [8400, 4800, 8450, 0, 8300, 0]
