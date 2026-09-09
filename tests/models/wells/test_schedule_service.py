"""Inspect immutable child schedules through OPM and the public workspace."""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import opm.io.deck  # noqa: F401
import pytest
from opm.io.ecl_state import EclipseState
from opm.io.parser import Parser
from opm.io.schedule import Schedule

from resinsight_mcp.contracts.engineering import CellIndex
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId, ConnectionId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision, Session
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.wells import (
    FieldSurfaceRate,
    InjectorControl,
    ProducerControl,
    WellStatus,
)
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.models.wells.records import (
    CompletionConnection,
    CompletionExport,
    ModeledWell,
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCase,
    ScheduledControl,
    ScheduledWell,
    TrajectoryPoint,
    TrajectorySample,
    Wellhead,
    WellScheduleRequest,
)
from resinsight_mcp.models.wells.service import OpmWellScheduleService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result
    return result.outcome.value


class IssuedExports:
    """Represent the completion service boundary without launching a native application."""

    def __init__(self, *exports: CompletionExport) -> None:
        self.exports = {export.artifact: export for export in exports}

    def get_export(self, reference: ArtifactRef) -> OperationResult[CompletionExport]:
        if reference not in self.exports:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.NOT_FOUND,
                        message="The completion service did not issue this export.",
                    )
                )
            )
        return OperationResult(outcome=Success(value=self.exports[reference]))


def completion(parent: ModelRevision, name: str = "PROD") -> CompletionExport:
    context = ApplicationContext(
        session_id=parent.model.session_id,
        connection_id=ConnectionId.new(),
        project_generation=1,
    )
    start = TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=0.0)
    end = TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=8500.0)
    modeled = ModeledWell(
        binding=PreparedCase(
            model=parent.model,
            case=ObjectRef(
                context=context,
                kind=ObjectKind.CASE,
                object_id="prepared",
            ),
        ),
        well=ObjectRef(context=context, kind=ObjectKind.WELL, object_id=name),
        version=0,
        definition=ModeledWellDefinition(
            name=name,
            coordinates=parent.coordinates,
            targets=(start, end),
            perforations=(
                PerforationInterval(start_md_ft=8325.0, end_md_ft=8425.0, diameter_ft=0.5),
            ),
        ),
        trajectory=(
            TrajectorySample(**start.model_dump(), measured_depth_ft=0.0),
            TrajectorySample(**end.model_dump(), measured_depth_ft=8500.0),
        ),
    )
    return CompletionExport(
        artifact=ArtifactRef(session_id=parent.model.session_id, artifact_id=ArtifactId.new()),
        modeled_well=modeled,
        wellhead=Wellhead(i=4, j=4, reference_depth_ft=8335.0),
        connections=tuple(
            CompletionConnection(
                cell=CellIndex(i=4, j=4, k=k),
                compdat_factor_field=factor,
                permeability_length_md_ft=kh,
                diameter_ft=0.5,
                skin=0.0,
                direction="Z",
                start_md_ft=start_md,
                end_md_ft=end_md,
            )
            for k, factor, kh, start_md, end_md in (
                (0, 10.07878, 9500.0, 8326.0, 8345.0),
                (1, 1.591386, 1500.0, 8345.0, 8375.0),
                (2, 10.39706, 9800.0, 8375.0, 8424.0),
            )
        ),
    )


@dataclass
class Case:
    store: SqliteWorkspaceStore
    imports: OpmImportService
    parent: ModelRevision
    source: Path
    export: CompletionExport

    def service(self, *exports: CompletionExport) -> OpmWellScheduleService:
        return OpmWellScheduleService(self.imports, IssuedExports(*(exports or (self.export,))))

    def request(self, report: int = 0) -> WellScheduleRequest:
        return WellScheduleRequest(
            parent=self.parent.model,
            wells=(
                ScheduledWell(
                    export=self.export.artifact,
                    controls=(
                        ScheduledControl(
                            report_index=report,
                            control=ProducerControl(
                                status=WellStatus.OPEN,
                                mode="BHP",
                                bhp_psia=1200.1234567890123,
                            ),
                        ),
                    ),
                ),
            ),
        )


def case_for(
    tmp_path: Path,
    *,
    schedule_tail: str = "",
    store_type: type[SqliteWorkspaceStore] = SqliteWorkspaceStore,
) -> Case:
    source = Path(
        shutil.copytree(Path(__file__).parents[1] / "imports/data/spe1", tmp_path / "source")
    )
    if schedule_tail:
        path = source / "includes/schedule.inc"
        path.write_text(path.read_text() + schedule_tail)
    store = store_type.create(tmp_path / "workspace")
    session = value(
        store.create_session(Session(session_id=SessionId.new(), name="Well schedules"))
    )
    imports = OpmImportService(store)
    parent = value(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=source,
                entrypoint="SPE1.DATA",
                datum="SPE1 local datum",
            )
        )
    ).prepared.revision
    return Case(store, imports, parent, source, completion(parent))


def parsed(path: Path) -> tuple[Any, Any]:
    deck = Parser().parse(str(path))
    return deck, Schedule(deck, EclipseState(deck))


def well_state(schedule: Any, name: str, report: int) -> tuple[Any, ...]:
    well = schedule.get_well(name, report)
    properties = (
        schedule.get_production_properties(name, report)
        if well.isproducer()
        else schedule.get_injection_properties(name, report)
    )
    return (
        well.pos(),
        well.status(),
        well.preferred_phase,
        well.group(),
        properties,
        tuple(
            (connection.pos, connection.cf, connection.kh, connection.state)
            for connection in well.connections()
        ),
    )


def test_child_replaces_all_requested_completions_and_preserves_other_well_events(
    tmp_path: Path,
) -> None:
    case = case_for(
        tmp_path,
        schedule_tail="""
COMPDAT
 'PROD' 10 10 2 2 'OPEN' 1* 1* 0.5 /
 'INJ' 1 1 2 2 'OPEN' 1* 1* 0.5 /
/
WCONPROD
 'PROD' 'OPEN' 'ORAT' 18000 4* 1100 /
/
WCONINJE
 'INJ' 'GAS' 'SHUT' 'BHP' 1* 1* 9014 /
/
TSTEP
 2 /
""",
    )
    request = case.request(report=1)
    receipt = value(case.service().publish(request))
    child = receipt.prepared.revision
    assert child.parent == case.parent.model
    assert child.coordinates == case.parent.coordinates
    assert child.model.session_id == case.parent.model.session_id
    assert child.model != case.parent.model
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert value(reopened.get_revision(case.parent.model)) == case.parent
    assert value(reopened.get_revision(child.model)) == child
    imports = OpmImportService(reopened)
    with (
        imports.materialize(case.parent.model) as original,
        imports.materialize(child.model) as changed,
    ):
        parent_deck, parent = parsed(original.entrypoint)
        child_deck, schedule = parsed(changed.entrypoint)
        assert schedule.reportsteps == parent.reportsteps
        assert changed.inspection.properties == original.inspection.properties
        assert changed.inspection.cell_depths_ft == original.inspection.cell_depths_ft
        assert changed.inspection.cell_volumes_ft3 == original.inspection.cell_volumes_ft3
        assert [well_state(schedule, "INJ", step) for step in range(4)] == [
            well_state(parent, "INJ", step) for step in range(4)
        ]
        assert schedule.get_production_properties("PROD", 0) == parent.get_production_properties(
            "PROD", 0
        )
        assert schedule.get_production_properties("PROD", 1)["bhp_target"] == 1200.1234567890123
        assert schedule.get_production_properties("PROD", 2)["oil_rate"] == 18000.0
        assert len(parent.get_well("PROD", 2).connections()) == 2
        for step in range(4):
            assert [
                connection.pos for connection in schedule.get_well("PROD", step).connections()
            ] == [(4, 4, k) for k in range(3)]
        assert {item.name(): item.value for item in child_deck["WELLDIMS"][0]}["MAXCONN"] == 3
        assert {item.name(): item.value for item in parent_deck["WELLDIMS"][0]}["MAXCONN"] == 1
    assert value(reopened.list_jobs(child.model.session_id)) == ()


def test_completion_field_factors_and_control_units_survive_publication(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    injector = completion(case.parent, "INJ")
    request = WellScheduleRequest(
        parent=case.parent.model,
        wells=(
            case.request().wells[0],
            ScheduledWell(
                export=injector.artifact,
                controls=(
                    ScheduledControl(
                        report_index=1,
                        control=InjectorControl(
                            status=WellStatus.OPEN,
                            phase="GAS",
                            mode="RATE",
                            surface_rate=FieldSurfaceRate(value=87654.32109876543, unit="Mscf/day"),
                            bhp_psia=9500.0,
                        ),
                    ),
                    ScheduledControl(
                        report_index=2,
                        control=InjectorControl(
                            status=WellStatus.SHUT,
                            phase="GAS",
                            mode="BHP",
                            bhp_psia=9000.0,
                        ),
                    ),
                ),
            ),
        ),
    )
    child = value(case.service(case.export, injector).publish(request)).prepared.revision
    with case.imports.materialize(child.model) as materialized:
        deck, schedule = parsed(materialized.entrypoint)
        rows = [
            record
            for keyword in deck
            if keyword.name == "COMPDAT"
            for record in keyword
            if record[0].value == "PROD"
        ]
        for connection, row, exported in zip(
            schedule.get_well("PROD", 0).connections(), rows, case.export.connections, strict=True
        ):
            items = {item.name(): item for item in row}
            assert (
                items["CONNECTION_TRANSMISSIBILITY_FACTOR"].value == exported.compdat_factor_field
            )
            assert items["Kh"].value == exported.permeability_length_md_ft
            assert items["DIAMETER"].value == exported.diameter_ft
            assert items["SKIN"].value == exported.skin
            assert items["DIR"].value == exported.direction
            assert connection.cf == pytest.approx(
                items["CONNECTION_TRANSMISSIBILITY_FACTOR"].get_SI(0)
            )
            assert connection.kh == pytest.approx(items["Kh"].get_SI(0))
        assert schedule.get_injection_properties("INJ", 0)["surf_inj_rate"] == 100000.0
        assert schedule.get_injection_properties("INJ", 1)["surf_inj_rate"] == 87654.32109876543
        assert schedule.get_well("INJ", 2).status() == "SHUT"
        assert schedule.get_injection_properties("INJ", 2)["bhp_target"] == 9000.0


def test_high_precision_untouched_properties_and_fluid_tables_are_preserved(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    property_path = case.source / "includes/props.inc"
    property_path.write_text(property_path.read_text().replace("4017.55", "4017.551234567891"))
    grid_path = case.source / "includes/grid.inc"
    grid_path.write_text(grid_path.read_text().replace("PORO\n 0.3", "PORO\n 0.31234567890123456"))
    case.parent = value(
        case.imports.import_model(
            ImportRequest(
                session_id=case.parent.model.session_id,
                source_root=case.source,
                entrypoint="SPE1.DATA",
                datum=case.parent.coordinates.datum,
            )
        )
    ).prepared.revision
    case.export = completion(case.parent)
    child = value(case.service().publish(case.request())).prepared.revision
    with (
        case.imports.materialize(case.parent.model) as original,
        case.imports.materialize(child.model) as changed,
    ):
        before, _ = parsed(original.entrypoint)
        after, _ = parsed(changed.entrypoint)
        assert original.inspection.properties == changed.inspection.properties
        for original_item, changed_item in zip(before["PVTW"][0], after["PVTW"][0], strict=True):
            assert changed_item.get_raw_data_list() == pytest.approx(
                original_item.get_raw_data_list(), rel=4 * sys.float_info.epsilon, abs=0.0
            )
        assert after["PVTW"][0][0].get_raw_data_list()[0] == pytest.approx(
            4017.551234567891, rel=4 * sys.float_info.epsilon, abs=0.0
        )
        assert changed.inspection.properties.porosity[0] == 0.31234567890123456


def test_generated_reference_retains_fluids_and_original_generation_metadata(
    tmp_path: Path,
) -> None:
    from resinsight_mcp.models.synthetic import (
        SyntheticModelRequest,
        SyntheticModelService,
        read_grid_id,
        read_specification,
        reference_specification,
    )

    case = case_for(tmp_path)
    specification = reference_specification()
    generated = value(
        SyntheticModelService(case.store).create_model(
            SyntheticModelRequest(
                session_id=case.parent.model.session_id,
                datum=case.parent.coordinates.datum,
                specification=specification,
            )
        )
    )
    case.parent = generated.imported.prepared.revision
    case.export = completion(case.parent)
    child = value(case.service().publish(case.request())).prepared.revision
    with (
        case.imports.materialize(case.parent.model) as original,
        case.imports.materialize(child.model) as changed,
    ):
        before, parent_schedule = parsed(original.entrypoint)
        after, child_schedule = parsed(changed.entrypoint)
        for name in ("PVTW", "ROCK", "SWOF", "SGOF", "DENSITY", "PVDG", "PVTO", "EQUIL", "RSVD"):
            assert len(before[name]) == len(after[name])
            for left, right in zip(before[name], after[name], strict=True):
                for item_left, item_right in zip(left, right, strict=True):
                    if item_left.is_double():
                        assert item_right.get_raw_data_list() == pytest.approx(
                            item_left.get_raw_data_list(), rel=4 * sys.float_info.epsilon, abs=0.0
                        )
        assert changed.inspection.properties == original.inspection.properties
        assert changed.inspection.cell_depths_ft == original.inspection.cell_depths_ft
        assert [well_state(child_schedule, "INJ", report) for report in range(3)] == [
            well_state(parent_schedule, "INJ", report) for report in range(3)
        ]
        text = changed.entrypoint.read_text()
        assert read_specification(text) == specification
        assert read_grid_id(text) == generated.active_cells.grid_id
        assert "Parent comments describe the original inputs" in text
        assert "Replace requested completions from report zero: PROD controls at reports 0" in text
        assert "Copyright (C) 2015 Statoil" in text
        assert "http://opendatacommons.org/licenses/odbl/1.0/" in text
        assert "http://opendatacommons.org/licenses/dbcl/1.0/" in text
        assert (
            child_schedule.get_production_properties("PROD", 0)["bhp_target"] == 1200.1234567890123
        )


def test_native_default_reference_depth_uses_first_new_connection(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    case.export = case.export.model_copy(
        update={"wellhead": case.export.wellhead.model_copy(update={"reference_depth_ft": None})}
    )
    child = value(case.service().publish(case.request())).prepared.revision
    with case.imports.materialize(child.model) as materialized:
        deck, schedule = parsed(materialized.entrypoint)
        declaration = next(record for record in deck["WELSPECS"] if record[0].value == "PROD")
        assert {item.name(): item for item in declaration}["REF_DEPTH"].defaulted
        assert schedule.get_well("PROD", 0).pos()[2] / 0.3048 == pytest.approx(8335.0)


def test_native_roundoff_is_accepted_without_changing_exported_values(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    export = case.export
    perforation = export.modeled_well.definition.perforations[0].model_copy(
        update={"start_md_ft": 8326.0, "end_md_ft": 8424.0}
    )
    definition = export.modeled_well.definition.model_copy(update={"perforations": (perforation,)})
    actual_diameter = 0.49999999999999994
    actual_skin = 5e-7
    connections = (
        export.connections[0].model_copy(update={"start_md_ft": 8326.0 - 5e-7}),
        export.connections[1].model_copy(
            update={"diameter_ft": actual_diameter, "skin": actual_skin}
        ),
        export.connections[2].model_copy(update={"end_md_ft": 8424.0 + 5e-7}),
    )
    case.export = CompletionExport.model_validate(
        {
            **export.model_dump(),
            "modeled_well": export.modeled_well.model_copy(update={"definition": definition}),
            "connections": connections,
        }
    )
    child = value(case.service().publish(case.request())).prepared.revision
    with case.imports.materialize(child.model) as materialized:
        deck, schedule = parsed(materialized.entrypoint)
        rows = [
            record
            for keyword in deck
            if keyword.name == "COMPDAT"
            for record in keyword
            if record[0].value == "PROD"
        ]
        middle = {item.name(): item for item in rows[1]}
        assert middle["DIAMETER"].get_raw_data_list()[0] == actual_diameter
        assert middle["SKIN"].get_raw_data_list()[0] == pytest.approx(
            actual_skin, rel=4 * sys.float_info.epsilon, abs=0.0
        )
        assert [connection.pos for connection in schedule.get_well("PROD", 0).connections()] == [
            (4, 4, layer) for layer in range(3)
        ]
    assert value(case.store.get_revision(case.parent.model)) == case.parent
