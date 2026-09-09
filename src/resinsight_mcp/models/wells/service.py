"""Publish bounded FIELD schedule edits through the official OPM parser."""

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.wells import InjectorControl, ProducerControl, WellControl, WellStatus
from resinsight_mcp.models.imports import DerivedModelRequest, ImportReceipt, OpmImportService
from resinsight_mcp.models.imports.records import MaterializedModel

from .records import CompletionExport, CompletionSource, ScheduledWell, WellScheduleRequest

# These variable-record keywords need a final slash after their records.
_TERMINATED = frozenset("PVTO BPR BGSAT WELSPECS COMPDAT WCONPROD WCONINJE".split())
_SCHEDULE = frozenset("WELSPECS COMPDAT WCONPROD WCONINJE TSTEP RPTSCHED RPTRST DRSDT".split())


def _invalid(message: str) -> ContractError:
    return ContractError(Error(code=ErrorCode.INVALID_MODEL, message=message))


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _text(value: str | int | float) -> str:
    if isinstance(value, str):
        if "'" in value or "\n" in value or "\r" in value:
            raise _invalid("Schedule serialization cannot preserve quoted or multiline strings.")
        return f"'{value}'"
    return format(value, ".17g") if isinstance(value, float) else str(value)


type _Scalar = str | int | float | None


def _record_values(record: Any) -> tuple[_Scalar, ...]:
    values: list[_Scalar] = []
    for item in record:
        if item.is_double():
            item.get_raw_data_list()
        if len(item) == 1 and item.defaulted:
            values.append(None)
        else:
            values.extend(_item_value(item, index) for index in range(len(item)))
    return tuple(values)


def _record(record: Any) -> str:
    return (
        " "
        + " ".join("1*" if value is None else _text(value) for value in _record_values(record))
        + " /\n"
    )


def _item_value(item: Any, index: int) -> str | int | float:
    if item.is_int():
        return item.get_int(index)
    if item.is_double():
        return item.get_raw(index)
    if item.is_string():
        return item.get_str(index)
    if item.is_uda():
        return item.get_uda(index).value
    raise _invalid("Schedule serialization requires supported OPM item types.")


def _render(name: str, records: list[str]) -> str:
    return name + "\n" + "".join(records) + ("/\n" if name in _TERMINATED else "")


def _keyword(keyword: Any) -> str:
    if keyword.name == "TITLE":
        return str(keyword)
    return _render(keyword.name, [_record(record) for record in keyword])


def _items(record: Any) -> dict[str, Any]:
    return {item.name(): item for item in record}


@dataclass(frozen=True)
class _Edit:
    export: CompletionExport
    schedule: ScheduledWell

    @property
    def name(self) -> str:
        return self.export.modeled_well.definition.name


def _check_export(edit: _Edit, materialized: MaterializedModel) -> None:
    export = edit.export
    definition = export.modeled_well.definition
    if export.modeled_well.binding.model != materialized.revision.model:
        raise _invalid("Every completion export must name the exact parent model revision.")
    if definition.coordinates != materialized.revision.coordinates:
        raise _invalid("Completion coordinates and depth datum must match the parent model.")
    active = set(materialized.inspection.active_cells)
    ni, nj, _ = materialized.inspection.summary.dimensions
    if export.wellhead.i >= ni or export.wellhead.j >= nj:
        raise _invalid("The exported wellhead must lie inside the parent grid.")
    for connection in export.connections:
        if connection.cell not in active or connection.status != WellStatus.OPEN:
            raise _invalid("Every exported connection must identify an active cell and be OPEN.")
        if not any(
            interval.start_md_ft
            <= connection.start_md_ft
            < connection.end_md_ft
            <= interval.end_md_ft
            and interval.diameter_ft == connection.diameter_ft
            and interval.skin == connection.skin
            for interval in definition.perforations
        ):
            raise _invalid("Connection intervals, diameter, and skin must match a perforation.")


def _check_controls(edit: _Edit, deck: Any, schedule: Any) -> None:
    if edit.name not in {well.name for well in schedule.get_wells(0)}:
        raise _invalid("Requested simulator wells must already exist at report zero.")
    producer = schedule.get_well(edit.name, 0).isproducer()
    phases = {
        _items(record)["TYPE"].value
        for keyword in deck
        if keyword.name == "WCONINJE"
        for record in keyword
        if _items(record)["WELL"].value == edit.name
    }
    for event in edit.schedule.controls:
        if event.report_index >= len(schedule.reportsteps):
            raise _invalid("Control changes must use an existing report index.")
        control = event.control
        if isinstance(control, ProducerControl) != producer:
            raise _invalid("Schedule edits cannot change a well between production and injection.")
        if isinstance(control, InjectorControl) and phases != {control.phase}:
            raise _invalid("Schedule edits cannot change injection phase or edit a changing phase.")


def _completions(export: CompletionExport) -> str:
    name = export.modeled_well.definition.name
    rows = []
    for connection in export.connections:
        cell = connection.cell
        values = (
            name,
            cell.i + 1,
            cell.j + 1,
            cell.k + 1,
            cell.k + 1,
            "OPEN",
        )
        rows.append(
            " "
            + " ".join(_text(value) for value in values)
            + " 1* "
            + _text(connection.compdat_factor_field)
            + " "
            + _text(connection.diameter_ft)
            + " "
            + _text(connection.permeability_length_md_ft)
            + " "
            + _text(connection.skin)
            + " 1* "
            + _text(connection.direction)
            + " /\n"
        )
    return _render("COMPDAT", rows)


def _declaration(record: Any, edit: _Edit) -> str:
    items = _items(record)
    head = edit.export.wellhead
    return (
        " "
        + _text(edit.name)
        + " "
        + _text(items["GROUP"].value)
        + f" {head.i + 1} {head.j + 1} "
        + ("1*" if head.reference_depth_ft is None else _text(head.reference_depth_ft))
        + " "
        + _text(items["PHASE"].value)
        + " /\n"
    )


def _control(name: str, control: WellControl) -> str:
    if isinstance(control, ProducerControl):
        rate = "1*" if control.oil_rate is None else _text(control.oil_rate.value)
        row = (
            f" '{name}' '{control.status}' '{control.mode}' {rate} 4* {_text(control.bhp_psia)} /\n"
        )
        return _render("WCONPROD", [row])
    rate = "1*" if control.surface_rate is None else _text(control.surface_rate.value)
    row = (
        f" '{name}' '{control.phase}' '{control.status}' '{control.mode}' "
        f"{rate} 1* {_text(control.bhp_psia)} /\n"
    )
    return _render("WCONINJE", [row])


def _overlays(edits: dict[str, _Edit], report: int) -> str:
    return "".join(
        _control(edit.name, event.control)
        for edit in edits.values()
        for event in edit.schedule.controls
        if event.report_index == report
    )


def _schedule_keyword(keyword: Any, edits: dict[str, _Edit]) -> str:
    if keyword.name not in {"WELSPECS", "COMPDAT"}:
        return _keyword(keyword)
    rows: list[str] = []
    completions: list[str] = []
    for record in keyword:
        name = _items(record)["WELL"].value
        if name not in edits:
            rows.append(_record(record))
        elif keyword.name == "WELSPECS":
            rows.append(_declaration(record, edits[name]))
            completions.append(_completions(edits[name].export))
    return (_render(keyword.name, rows) if rows else "") + "".join(completions)


def _capacity(keyword: Any, edits: dict[str, _Edit]) -> str:
    items = _items(keyword[0])
    count = max(items["MAXCONN"].value, *(len(edit.export.connections) for edit in edits.values()))
    values = [items[name].value for name in ("MAXWELLS", "MAXCONN", "MAXGROUPS", "MAX_GROUPSIZE")]
    values[1] = count
    return "WELLDIMS\n " + " ".join(_text(value) for value in values) + " /\n"


def _rewrite(deck: Any, edits: dict[str, _Edit]) -> str:
    output: list[str] = []
    report: int | None = None
    for keyword in deck:
        if keyword.name == "SCHEDULE":
            if report is not None:
                raise _invalid("Schedule edits require one SCHEDULE section.")
            report = 0
            output.append("SCHEDULE\n")
        elif report is None:
            output.append(
                _capacity(keyword, edits) if keyword.name == "WELLDIMS" else _keyword(keyword)
            )
        elif keyword.name == "TSTEP":
            for interval in keyword[0][0].get_raw_data_list():
                output.extend((_overlays(edits, report), f"TSTEP\n {_text(interval)} /\n"))
                report += 1
        elif keyword.name in _SCHEDULE:
            output.append(_schedule_keyword(keyword, edits))
        else:
            raise _invalid(f"Schedule edits cannot preserve {keyword.name} inside SCHEDULE.")
    if report is None:
        raise _invalid("Schedule edits require a SCHEDULE section.")
    output.append(_overlays(edits, report))
    return "".join(output)


@dataclass(frozen=True)
class _InputKeyword:
    name: str
    records: tuple[tuple[_Scalar, ...], ...]
    report: int | None = None


def _unchanged(deck: Any, edits: dict[str, _Edit]) -> tuple[_InputKeyword, ...]:
    values: list[_InputKeyword] = []
    report: int | None = None
    for keyword in deck:
        if keyword.name == "TSTEP":
            if report is None:
                raise _invalid("Report intervals must follow SCHEDULE.")
            report += len(keyword[0][0])
            continue
        if keyword.name == "SCHEDULE":
            report = 0
        if keyword.name == "WELLDIMS":
            continue
        records = tuple(
            _record_values(record)
            for record in keyword
            if keyword.name not in {"WELSPECS", "COMPDAT", "WCONPROD", "WCONINJE"}
            or _items(record)["WELL"].value not in edits
        )
        if records or not len(keyword):
            values.append(_InputKeyword(keyword.name, records, report))
    return tuple(values)


def _same_values(first: tuple[_Scalar, ...], second: tuple[_Scalar, ...]) -> bool:
    if len(first) != len(second):
        return False
    return all(
        math.isclose(left, right, rel_tol=4 * sys.float_info.epsilon, abs_tol=0.0)
        if isinstance(left, float) and isinstance(right, float)
        else left == right
        for left, right in zip(first, second, strict=True)
    )


def _same_inputs(first: Any, second: Any, edits: dict[str, _Edit]) -> bool:
    before, after = _unchanged(first, edits), _unchanged(second, edits)
    if len(before) != len(after):
        return False
    for left, right in zip(before, after, strict=True):
        if (
            left.name != right.name
            or left.report != right.report
            or len(left.records) != len(right.records)
        ):
            return False
        if not all(_same_values(a, b) for a, b in zip(left.records, right.records, strict=True)):
            return False
    return True


def _source_comments(directory: Path) -> str:
    comments = ["-- Parent comments describe the original inputs, before this schedule edit.\n"]
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            comments.extend(
                line + "\n"
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.lstrip().startswith("--")
            )
    return "".join(comments)


def _write_candidate(materialized: MaterializedModel, edits: dict[str, _Edit]) -> Path:
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import ParseContext, Parser, action
    from opm.io.schedule import Schedule

    parser = Parser()
    context = ParseContext([("*", action.throw)])
    deck = parser.parse(str(materialized.entrypoint), context)
    for edit in edits.values():
        _check_export(edit, materialized)
    text = _rewrite(deck, edits)
    schedule = Schedule(deck, EclipseState(deck))
    for edit in edits.values():
        _check_controls(edit, deck, schedule)
    candidate = parser.parse_string(text, context)
    if not _same_inputs(deck, candidate, edits):
        raise _invalid("Schedule serialization changed an untouched parent input value.")
    changed = Schedule(candidate, EclipseState(candidate))
    if changed.reportsteps != schedule.reportsteps:
        raise _invalid("Schedule serialization changed the parent report dates.")
    directory = materialized.directory.parent / "schedule-child"
    directory.mkdir()
    path = directory / "SCHEDULE.DATA"
    note = f"-- Schedule child of {materialized.revision.model.revision_id}.\n"
    for edit in edits.values():
        reports = ", ".join(str(event.report_index) for event in edit.schedule.controls)
        note += (
            f"-- Replace requested completions from report zero: {edit.name} "
            f"controls at reports {reports}.\n"
        )
    path.write_text(note + _source_comments(materialized.directory) + text, encoding="utf-8")
    return path


class OpmWellScheduleService:
    """Resolve issued completion exports and publish immutable child input revisions."""

    def __init__(self, imports: OpmImportService, completion_source: CompletionSource) -> None:
        self._imports = imports
        self._completion_source = completion_source

    def publish(self, request: WellScheduleRequest) -> OperationResult[ImportReceipt]:
        receipt: ImportReceipt | None = None
        try:
            edits: dict[str, _Edit] = {}
            for well in request.wells:
                export = _value(self._completion_source.get_export(well.export))
                if export.artifact != well.export:
                    raise _invalid("The resolved export differs from its requested artifact.")
                edit = _Edit(export, well)
                if edit.name in edits:
                    raise _invalid("Each simulator well name must appear once.")
                edits[edit.name] = edit
            with self._imports.materialize(request.parent) as materialized:
                path = _write_candidate(materialized, edits)
                receipt = _value(
                    self._imports.derive_model(
                        DerivedModelRequest(
                            parent=request.parent,
                            source_root=path.parent,
                            entrypoint=path.name,
                        )
                    )
                )
            return OperationResult(outcome=Success(value=receipt))
        except ContractError as error:
            detail = error.error
            if notes := getattr(error, "__notes__", ()):
                detail = detail.model_copy(update={"message": " ".join((detail.message, *notes))})
            if receipt is not None:
                detail = detail.model_copy(
                    update={
                        "effect": MutationEffect.UNKNOWN,
                        "message": (
                            f"{detail.message} Published child revision "
                            f"{receipt.prepared.revision.model.revision_id}."
                        ),
                    }
                )
            return OperationResult(outcome=Failure(error=detail))
        except (OSError, ValueError, RuntimeError, ValidationError) as error:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED
                        if isinstance(error, OSError)
                        else ErrorCode.INVALID_MODEL,
                        message=" ".join(
                            (
                                f"Schedule publication failed: {error}",
                                *getattr(error, "__notes__", ()),
                            )
                        ),
                        effect=MutationEffect.UNKNOWN
                        if receipt is not None
                        else MutationEffect.NOT_APPLIED,
                    )
                )
            )
