"""Run the official parser in an isolated process without starting a simulator."""

import json
import math
import sys
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

from resinsight_mcp.contracts.engineering import CellIndex

from .records import FieldCellProperties, ModelInspection, ModelSummary

REQUIRED = frozenset(
    "RUNSPEC DIMENS OIL WATER GAS DISGAS FIELD START WELLDIMS GRID DX DY DZ TOPS PORO "
    "PERMX PERMY PERMZ PROPS PVTW ROCK SWOF SGOF DENSITY PVDG PVTO SOLUTION EQUIL RSVD "
    "SUMMARY SCHEDULE WELSPECS COMPDAT WCONPROD WCONINJE TSTEP".split()
)
SUPPORTED = REQUIRED | frozenset(
    "TITLE EQLDIMS TABDIMS UNIFOUT INIT REGIONS FIPNUM RPTSCHED RPTRST DRSDT "
    "FOPR FGOR BPR BGSAT WBHP WGIR WGIT WGPR WGPT WOPR WOPT WWIR WWIT WWPR WWPT".split()
)
MAX_CELLS = 10_000
MAX_WELLS = 32
MAX_REPORT_STEPS = 256
MAX_DAYS = 3660


def _items(record: Any) -> dict[str, Any]:
    return {item.name(): item for item in record}


def _explicit(items: dict[str, Any], name: str) -> Any:
    item = items[name]
    if item.defaulted or not item.valid:
        raise ValueError(f"Well controls require an explicit {name} value.")
    return item.value


def _positive(value: Any, name: str, *, zero: bool = False) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    if value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name} has an invalid sign or zero value.")


def _allowed_items(items: dict[str, Any], allowed: set[str]) -> None:
    if extra := [
        name for name, item in items.items() if not item.defaulted and name not in allowed
    ]:
        raise ValueError(f"Unsupported explicit items: {', '.join(extra)}.")


def _control(keyword: Any, record: Any) -> str:
    items = _items(record)
    well = _explicit(items, "WELL")
    if any(character in well for character in "*?["):
        raise ValueError("Well controls require exact well names.")
    status = _explicit(items, "STATUS")
    mode = _explicit(items, "CMODE")
    rate_mode = "ORAT" if keyword.name == "WCONPROD" else "RATE"
    if status not in {"OPEN", "SHUT"} or mode not in {rate_mode, "BHP"}:
        raise ValueError(f"Unsupported control status or mode for {well}.")
    _positive(_explicit(items, "BHP"), "BHP")
    if mode == rate_mode:
        _positive(_explicit(items, rate_mode), rate_mode, zero=status == "SHUT")
    if keyword.name == "WCONINJE" and _explicit(items, "TYPE") not in {"GAS", "WATER"}:
        raise ValueError("Injection requires GAS or WATER.")
    allowed = {"WELL", "STATUS", "CMODE", "BHP", mode}
    if keyword.name == "WCONINJE":
        allowed.add("TYPE")
    _allowed_items(items, allowed)
    return well


def _controls(deck: Any, active_cells: set[tuple[int, int, int]]) -> None:
    declared: set[str] = set()
    completed: set[str] = set()
    controlled: set[str] = set()
    roles: dict[str, str] = {}
    for keyword in deck:
        if keyword.name == "WELSPECS":
            _declare(keyword, declared)
        elif keyword.name == "COMPDAT":
            completed.update(_completion(record, declared, active_cells) for record in keyword)
        elif keyword.name in {"WCONPROD", "WCONINJE"}:
            for record in keyword:
                name = _control(keyword, record)
                _check_role(name, keyword.name, declared, completed, roles)
                roles[name] = keyword.name
                controlled.add(name)
        elif keyword.name == "TSTEP":
            if not declared or declared != controlled or not declared <= completed:
                raise ValueError("Each scheduled well requires completions and complete controls.")
    if len(declared) > MAX_WELLS:
        raise ValueError("The model exceeds 32 wells.")
    if declared != controlled or not declared <= completed:
        raise ValueError("Each declared well requires completions and complete controls.")


def _declare(keyword: Any, declared: set[str]) -> None:
    for record in keyword:
        items = _items(record)
        name = _explicit(items, "WELL")
        if name in declared:
            raise ValueError("Repeated well declarations are unsupported.")
        _allowed_items(items, {"WELL", "GROUP", "HEAD_I", "HEAD_J", "REF_DEPTH", "PHASE"})
        if _explicit(items, "PHASE") not in {"OIL", "GAS", "WATER"}:
            raise ValueError("Well phases must be OIL, GAS, or WATER.")
        declared.add(name)


def _completion(record: Any, declared: set[str], active_cells: set[tuple[int, int, int]]) -> str:
    items = _items(record)
    name = _explicit(items, "WELL")
    if name not in declared:
        raise ValueError("Each completion must name a declared well without wildcards.")
    _allowed_items(
        items,
        {
            "WELL",
            "I",
            "J",
            "K1",
            "K2",
            "STATE",
            "DIAMETER",
            "CONNECTION_TRANSMISSIBILITY_FACTOR",
            "Kh",
            "SKIN",
            "DIR",
        },
    )
    if _explicit(items, "STATE") != "OPEN":
        raise ValueError(
            "This profile requires OPEN completions and controls well closure separately."
        )
    _positive(_explicit(items, "DIAMETER"), "Completion diameter")
    i, j, k1, k2 = (_explicit(items, key) for key in ("I", "J", "K1", "K2"))
    if k1 > k2 or any((i - 1, j - 1, k - 1) not in active_cells for k in range(k1, k2 + 1)):
        raise ValueError("Every completion must identify active cells in the prepared grid.")
    for key in ("CONNECTION_TRANSMISSIBILITY_FACTOR", "Kh", "SKIN"):
        if not items[key].defaulted:
            _positive(_explicit(items, key), key, zero=key == "SKIN")
    if not items["DIR"].defaulted and _explicit(items, "DIR") not in {"X", "Y", "Z"}:
        raise ValueError("Completion direction must be X, Y, or Z.")
    return name


def _check_role(
    name: str, role: str, declared: set[str], completed: set[str], roles: dict[str, str]
) -> None:
    if name not in declared or name not in completed:
        raise ValueError(f"Well {name} requires a declaration and completion before control.")
    if name in roles and roles[name] != role:
        raise ValueError("Switching a well between production and injection is unsupported.")


def _check_schedule(schedule: Any) -> float:
    reports = schedule.reportsteps
    elapsed = (reports[-1] - reports[0]).total_seconds() / 86400
    if not 1 <= len(reports) - 1 <= MAX_REPORT_STEPS or not 0 < elapsed <= MAX_DAYS:
        raise ValueError("The schedule exceeds 256 report steps or 3,660 days.")
    if any((later - earlier).total_seconds() <= 0 for earlier, later in pairwise(reports)):
        raise ValueError("Report times must increase.")
    for step in range(len(reports)):
        for well in schedule.get_wells(step):
            if not well.connections():
                raise ValueError(f"Well {well.name} has no active completion at step {step}.")
            if well.status() == "OPEN" and not any(
                connection.state == "OPEN" for connection in well.connections()
            ):
                raise ValueError(f"Open well {well.name} requires an open completion.")
            for connection in well.connections():
                _positive(connection.cf, "Parsed connection factor")
                _positive(connection.kh, "Parsed connection permeability-length")
    return elapsed


def _check_inputs(deck: Any) -> tuple[int, int, int]:
    dimensions = tuple(item.get_int(0) for item in deck["DIMENS"][0])
    if len(dimensions) != 3 or min(dimensions) <= 0 or math.prod(dimensions) > MAX_CELLS:
        raise ValueError("The Cartesian grid must contain 1 through 10,000 cells.")
    for name in ("DX", "DY", "DZ", "PERMX", "PERMY", "PERMZ", "PORO"):
        for value in deck[name].get_raw_array():
            _positive(float(value), name)
            if name == "PORO" and value >= 1:
                raise ValueError("Porosity must be less than one.")
    steps = [
        float(value)
        for keyword in deck
        if keyword.name == "TSTEP"
        for value in keyword[0][0].get_raw_data_list()
    ]
    if len(steps) > MAX_REPORT_STEPS or sum(steps) > MAX_DAYS:
        raise ValueError("The schedule exceeds 256 report steps or 3,660 days.")
    for step in steps:
        _positive(step, "Report interval")
    _check_dimensions(deck)
    return dimensions


def _check_dimensions(deck: Any) -> None:
    for name in ("EQLDIMS", "TABDIMS"):
        if name in deck:
            _allowed_items(_items(deck[name][0]), set())
    limits = {
        "MAXWELLS": MAX_WELLS,
        "MAXCONN": MAX_CELLS,
        "MAXGROUPS": 32,
        "MAX_GROUPSIZE": MAX_WELLS,
    }
    items = _items(deck["WELLDIMS"][0])
    _allowed_items(items, set(limits))
    for name, limit in limits.items():
        value = _explicit(items, name)
        if not 1 <= value <= limit:
            raise ValueError(f"WELLDIMS {name} must lie between 1 and {limit}.")
    if len(deck["EQUIL"]) != 1:
        raise ValueError("This profile supports one equilibrium region.")


def _expanded_lengths(deck: Any, name: str, dimensions: tuple[int, int, int]) -> tuple[float, ...]:
    """Expand OPM's inherited layer lengths in global cell order."""
    values = [float(value) for value in deck[name].get_raw_array()]
    ni, nj, nk = dimensions
    area = ni * nj
    total = area * nk
    if not area <= len(values) <= total:
        raise ValueError(f"{name} requires at least one full layer and at most the full grid.")
    while len(values) < total:
        values.append(values[len(values) - area])
    return tuple(values)


def _properties(deck: Any, state: Any, dimensions: tuple[int, int, int]) -> FieldCellProperties:
    field = state.field_props()

    def field_values(name: str) -> tuple[float, ...]:
        keyword = deck[name]
        scale = float(keyword.get_SI_array()[0]) / float(keyword.get_raw_array()[0])
        return tuple(float(value) / scale for value in field.get_double_array(name))

    return FieldCellProperties(
        dx_ft=_expanded_lengths(deck, "DX", dimensions),
        dy_ft=_expanded_lengths(deck, "DY", dimensions),
        dz_ft=_expanded_lengths(deck, "DZ", dimensions),
        porosity=field_values("PORO"),
        permx_millidarcy=field_values("PERMX"),
        permy_millidarcy=field_values("PERMY"),
        permz_millidarcy=field_values("PERMZ"),
    )


def check_dependencies() -> None:
    """Require the pinned parser and its native modules without opening model inputs."""
    import opm.io.deck  # noqa: F401
    import opm.io.ecl_state  # noqa: F401
    import opm.io.parser  # noqa: F401
    import opm.io.schedule  # noqa: F401

    if version("opm") != "2025.10":
        raise ValueError("This import profile requires opm==2025.10.")


def inspect(path: Path) -> ModelInspection:
    check_dependencies()
    # Importing deck enables the supported item value and defaulted properties.
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import ParseContext, Parser, action
    from opm.io.schedule import Schedule

    context = ParseContext([("*", action.throw)])
    deck = Parser().parse(str(path), context)
    names = {keyword.name for keyword in deck}
    units = names & {"FIELD", "METRIC", "LAB", "SI", "PVT-M"}
    if units != {"FIELD"} or deck.count("FIELD") != 1:
        raise ValueError("Declare FIELD once without another unit system.")
    if unsupported := names - SUPPORTED:
        raise ValueError(f"Unsupported keywords: {', '.join(sorted(unsupported))}.")
    if missing := REQUIRED - names:
        raise ValueError(f"Missing required keywords: {', '.join(sorted(missing))}.")
    dimensions = _check_inputs(deck)
    state = EclipseState(deck)
    grid = state.grid()
    actnum = state.field_props().get_int_array("ACTNUM")
    active_cells = tuple(
        CellIndex(i=int(i), j=int(j), k=int(k))
        for index, active in enumerate(actnum)
        if active
        for i, j, k in (grid.getIJK(index),)
    )
    _controls(deck, {(cell.i, cell.j, cell.k) for cell in active_cells})
    schedule = Schedule(deck, state)
    reports = schedule.reportsteps
    elapsed = _check_schedule(schedule)
    summary = ModelSummary(
        support_profile="spe1-field-v2",
        dimensions=dimensions,
        active_cells=state.grid().nactive,
        wells=tuple(well.name for well in schedule.get_wells(len(reports) - 1)),
        report_steps=len(reports) - 1,
        elapsed_days=elapsed,
        keywords=tuple(sorted(names)),
    )
    length_scale = float(deck["DX"].get_SI_array()[0]) / float(deck["DX"].get_raw_array()[0])
    return ModelInspection(
        summary=summary,
        active_cells=active_cells,
        cell_depths_ft=tuple(float(value) / length_scale for value in grid.getCellDepth()),
        cell_volumes_ft3=tuple(float(value) / length_scale**3 for value in grid.getCellVolume()),
        properties=_properties(deck, state, dimensions),
        report_elapsed_days=tuple(
            (report - reports[0]).total_seconds() / 86400 for report in reports
        ),
    )


def _item_values(item: Any) -> tuple[Any, ...]:
    if not len(item):
        return (item.name(), ())
    if item.is_uda():
        values = tuple(
            value.value if value.is_double() or value.is_string() else None
            for value in (item.get_uda(index) for index in range(len(item)))
        )
    elif item.is_double():
        values = tuple(item.get_raw_data_list())
    else:
        values = tuple(item.get_data_list())
    return (item.name(), item.defaulted, values)


def _source_values(path: Path) -> tuple[Any, ...]:
    import opm.io.deck  # noqa: F401
    from opm.io.parser import ParseContext, Parser, action

    deck = Parser().parse(str(path), ParseContext([("*", action.throw)]))
    return tuple(
        (keyword.name, tuple(tuple(_item_values(item) for item in record) for record in keyword))
        for keyword in deck
    )


def main() -> None:
    if sys.argv[1:] == ["--check-dependencies"]:
        try:
            check_dependencies()
        except (ValueError, RuntimeError, ImportError, OSError) as error:
            print(error, file=sys.stderr)
            raise SystemExit(2) from error
        return
    output = Path(sys.argv[2])
    try:
        inspection = inspect(Path(sys.argv[1]))
        if len(sys.argv) > 3 and _source_values(Path(sys.argv[1])) != _source_values(
            Path(sys.argv[3])
        ):
            raise ValueError("Persistent parsed input values differ from the fixed model sources.")
        payload = {"inspection": inspection.model_dump(mode="json")}
    except (ValueError, RuntimeError, IndexError, KeyError, ImportError) as error:
        payload = {"error": str(error)}
    output.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
