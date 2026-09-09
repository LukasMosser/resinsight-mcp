"""Exercise the maintained modeled well service in one owned native process."""

import argparse
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol, cast

import opm.io.deck  # noqa: F401
import psutil
import rips
from google.protobuf.json_format import MessageToDict
from opm.io.ecl_state import EclipseState
from opm.io.parser import Parser
from opm.io.schedule import Schedule
from PIL import Image

from resinsight_mcp.contracts.errors import ErrorCode, Failure, MutationEffect
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.observations import Camera, Projection
from resinsight_mcp.contracts.sessions import AttachRequest, CloseRequest, Endpoint
from resinsight_mcp.contracts.wells import ProducerControl, WellStatus
from resinsight_mcp.models.imports import (
    ImportReceipt,
    ImportRequest,
    MaterializedModel,
    OpmImportService,
)
from resinsight_mcp.models.wells.records import (
    CompletionExport,
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCaseRequest,
    ScheduledControl,
    ScheduledWell,
    TrajectoryPoint,
    WellCreateRequest,
    WellExportRequest,
    WellScheduleRequest,
    WellUpdateRequest,
)
from resinsight_mcp.models.wells.service import OpmWellScheduleService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.views._camera import read_camera, view_matrix
from resinsight_mcp.resinsight.wells import ResInsightWellService, RipsWellBackend
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .input_probe import Evidence, inspect_case, value


class View(Protocol):
    def address(self) -> int: ...
    def export_snapshot(self, prefix: str, export_folder: str, width: int, height: int) -> None: ...


class DisplayCase(Protocol):
    def address(self) -> int: ...
    def create_view(self) -> View: ...


class DisplayProject(Protocol):
    def cases(self) -> list[DisplayCase]: ...
    def save(self, path: str) -> None: ...


def configure_snapshot(case: Any, evidence: Evidence) -> Any:
    case.name_setting = "CUSTOM_NAME"
    case.name = "P09 PROD J5 slice PERMX (mD)"
    case.update()
    view = case.create_view()
    view.apply_cell_result("INPUT_PROPERTY", "PERMX")
    view.grid_z_scale = 20
    view.disable_lighting = True
    view.show_grid_box = True
    view.update()
    collection = view.range_filters()
    collection.active = True
    collection.combine_filter_mode = "AND"
    collection.update()
    section = collection.add_new_object(rips.CellRangeFilter, "CellFilters")
    section.name = "PROD row J=5"
    section.is_checked = True
    section.grid_index = 0
    section.filter_type = "INCLUDE"
    section.start_index_i, section.start_index_j, section.start_index_k = 1, 5, 1
    section.cell_count_i, section.cell_count_j, section.cell_count_k = 10, 1, 3
    section.update()
    view = case.view(view.id)
    legends = [
        item
        for item in view.cell_result().result_var_legend_definition_list()
        if item.result_variable_usage == "PERMX"
    ]
    if len(legends) != 1:
        raise RuntimeError("The snapshot requires one PERMX legend.")
    legend = legends[0]
    legend.range_type = "USER_DEFINED_MAX_MIN"
    legend.mapping_mode = "LinearContinuous"
    legend.user_defined_min = 50
    legend.user_defined_max = 500
    legend.update()
    camera = Camera(
        position=(16000, -16000, 14000),
        target=(0, -500, 0),
        up=(0, 0, 1),
        projection=Projection.ORTHOGRAPHIC,
        parallel_scale=6000,
    )
    view.set_camera_projection(
        perspective=False, field_of_view_y_degrees=40, parallel_projection_height=12000
    )
    view = case.view(view.id)
    view.camera_point_of_interest = list(camera.target)
    view.camera_matrix = view_matrix(camera)
    view.update()
    view = case.view(view.id)
    observed = read_camera(
        view.camera_matrix,
        view.camera_point_of_interest,
        view.perspective_projection,
        view.actual_camera_field_of_view_y_degrees,
        view.actual_camera_parallel_projection_height,
    )
    evidence.check(
        "snapshot_camera",
        math.dist(observed.position, camera.position) < 1e-6
        and math.dist(observed.target, camera.target) < 1e-6
        and observed.projection == camera.projection
        and observed.parallel_scale is not None
        and math.isclose(observed.parallel_scale, 6000, abs_tol=1e-6),
        requested=camera.model_dump(mode="json"),
        observed=observed.model_dump(mode="json"),
    )
    sections = view.range_filters().cell_filters()
    evidence.check(
        "snapshot_slice",
        len(sections) == 1
        and view.range_filters().active
        and sections[0].is_checked
        and sections[0].filter_type == "INCLUDE"
        and sections[0].grid_index == 0
        and (sections[0].start_index_i, sections[0].start_index_j, sections[0].start_index_k)
        == (1, 5, 1)
        and (sections[0].cell_count_i, sections[0].cell_count_j, sections[0].cell_count_k)
        == (10, 1, 3),
        one_based_start=[1, 5, 1],
        counts=[10, 1, 3],
    )
    evidence.check(
        "snapshot_property",
        view.cell_result().result_type == "INPUT_PROPERTY"
        and view.cell_result().result_variable == "PERMX"
        and view.grid_z_scale == 20
        and view.disable_lighting,
        property="PERMX",
        unit="mD",
        legend=[50, 500],
        vertical_exaggeration=20,
    )
    legend = next(
        item
        for item in view.cell_result().result_var_legend_definition_list()
        if item.result_variable_usage == "PERMX"
    )
    evidence.check(
        "snapshot_legend",
        math.isclose(legend.actual_minimum, 50, abs_tol=1e-6)
        and math.isclose(legend.actual_maximum, 500, abs_tol=1e-6),
        minimum=legend.actual_minimum,
        maximum=legend.actual_maximum,
    )
    return view


def snapshot(access: ApplicationAccess, case_address: str, evidence: Evidence) -> int:
    application = cast(RipsApplication, access.application)
    output = evidence.output

    def capture() -> int:
        project = cast(DisplayProject, application.project())
        case = next(item for item in project.cases() if str(item.address()) == case_address)
        view = configure_snapshot(case, evidence)
        view.export_snapshot(prefix="service", export_folder=str(output), width=1000, height=800)
        project.save(str(output / "service-project.rsp"))
        return view.address()

    return application.call(capture, mutation=True)


def item_values(item: Any) -> tuple[Any, ...]:
    if len(item) == 1 and item.defaulted:
        return (None,)
    if item.is_double():
        return tuple(item.get_raw_data_list())
    if item.is_int():
        return tuple(item.get_int(index) for index in range(len(item)))
    if item.is_string():
        return tuple(item.get_str(index) for index in range(len(item)))
    if item.is_uda():
        return tuple(item.get_uda(index).value for index in range(len(item)))
    if len(item) == 0:
        return ()
    raise RuntimeError("The parsed parent has an unsupported OPM item type.")


def deck_semantics(path: Path) -> tuple[Any, ...]:
    deck = Parser().parse(str(path))
    return tuple(
        (
            keyword.name,
            tuple(tuple((item.name(), item_values(item)) for item in record) for record in keyword),
        )
        for keyword in deck
    )


def prepared_readback(
    access: ApplicationAccess, model: MaterializedModel, evidence: Evidence
) -> None:
    application = cast(RipsApplication, access.application)

    def read() -> None:
        project = cast(Any, application.project())
        case = next(
            case for case in project.cases() if str(case.address()) == access.objects[0].address
        )
        inspect_case(case, model, evidence)
        grid = case.grid()
        evidence.record(
            "native_prepared_readback",
            dimensions=MessageToDict(grid.dimensions()),
            centers=[MessageToDict(item) for item in grid.cell_centers()],
            corners=[MessageToDict(item) for item in grid.cell_corners()],
            volumes_ft3=case.active_cell_property("STATIC_NATIVE", "riCELLVOLUME", 0),
            properties={
                name: case.active_cell_property(
                    "STATIC_NATIVE" if name in {"DX", "DY", "DZ"} else "INPUT_PROPERTY", name, 0
                )
                for name, _ in model.inspection.properties.keyword_arrays()
            },
            expected=model.inspection.model_dump(mode="json"),
        )

    application.call(read, mutation=False)


def injector_state(schedule: Any, report: int) -> tuple[Any, ...]:
    well = schedule.get_well("INJ", report)
    return (
        well.pos(),
        well.status(),
        well.preferred_phase,
        well.group(),
        schedule.get_injection_properties("INJ", report),
        tuple((row.pos, row.cf, row.kh, row.state) for row in well.connections()),
    )


def producer_controls(deck: Any) -> list[tuple[int, str, str]]:
    report = 0
    controls = []
    for keyword in deck:
        if keyword.name == "TSTEP":
            report += len(keyword[0][0])
        if keyword.name == "WCONPROD":
            controls.extend(
                (report, row[1].value, row[2].value) for row in keyword if row[0].value == "PROD"
            )
    return controls


def check_connections(
    deck: Any,
    schedule: Any,
    exported: CompletionExport,
    default_depth_ft: float,
    evidence: Evidence,
) -> None:
    rows = [
        record
        for keyword in deck
        if keyword.name == "COMPDAT"
        for record in keyword
        if record[0].value == "PROD"
    ]
    table = []
    readable = [
        "# Native completion values and parsed child values\n",
        "Cells use zero-based indices. Factors use cP·stb/(day·psia).\n",
        "| Cell | Native factor | Parsed factor | Native Kh (mD ft) | Parsed Kh (mD ft) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row, native in zip(rows, exported.connections, strict=True):
        items = {item.name(): item for item in row}
        raw = {
            name: items[name].get_raw_data_list()[0]
            for name in ("CONNECTION_TRANSMISSIBILITY_FACTOR", "Kh", "DIAMETER", "SKIN")
        }
        evidence.check(
            "parsed_native_completion",
            all(
                math.isclose(raw[name], expected, rel_tol=4 * sys.float_info.epsilon, abs_tol=0.0)
                for name, expected in (
                    ("CONNECTION_TRANSMISSIBILITY_FACTOR", native.compdat_factor_field),
                    ("Kh", native.permeability_length_md_ft),
                    ("DIAMETER", native.diameter_ft),
                    ("SKIN", native.skin),
                )
            )
            and items["DIR"].value == native.direction,
            cell=native.cell.model_dump(mode="json"),
        )
        table.append(
            {
                "cell": native.cell.model_dump(mode="json"),
                "native_factor_field": native.compdat_factor_field,
                "parsed_factor_field": raw["CONNECTION_TRANSMISSIBILITY_FACTOR"],
                "native_kh_md_ft": native.permeability_length_md_ft,
                "parsed_kh_md_ft": raw["Kh"],
            }
        )
        readable.append(
            f"| ({native.cell.i}, {native.cell.j}, {native.cell.k}) "
            f"| {native.compdat_factor_field:.16g} "
            f"| {raw['CONNECTION_TRANSMISSIBILITY_FACTOR']:.16g} "
            f"| {native.permeability_length_md_ft:.16g} | {raw['Kh']:.16g} |"
        )
    reference_depth_ft = exported.wellhead.reference_depth_ft
    if reference_depth_ft is None:
        reference_depth_ft = default_depth_ft
        heads = [
            record
            for keyword in deck
            if keyword.name == "WELSPECS"
            for record in keyword
            if record[0].value == "PROD"
        ]
        evidence.check("defaulted_reference_depth", all(record[4].defaulted for record in heads))
    for report in range(len(schedule.reportsteps)):
        well = schedule.get_well("PROD", report)
        evidence.check(
            "parsed_connection_cells",
            [row.pos for row in schedule.get_well("PROD", report).connections()]
            == [(row.cell.i, row.cell.j, row.cell.k) for row in exported.connections],
            report=report,
        )
        evidence.check(
            "parsed_wellhead",
            well.pos()[:2] == (exported.wellhead.i, exported.wellhead.j)
            and math.isclose(well.pos()[2], reference_depth_ft * 0.3048, rel_tol=1e-12),
            report=report,
        )
        for connection, row in zip(well.connections(), rows, strict=True):
            items = {item.name(): item for item in row}
            evidence.check(
                "schedule_connection_values",
                math.isclose(
                    connection.cf,
                    items["CONNECTION_TRANSMISSIBILITY_FACTOR"].get_SI(0),
                    rel_tol=1e-12,
                )
                and math.isclose(connection.kh, items["Kh"].get_SI(0), rel_tol=1e-12),
                report=report,
            )
    evidence.record("native_to_schedule_connections", rows=table)
    (evidence.output / "connections.md").write_text("\n".join(readable) + "\n")


def check_schedule(
    store: SqliteWorkspaceStore,
    imports: OpmImportService,
    wells: ResInsightWellService,
    receipt: ImportReceipt,
    exported: CompletionExport,
    evidence: Evidence,
) -> None:
    parent = receipt.prepared.revision
    with imports.materialize(parent.model) as before:
        original_semantics = deck_semantics(before.entrypoint)
    published = value(
        OpmWellScheduleService(imports, wells).publish(
            WellScheduleRequest(
                parent=parent.model,
                wells=(
                    ScheduledWell(
                        export=exported.artifact,
                        controls=(
                            ScheduledControl(
                                report_index=1,
                                control=ProducerControl(
                                    status=WellStatus.OPEN, mode="BHP", bhp_psia=1200.1234567890123
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )
    )
    child = published.prepared.revision
    (evidence.output / "schedule-receipt.json").write_text(
        published.model_dump_json(indent=2) + "\n"
    )
    evidence.check(
        "exact_parent_lineage",
        child.parent == parent.model
        and child.model != parent.model
        and child.coordinates == parent.coordinates,
    )
    evidence.check("immutable_parent_record", value(store.get_revision(parent.model)) == parent)
    with imports.materialize(parent.model) as original, imports.materialize(child.model) as changed:
        evidence.check(
            "immutable_parent_semantics", deck_semantics(original.entrypoint) == original_semantics
        )
        parent_deck = Parser().parse(str(original.entrypoint))
        parent_schedule = Schedule(parent_deck, EclipseState(parent_deck))
        deck = Parser().parse(str(changed.entrypoint))
        schedule = Schedule(deck, EclipseState(deck))
        evidence.check(
            "retained_parent_model",
            changed.inspection.properties == original.inspection.properties
            and changed.inspection.cell_depths_ft == original.inspection.cell_depths_ft
            and changed.inspection.cell_volumes_ft3 == original.inspection.cell_volumes_ft3,
        )
        evidence.check("retained_report_dates", schedule.reportsteps == parent_schedule.reportsteps)
        evidence.check(
            "retained_injector_events",
            [injector_state(schedule, report) for report in range(len(schedule.reportsteps))]
            == [
                injector_state(parent_schedule, report)
                for report in range(len(parent_schedule.reportsteps))
            ],
        )
        evidence.check(
            "retained_initial_producer_control",
            schedule.get_production_properties("PROD", 0)
            == parent_schedule.get_production_properties("PROD", 0),
        )
        evidence.check(
            "published_producer_control",
            schedule.get_production_properties("PROD", 1)["bhp_target"] == 1200.1234567890123,
        )
        first = exported.connections[0].cell
        ni, nj, _ = changed.inspection.summary.dimensions
        default_depth_ft = changed.inspection.cell_depths_ft[
            first.k * ni * nj + first.j * ni + first.i
        ]
        check_connections(deck, schedule, exported, default_depth_ft, evidence)
        evidence.check(
            "retained_published_control",
            schedule.get_production_properties("PROD", 2)["bhp_target"] == 1200.1234567890123,
        )
        overlays = [
            record
            for keyword in deck
            if keyword.name == "WCONPROD"
            for record in keyword
            if record[0].value == "PROD" and record[2].value == "BHP"
        ]
        evidence.check(
            "published_open_bhp_mode",
            len(overlays) == 1
            and overlays[0][1].value == "OPEN"
            and schedule.get_well("PROD", 1).status() == "OPEN"
            and schedule.get_well("PROD", 2).status() == "OPEN",
        )
        control_trace = producer_controls(deck)
        evidence.check(
            "overlay_control_report", (1, "OPEN", "BHP") in control_trace, controls=control_trace
        )


def check_service(executable: Path, source: Path, evidence: Evidence) -> None:
    output = evidence.output
    store = SqliteWorkspaceStore.create(output / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="P09 service")))
    imports = OpmImportService(store)
    receipt = value(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=source,
                entrypoint="SPE1.DATA",
                datum="SPE1 local datum",
            )
        )
    )
    (output / "import-receipt.json").write_text(receipt.model_dump_json(indent=2) + "\n")
    sessions = ResInsightSessionService(store, RipsApplicationFactory(output / "client-logs"))
    wells = ResInsightWellService(store, sessions, imports, RipsWellBackend())
    command = [str(executable), "--server", "0", "--portnumberfile", str(output / "port.txt")]
    evidence.record(
        "command",
        command=command,
        environment={
            key: os.environ.get(key) for key in ("LC_ALL", "QT_PLUGIN_PATH", "PYTHONPATH")
        },
    )
    connection = None
    with (output / "application.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        identity = psutil.Process(process.pid).create_time()
        evidence.record("owned_process", pid=process.pid, start_marker=identity)
        try:
            deadline = time.monotonic() + 45
            while not (output / "port.txt").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("The owned application did not publish its port.")
                time.sleep(0.1)
            endpoint = Endpoint(port=int((output / "port.txt").read_text()))
            connection = value(
                sessions.attach(AttachRequest(session_id=session.session_id, endpoint=endpoint))
            )
            evidence.record("connection", data=connection.model_dump(mode="json"))
            evidence.check(
                "attached_owned_process",
                connection.process is not None
                and connection.process.pid == process.pid
                and connection.process.start_marker == str(identity),
            )
            native_process = psutil.Process(process.pid)
            evidence.check(
                "owned_executable",
                Path(native_process.exe()).resolve() == executable
                and native_process.cmdline() == command,
            )
            binding = value(
                wells.load(
                    PreparedCaseRequest(
                        context=connection.context, model=receipt.prepared.revision.model
                    )
                )
            )
            evidence.record("prepared_case", data=binding.model_dump(mode="json"))
            with (
                imports.materialize(binding.model) as model,
                sessions.access_objects((binding.case,)) as access,
            ):
                prepared_readback(access, model, evidence)
            definition = ModeledWellDefinition(
                name="PROD",
                coordinates=receipt.prepared.revision.coordinates,
                targets=tuple(
                    TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=depth)
                    for depth in (0.0, 8325.0, 8430.0)
                ),
                perforations=(
                    PerforationInterval(start_md_ft=8326.0, end_md_ft=8424.0, diameter_ft=0.5),
                ),
            )
            created = value(wells.create(WellCreateRequest(binding=binding, definition=definition)))
            evidence.record("created_well", data=created.model_dump(mode="json"))
            evidence.check(
                "positive_down_trajectory",
                math.isclose(created.trajectory[-1].depth_ft, 8430.0, abs_tol=1e-3),
            )
            exported = value(wells.export(WellExportRequest(well=created.well, expected_version=0)))
            (output / "completion-export.json").write_text(
                exported.model_dump_json(indent=2) + "\n"
            )
            evidence.check(
                "fixed_model_export",
                exported.modeled_well.binding.model == receipt.prepared.revision.model,
            )
            reference = {0: 10.078780273272798, 1: 1.5913863589378099, 2: 10.397057545060358}
            evidence.check(
                "active_connections",
                {(row.cell.i, row.cell.j, row.cell.k) for row in exported.connections}
                == {(4, 4, 0), (4, 4, 1), (4, 4, 2)},
            )
            for row in exported.connections:
                evidence.check(
                    "field_connection_factor",
                    math.isclose(row.compdat_factor_field, reference[row.cell.k], rel_tol=1e-6),
                    k=row.cell.k,
                    factor=row.compdat_factor_field,
                )
                evidence.check(
                    "reference_permeability_length",
                    math.isclose(
                        row.permeability_length_md_ft,
                        {0: 9500.0, 1: 1500.0, 2: 9800.0}[row.cell.k],
                        rel_tol=1e-6,
                    ),
                    k=row.cell.k,
                    kh_md_ft=row.permeability_length_md_ft,
                )
            changed = ModeledWellDefinition.model_validate(
                {
                    **definition.model_dump(),
                    "targets": (
                        *definition.targets[:-1],
                        TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=8450.0),
                    ),
                }
            )
            updated = value(
                wells.update(
                    WellUpdateRequest(well=created.well, expected_version=0, definition=changed)
                )
            )
            evidence.record("updated_well", data=updated.model_dump(mode="json"))
            evidence.check(
                "updated_trajectory",
                updated.version == 1
                and math.isclose(updated.trajectory[-1].depth_ft, 8450.0, abs_tol=1e-3),
            )
            evidence.check(
                "immutable_export", value(wells.get_export(exported.artifact)) == exported
            )
            check_schedule(store, imports, wells, receipt, exported, evidence)
            stale = wells.export(WellExportRequest(well=updated.well, expected_version=0))
            evidence.check(
                "stale_version",
                isinstance(stale.outcome, Failure)
                and stale.outcome.error.code == ErrorCode.STALE_OBJECT,
            )
            outside = ModeledWellDefinition.model_validate(
                {
                    **definition.model_dump(),
                    "name": "INJ",
                    "targets": tuple(
                        TrajectoryPoint(x_ft=20000.0, y_ft=20000.0, depth_ft=target.depth_ft)
                        for target in definition.targets
                    ),
                }
            )
            invalid = value(
                wells.create(WellCreateRequest(binding=updated.binding, definition=outside))
            )
            rejected = wells.export(WellExportRequest(well=invalid.well, expected_version=0))
            evidence.check(
                "rejected_empty_completion",
                isinstance(rejected.outcome, Failure)
                and rejected.outcome.error.code == ErrorCode.INVALID_MODEL
                and rejected.outcome.error.effect == MutationEffect.NOT_APPLIED,
                result=rejected.model_dump(mode="json"),
            )
            project = value(sessions.inspect_project(session.session_id))
            with sessions.access_objects((invalid.binding.case,)) as access:
                case_address = access.objects[0].address
            captured = sessions.mutate_project(
                project.context, lambda access: snapshot(access, case_address, evidence)
            )
            evidence.record(
                "snapshot_project", data=captured.access.project.model_dump(mode="json")
            )
            images = tuple(output.glob("service*.png"))
            evidence.check("snapshot_exists", len(images) == 1)
            with Image.open(images[0]) as picture:
                picture.load()
                evidence.check("snapshot_dimensions", picture.size == (1000, 800))
            references = {
                native.address: issued.ref
                for native, issued in zip(
                    captured.access.objects, captured.access.project.objects, strict=True
                )
            }
            evidence.record(
                "snapshot_provenance",
                image=images[0].name,
                view_address=captured.value,
                case_address=case_address,
                view=references[str(captured.value)].model_dump(mode="json"),
                case=references[case_address].model_dump(mode="json"),
                model=updated.binding.model.model_dump(mode="json"),
                displayed_well_version=updated.version,
                exported_well_version=exported.modeled_well.version,
            )
        except BaseException as error:
            evidence.record("probe_error", error=repr(error))
            raise
        finally:
            detached = None
            if connection is not None:
                detached = sessions.close(
                    CloseRequest(
                        session_id=session.session_id,
                        connection_id=connection.context.connection_id,
                    )
                )
                evidence.record(
                    "detached",
                    result=detached.model_dump(mode="json"),
                )
            if process.poll() is None:
                if psutil.Process(process.pid).create_time() != identity:
                    raise RuntimeError("The owned native process identity changed.")
                process.terminate()
                process.wait(timeout=20)
            evidence.record(
                "cleanup",
                pid=process.pid,
                exit_code=process.returncode,
                alive=psutil.pid_exists(process.pid),
            )
            closed = wells.close()
            evidence.record("source_cleanup", result=closed.model_dump(mode="json"))
            if isinstance(closed.outcome, Failure):
                raise RuntimeError(closed.outcome.error.message)
            evidence.check("owned_process_exited", process.poll() is not None)
            if detached is not None:
                evidence.check("detached_successfully", not isinstance(detached.outcome, Failure))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(exist_ok=False)
    evidence = Evidence(output)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    evidence.record("versions", repository_commit=commit, native_commit=arguments.native_commit)
    check_service(
        arguments.executable.resolve(strict=True), arguments.source.resolve(strict=True), evidence
    )


if __name__ == "__main__":
    main()
