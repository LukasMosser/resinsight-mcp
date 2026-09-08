"""Run the official parser in an isolated process without starting a simulator."""

import json
import math
import sys
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

from .records import ModelSummary

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


def _controls(deck: Any) -> None:
    declared: set[str] = set()
    completed: set[str] = set()
    controlled: set[str] = set()
    roles: dict[str, str] = {}
    for keyword in deck:
        if keyword.name == "WELSPECS":
            _declare(keyword, declared)
        elif keyword.name == "COMPDAT":
            completed.update(_completion(record, declared) for record in keyword)
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


def _completion(record: Any, declared: set[str]) -> str:
    items = _items(record)
    name = _explicit(items, "WELL")
    if name not in declared:
        raise ValueError("Each completion must name a declared well without wildcards.")
    _allowed_items(items, {"WELL", "I", "J", "K1", "K2", "STATE", "DIAMETER"})
    if _explicit(items, "STATE") != "OPEN":
        raise ValueError(
            "This profile requires OPEN completions and controls well closure separately."
        )
    _positive(_explicit(items, "DIAMETER"), "Completion diameter")
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


def validate(path: Path) -> ModelSummary:
    # Importing deck enables the supported item value and defaulted properties.
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import ParseContext, Parser, action
    from opm.io.schedule import Schedule

    if version("opm") != "2025.10":
        raise ValueError("This import profile requires opm==2025.10.")
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
    _controls(deck)
    state = EclipseState(deck)
    schedule = Schedule(deck, state)
    reports = schedule.reportsteps
    elapsed = _check_schedule(schedule)
    return ModelSummary(
        dimensions=dimensions,
        active_cells=state.grid().nactive,
        wells=tuple(well.name for well in schedule.get_wells(len(reports) - 1)),
        report_steps=len(reports) - 1,
        elapsed_days=elapsed,
        keywords=tuple(sorted(names)),
    )


def main() -> None:
    output = Path(sys.argv[2])
    try:
        summary = validate(Path(sys.argv[1]))
        payload = {"summary": summary.model_dump(mode="json")}
    except (ValueError, RuntimeError, IndexError, KeyError, ImportError) as error:
        payload = {"error": str(error)}
    output.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
