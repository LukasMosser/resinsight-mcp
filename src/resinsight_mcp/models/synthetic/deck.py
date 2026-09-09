"""Generate one complete input deck from the constrained specification."""

from resinsight_mcp.contracts.identifiers import GridId

from ._template import PROPERTIES
from .grid import render_equilibrium, render_grid
from .records import SyntheticModelSpec

SPECIFICATION_PREFIX = "-- synthetic-specification: "
GRID_ID_PREFIX = "-- synthetic-grid-id: "
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def render_deck(specification: SyntheticModelSpec, grid_id: GridId) -> str:
    """Keep canonical specification JSON in the immutable source comments."""
    nx, ny, nz = specification.grid.dimensions
    start = specification.start_date
    source = (
        SPECIFICATION_PREFIX
        + specification.model_dump_json()
        + "\n"
        + GRID_ID_PREFIX
        + str(grid_id)
        + "\n"
        "RUNSPEC\nDIMENS\n"
        f" {nx} {ny} {nz} /\n"
        "EQLDIMS\n /\nTABDIMS\n /\nOIL\nGAS\nWATER\nDISGAS\nFIELD\n"
        f"START\n {start.day} '{_MONTHS[start.month - 1]}' {start.year} /\n"
        "WELLDIMS\n 2 1 1 2 /\nUNIFOUT\n"
    )
    source += render_grid(specification.grid) + PROPERTIES
    source += render_equilibrium(specification.initial)
    names = " ".join(f"'{well.name}'" for well in specification.wells)
    source += f"SUMMARY\nFOPR\nWBHP\n {names} /\nSCHEDULE\nRPTRST\n 'BASIC=1' /\nDRSDT\n 0 /\n"
    source += "WELSPECS\n"
    for well in specification.wells:
        phase = "OIL" if well.control.kind == "producer" else well.control.phase
        source += (
            f" '{well.name}' 'G1' {well.cell.i + 1} {well.cell.j + 1} "
            f"{well.reference_depth_ft:.17g} '{phase}' /\n"
        )
    source += "/\nCOMPDAT\n"
    for well in specification.wells:
        source += (
            f" '{well.name}' {well.cell.i + 1} {well.cell.j + 1} "
            f"{well.cell.k + 1} {well.cell.k + 1} 'OPEN' 2* {well.diameter_ft:.17g} /\n"
        )
    source += "/\n"
    for well in specification.wells:
        control = well.control
        if control.kind == "producer":
            rate = f"{control.oil_rate.value:.17g}" if control.oil_rate is not None else "1*"
            source += (
                f"WCONPROD\n '{well.name}' '{control.status.value}' '{control.mode}' "
                f"{rate} 4* {control.bhp_psia:.17g} /\n/\n"
            )
        else:
            rate = (
                f"{control.surface_rate.value:.17g}" if control.surface_rate is not None else "1*"
            )
            source += (
                f"WCONINJE\n '{well.name}' '{control.phase}' '{control.status.value}' "
                f"'{control.mode}' {rate} 1* {control.bhp_psia:.17g} /\n/\n"
            )
    intervals = " ".join(format(value, ".17g") for value in specification.report_intervals_days)
    return source + f"TSTEP\n {intervals} /\n"


def _read_comment(source: str, prefix: str) -> str:
    records = [line.removeprefix(prefix) for line in source.splitlines() if line.startswith(prefix)]
    if len(records) != 1:
        raise ValueError(f"The generated source must contain exactly one {prefix.strip()} comment.")
    return records[0]


def read_specification(source: str) -> SyntheticModelSpec:
    """Recover the saved specification without interpreting simulator keywords."""
    return SyntheticModelSpec.model_validate_json(_read_comment(source, SPECIFICATION_PREFIX))


def read_grid_id(source: str) -> GridId:
    """Recover the grid identity saved with the generated specification."""
    return GridId(_read_comment(source, GRID_ID_PREFIX))
