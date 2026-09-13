"""Write complete inputs from stored arrays, native exports, and event histories."""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import numpy as np

from resinsight_mcp.models.deck import control_keyword, deck_text
from resinsight_mcp.models.general.arrays import fail, value
from resinsight_mcp.models.general.physics.records import PhysicsManifest, TableInfo, UniformRegion
from resinsight_mcp.models.general.physics.validation import rows
from resinsight_mcp.models.general.schedules.records import Control, ScheduleManifest, TimedEvent
from resinsight_mcp.models.general.schedules.service import apply_event

from .records import AssemblyManifest

if TYPE_CHECKING:
    from .service import GeneralCompilation

FIELDS = frozenset(("PORO", "PERMX", "PERMY", "PERMZ"))
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def effective_events(
    service: GeneralCompilation, schedule: ScheduleManifest
) -> Iterator[tuple[float, str, Control]]:
    service.policy.require_memory(
        sum(max(c.count for c in well.chunks) * 2048 for well in schedule.wells) / 1024**2
    )

    def history(name: str, events: Iterator[TimedEvent]) -> Iterator[tuple[float, str, Control]]:
        control = None
        for event in events:
            control = apply_event(control, event)
            yield event.elapsed_days, name, control

    yield from heapq.merge(
        *(history(well.name, service.storage.events(well)) for well in schedule.wells),
        key=lambda event: event[:2],
    )


def check_fields(service: GeneralCompilation, assembly: AssemblyManifest) -> None:
    geometry = service.models.manifest(assembly.info.model)
    names = {field.name for field in geometry.fields}
    omitted = assembly.source.omitted_fields
    if len(set(omitted)) != len(omitted) or set(omitted) != names - FIELDS:
        fail(
            "Explicit omitted_fields must identify every unsupported field, and no supported field."
        )
    if not FIELDS <= names:
        fail("Compilation requires PORO, PERMX, PERMY, and PERMZ for every global cell.")
    active = service.arrays.read(geometry.actnum).astype(bool)
    for field in geometry.fields:
        if field.name in FIELDS:
            descriptor = service.arrays.descriptor(field.array)
            if descriptor.unit != ("1" if field.name == "PORO" else "mD"):
                fail("Compiled porosity requires unit 1, and permeability requires mD.")
            offset = 0
            for part in service.arrays.chunks(field.array):
                selected = part[active[offset : offset + len(part)]]
                invalid = (
                    ((selected <= 0) | (selected > 1)) if field.name == "PORO" else selected < 0
                )
                if np.any(invalid):
                    fail(
                        "Active cells require porosity within (0, 1] and nonnegative permeability."
                    )
                offset += len(part)


def _table(stream: TextIO, service: GeneralCompilation, table: TableInfo) -> None:
    previous = None
    for row in rows(service.arrays, table):
        values = row
        if table.keyword == "PVTO":
            if row[0] == previous:
                values = row[1:]
            elif previous is not None:
                stream.write("/\n")
            previous = row[0]
        stream.write(" " + " ".join(deck_text(v) for v in values) + "\n")
    stream.write("/\n/\n" if table.keyword == "PVTO" else "/\n")


def _physics(stream: TextIO, service: GeneralCompilation, physics: PhysicsManifest) -> None:
    stream.write("PROPS\n")
    for keyword in ("PVTW", "ROCK", "DENSITY", "PVDG", "PVTO", "SWOF", "SGOF"):
        stream.write(keyword + "\n")
        for table in physics.tables:
            if table.keyword == keyword:
                _table(stream, service, table)
    _regions(stream, service, physics)
    stream.write("SOLUTION\n")
    for keyword in ("EQUIL", "RSVD"):
        stream.write(keyword + "\n")
        for table in physics.tables:
            if table.keyword == keyword:
                _table(stream, service, table)


def _regions(stream: TextIO, service: GeneralCompilation, physics: PhysicsManifest) -> None:
    stream.write("REGIONS\n")
    count = service.models.manifest(physics.info.model).shape.cells
    for assignment in physics.regions:
        stream.write(assignment.keyword + "\n")
        if isinstance(assignment.values, UniformRegion):
            stream.write(f" {count}*{assignment.values.value}\n")
        else:
            for part in service.arrays.chunks(assignment.values.array):
                for offset in range(0, len(part), 16):
                    stream.write(" ".join(str(int(v)) for v in part[offset : offset + 16]) + "\n")
        stream.write("/\n")


def _wells(stream: TextIO, service: GeneralCompilation, assembly: AssemblyManifest) -> None:
    if not assembly.connections:
        return
    stream.write("WELSPECS\n")
    for binding in assembly.connections:
        export = service.connections.read(binding.export)
        head = export.wellhead
        plan = value(service.plans.inspect(binding.plan))
        phase = "OIL" if plan.role == "producer" else plan.injection_phase
        if any(character in binding.well for character in "*?["):
            fail("Simulator well names must not contain pattern operators.")
        stream.write(
            f" {deck_text(binding.well)} {deck_text(assembly.source.group)} "
            f"{head.i + 1} {head.j + 1} "
            + ("1*" if head.reference_depth is None else deck_text(head.reference_depth))
            + f" {deck_text(str(phase))} /\n"
        )
    stream.write("/\nCOMPDAT\n")
    for binding in assembly.connections:
        export = service.connections.read(binding.export)
        for connection in service.connections.rows(export):
            cell = connection.cell
            stream.write(
                f" {deck_text(binding.well)} {cell.i + 1} {cell.j + 1} {cell.k + 1} {cell.k + 1} "
                f"{deck_text(connection.status)} 1* {deck_text(connection.factor)} "
                f"{deck_text(connection.diameter)} {deck_text(connection.kh)} "
                f"{deck_text(connection.skin)} 1* {deck_text(connection.direction)} /\n"
            )
    stream.write("/\n")


def _schedule(
    stream: TextIO,
    service: GeneralCompilation,
    assembly: AssemblyManifest,
    schedule: ScheduleManifest,
) -> None:
    stream.write("SCHEDULE\n")
    if assembly.source.write_restart:
        stream.write("RPTRST\n 'BASIC=1' /\n")
    stream.write(f"DRSDT\n {deck_text(assembly.source.dissolution_limit.value)} /\n")
    _wells(stream, service, assembly)
    _, days = service.storage.timeline(schedule.info.reports.artifact)
    events = iter(effective_events(service, schedule))
    event = next(events, None)
    previous = 0.0
    for day in days:
        if day:
            stream.write(f"TSTEP\n {deck_text(float(day - previous))} /\n")
        while event is not None and event[0] == day:
            _, name, control = event
            stream.write(
                control_keyword(
                    name,
                    control.status,
                    control.mode,
                    None if control.rate is None else control.rate.value,
                    control.bhp.value,
                    control.injection_phase,
                )
            )
            event = next(events, None)
        previous = float(day)
    if event is not None:
        fail("A control event falls outside the authored report times.")


def render(service: GeneralCompilation, assembly: AssemblyManifest, directory: Path) -> None:
    check_fields(service, assembly)
    schedule = service.storage.manifest(assembly.info.schedule)
    physics = service.physics.manifest(assembly.info.physics)
    shape = service.models.manifest(assembly.info.model).shape
    regions = {entry.keyword: entry.required_regions for entry in physics.info.coverage}
    max_rows = {
        keyword: max(t.rows for t in physics.tables if t.keyword == keyword)
        for keyword in ("SWOF", "SGOF", "PVDG", "PVTO", "RSVD")
    }
    nwell, nconn = (
        len(assembly.connections),
        max((c.count for c in assembly.connections), default=0),
    )
    sat, pvt, eql = regions["SATNUM"], regions["PVTNUM"], regions["EQLNUM"]
    sat_rows, pvt_rows = (
        max(max_rows["SWOF"], max_rows["SGOF"]),
        max(max_rows["PVTO"], max_rows["PVDG"]),
    )
    start = schedule.info.start_date
    text = (
        f"RUNSPEC\nDIMENS\n {shape.nx} {shape.ny} {shape.nz} /\n"
        f"TABDIMS\n {sat} {pvt} {sat_rows} {pvt_rows} 1 {max_rows['PVTO']} 1 1 1 1 1 1 {pvt} /\n"
        f"EQLDIMS\n {eql} 1* {max_rows['RSVD']} 1 {max_rows['RSVD']} /\n"
        f"OIL\nGAS\nWATER\nDISGAS\n{physics.info.unit_system}\n"
        f"START\n {start.day} '{MONTHS[start.month - 1]}' {start.year} /\n"
        f"WELLDIMS\n {nwell} {nconn} 1 {nwell} /\nUNIFOUT\nGRID\n"
        "INCLUDE\n 'GRID.INC' /\nINCLUDE\n 'PHYSICS.INC' /\nSUMMARY\nFOPR\n"
    )
    if nwell:
        text += "WBHP\n /\nWOPR\n /\nWWIR\n /\nWGIR\n /\n"
    (directory / "MODEL.DATA").write_text(text + "INCLUDE\n 'SCHEDULE.INC' /\n")
    with (directory / "GRID.INC").open("w") as stream:
        service.models.export_grdecl(assembly.info.model, stream, fields=FIELDS)
    with (directory / "PHYSICS.INC").open("w") as stream:
        _physics(stream, service, physics)
    with (directory / "SCHEDULE.INC").open("w") as stream:
        _schedule(stream, service, assembly, schedule)
