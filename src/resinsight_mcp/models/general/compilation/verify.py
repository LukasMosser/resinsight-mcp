"""Compare OPM values and effective states against their immutable authored sources."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import islice
from math import isclose
from typing import TYPE_CHECKING, Any

import numpy as np

from resinsight_mcp.models.general.arrays import fail, value
from resinsight_mcp.models.general.physics.records import UniformRegion
from resinsight_mcp.models.general.physics.validation import rows

from .records import AssemblyManifest, ValidationSummary
from .render import FIELDS, effective_events

if TYPE_CHECKING:
    from .service import GeneralCompilation


def require(condition: bool, message: str) -> None:
    if not condition:
        fail("Parsed input differs from authored input: " + message)


def _arrays(service: GeneralCompilation, assembly: AssemblyManifest, deck: Any, state: Any) -> int:
    geometry = service.models.manifest(assembly.info.model)
    require(
        tuple(int(item.value) for item in deck["DIMENS"][0])
        == (geometry.shape.nx, geometry.shape.ny, geometry.shape.nz),
        "Grid dimensions.",
    )
    total = 0
    for name, reference in service.models.references(geometry):
        if name not in FIELDS | {"COORD", "ZCORN", "ACTNUM"}:
            continue
        descriptor = service.arrays.descriptor(reference)
        parsed = (
            deck[name].get_int_array()
            if descriptor.dtype == "int64"
            else deck[name].get_raw_array()
        )
        require(len(parsed) == descriptor.count, f"{name} value count.")
        offset = 0
        for part in service.arrays.chunks(reference):
            actual = parsed[offset : offset + len(part)]
            require(bool(np.allclose(part, actual, rtol=2e-14, atol=0)), f"{name} values.")
            offset += len(part)
        total += offset
    require(state.grid().nactive == geometry.active_cells, "Active cell count.")
    return total


def _values(record: Any) -> Iterator[float]:
    for item in record:
        if item.valid and not item.defaulted:
            if item.is_double():
                yield from item.get_raw_data_list()
            elif item.is_int():
                yield from item.get_data_list()


def _table_rows(keyword: Any, width: int) -> Iterator[tuple[int, tuple[float, ...]]]:
    region = 1
    for record in keyword:
        if keyword.name == "PVTO":
            if not record[0].valid:
                region += 1
                continue
            ratio = record[0].get_raw_data_list()[0]
            values = iter(record[1].get_raw_data_list())
            while part := tuple(islice(values, 3)):
                yield region, (ratio, *part)
        else:
            values = iter(_values(record))
            while part := tuple(islice(values, width)):
                yield region, part
            region += 1


def _physics(service: GeneralCompilation, assembly: AssemblyManifest, deck: Any) -> int:
    physics = service.physics.manifest(assembly.info.physics)
    geometry = service.models.manifest(assembly.info.model)
    require(deck[physics.info.unit_system].name == physics.info.unit_system, "Simulator units.")
    total = 0
    for name in sorted({table.keyword for table in physics.tables}):
        tables = [table for table in physics.tables if table.keyword == name]
        actual = _table_rows(deck[name], len(tables[0].columns))
        expected = ((table.region, row) for table in tables for row in rows(service.arrays, table))
        for (left_region, left), (right_region, right) in zip(expected, actual, strict=True):
            require(
                left_region == right_region
                and len(left) == len(right)
                and all(
                    isclose(a, b, rel_tol=2e-14, abs_tol=0)
                    for a, b in zip(left, right, strict=True)
                ),
                f"{name} table values.",
            )
            total += 1
    for mapping in physics.regions:
        actual = deck[mapping.keyword].get_int_array()
        require(len(actual) == geometry.shape.cells, f"{mapping.keyword} size.")
        if isinstance(mapping.values, UniformRegion):
            require(bool(np.all(actual == mapping.values.value)), f"{mapping.keyword} assignment.")
        else:
            offset = 0
            for part in service.arrays.chunks(mapping.values.array):
                require(
                    bool(np.array_equal(actual[offset : offset + len(part)], part)),
                    f"{mapping.keyword} assignment.",
                )
                offset += len(part)
    return total


def _items(record: Any) -> dict[str, Any]:
    return {item.name(): item for item in record}


def _raw(item: Any) -> Any:
    # OPM can cache converted doubles after state construction.
    return item.get_raw_data_list()[0] if item.is_double() else item.value


def _connections(
    service: GeneralCompilation, assembly: AssemblyManifest, deck: Any, schedule: Any
) -> None:
    records = [record for keyword in deck if keyword.name == "COMPDAT" for record in keyword]
    require(len(records) == assembly.info.connection_count, "Connection record count.")
    offset = 0
    heads = list(deck["WELSPECS"]) if assembly.connections else []
    require(len(heads) == len(assembly.connections), "Well specification count.")
    for binding, head_record in zip(assembly.connections, heads, strict=True):
        export = service.connections.read(binding.export)
        plan = value(service.plans.inspect(binding.plan))
        head = _items(head_record)
        expected_head = {
            "WELL": binding.well,
            "GROUP": assembly.source.group,
            "HEAD_I": export.wellhead.i + 1,
            "HEAD_J": export.wellhead.j + 1,
            "PHASE": "OIL" if plan.role == "producer" else plan.injection_phase,
        }
        require(
            all(_raw(head[key]) == expected for key, expected in expected_head.items()),
            "Well specification values.",
        )
        depth = export.wellhead.reference_depth
        require(
            head["REF_DEPTH"].defaulted
            if depth is None
            else isclose(_raw(head["REF_DEPTH"]), depth, rel_tol=2e-14),
            "Well reference depth.",
        )
        connections = schedule.get_well(binding.well, 0).connections()
        require(len(connections) == export.count, f"{binding.well} active connection count.")
        by_cell = {tuple(connection.pos): connection for connection in connections}
        require(len(by_cell) == export.count, "Connection cells must be unique.")
        for connection in service.connections.rows(export):
            items = _items(records[offset])
            offset += 1
            cell = (connection.cell.i, connection.cell.j, connection.cell.k)
            require(cell in by_cell, "A native connection is absent from the parsed active grid.")
            actual = by_cell[cell]
            expected = {
                "WELL": binding.well,
                "I": cell[0] + 1,
                "J": cell[1] + 1,
                "K1": cell[2] + 1,
                "K2": cell[2] + 1,
                "STATE": connection.status,
                "DIAMETER": connection.diameter,
                "SKIN": connection.skin,
                "DIR": connection.direction,
                "CONNECTION_TRANSMISSIBILITY_FACTOR": connection.factor,
                "Kh": connection.kh,
            }
            require(
                all(
                    isclose(_raw(items[key]), v, rel_tol=2e-14)
                    if isinstance(v, float)
                    else _raw(items[key]) == v
                    for key, v in expected.items()
                ),
                "Native connection values.",
            )
            require(
                isclose(
                    actual.cf, items["CONNECTION_TRANSMISSIBILITY_FACTOR"].get_SI(0), rel_tol=2e-12
                ),
                "Connection factor units.",
            )
            require(
                isclose(actual.kh, items["Kh"].get_SI(0), rel_tol=2e-12),
                "Connection permeability-length units.",
            )
            require(actual.state == connection.status, "Connection status.")


def _controls(
    service: GeneralCompilation, assembly: AssemblyManifest, deck: Any, schedule: Any
) -> None:
    source = service.storage.manifest(assembly.info.schedule)
    _, days = service.storage.timeline(source.info.reports.artifact)
    require(len(schedule.reportsteps) == len(days), "Report count.")
    events = iter(effective_events(service, source))
    event = next(events, None)
    controls = {}
    epoch = datetime.combine(source.info.start_date, datetime.min.time())
    for index, (report, day) in enumerate(zip(schedule.reportsteps, days, strict=True)):
        require(
            abs((report - (epoch + timedelta(days=float(day)))).total_seconds()) < 1e-6,
            "Report dates.",
        )
        while event is not None and event[0] == day:
            controls[event[1]] = event[2]
            event = next(events, None)
        require({well.name for well in schedule.get_wells(index)} == set(controls), "Well names.")
        for name, control in controls.items():
            well = schedule.get_well(name, index)
            require(
                well.status() == control.status
                and well.isproducer() == (control.role == "producer"),
                f"{name} role or status.",
            )
            props = (
                schedule.get_production_properties(name, index)
                if well.isproducer()
                else schedule.get_injection_properties(name, index)
            )
            require(
                isclose(props["bhp_target"], control.bhp.value, rel_tol=2e-14),
                f"{name} pressure control.",
            )
            if control.rate is not None:
                require(
                    isclose(
                        props["oil_rate" if well.isproducer() else "surf_inj_rate"],
                        control.rate.value,
                        rel_tol=2e-14,
                    ),
                    f"{name} rate control.",
                )
    parsed = (keyword for keyword in deck if keyword.name in ("WCONPROD", "WCONINJE"))
    for (_, name, control), keyword in zip(effective_events(service, source), parsed, strict=True):
        items = _items(keyword[0])
        require(
            items["WELL"].value == name and items["CMODE"].value == control.mode,
            "Control name or mode.",
        )
        if control.injection_phase is not None:
            require(items["TYPE"].value == control.injection_phase, "Injection phase.")


def verify(
    service: GeneralCompilation,
    assembly: AssemblyManifest,
    deck: Any,
    state: Any,
    schedule: Any,
    version: str,
) -> ValidationSummary:
    array_values = _arrays(service, assembly, deck, state)
    table_rows = _physics(service, assembly, deck)
    _connections(service, assembly, deck, schedule)
    _controls(service, assembly, deck, schedule)
    require(
        isclose(_raw(deck["DRSDT"][0][0]), assembly.source.dissolution_limit.value, rel_tol=2e-14),
        "Dissolution rate limit.",
    )
    restart = [keyword for keyword in deck if keyword.name == "RPTRST"]
    require(bool(restart) == assembly.source.write_restart, "Restart output selection.")
    if restart:
        require(restart[0][0][0].get_data_list() == ["BASIC=1"], "Restart output frequency.")
    geometry = service.models.manifest(assembly.info.model)
    source = service.storage.manifest(assembly.info.schedule)
    return ValidationSummary(
        parser_version=version,
        unit_system=service.physics.manifest(assembly.info.physics).info.unit_system,
        global_cells=geometry.shape.cells,
        active_cells=geometry.active_cells,
        wells=assembly.info.well_count,
        connections=assembly.info.connection_count,
        reports=source.info.reports.count,
        control_events=source.info.event_count,
        verified_array_values=array_values,
        verified_table_rows=table_rows,
    )
