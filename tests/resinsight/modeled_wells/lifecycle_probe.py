"""Verify persistent FIELD wells through native save, reopen, and service reconnection."""

import argparse
import json
import math
import shutil
import subprocess
from importlib.metadata import distribution, version
from pathlib import Path
from typing import Any, cast

import psutil
import rips
from google.protobuf.json_format import MessageToDict
from opm.io.ecl import EclFile

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    CloseAction,
    CloseRequest,
    LaunchRequest,
    ObjectKind,
    ProjectCloseRequest,
    ProjectOpenRequest,
    ProjectSaveRequest,
)
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.models.wells.records import (
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCase,
    PreparedCaseReceipt,
    PreparedCaseRequest,
    PreparedCaseRestoreRequest,
    TrajectoryPoint,
    WellAdoptRequest,
    WellCreateRequest,
    WellExportRequest,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.wells import ResInsightWellService, RipsWellBackend
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .input_probe import Evidence, inspect_case, value
from .service_probe import configure_snapshot


def record(evidence: Evidence, label: str, payload: Any) -> None:
    (evidence.output / f"{label}.json").write_text(json.dumps(payload, indent=2) + "\n")
    evidence.record(label, file=f"{label}.json")


def reject_exports(
    instance: Any, imports: OpmImportService, model: Any, evidence: Evidence
) -> None:
    cases = tuple(case.id for case in instance.project.cases())
    with imports.materialize(model) as materialized:
        for label, old, new in (("parser", "RUNSPEC", "NOTAKEYWORD"), ("units", "FIELD", "METRIC")):
            root = Path(shutil.copytree(materialized.directory, evidence.output / label))
            entrypoint = root / materialized.entrypoint.name
            entrypoint.write_text(entrypoint.read_text().replace(old, new))
            request = {"path": str(entrypoint), "output_path": str(root / "rejected.EGRID")}
            try:
                instance.project.export_prepared_input_grid(**request)
            except rips.RipsError as error:
                evidence.check(
                    f"reject_{label}",
                    tuple(case.id for case in instance.project.cases()) == cases,
                    request=request,
                    error=str(error),
                )
            else:
                evidence.check(f"reject_{label}", False)
        grid = evidence.output / "existing.EGRID"
        request = {"path": str(materialized.entrypoint), "output_path": str(grid)}
        instance.project.export_prepared_input_grid(**request)
        before = list(EclFile(str(grid))["GRIDUNIT"])
        try:
            instance.project.export_prepared_input_grid(**request)
        except rips.RipsError as error:
            evidence.check(
                "reject_existing_export",
                tuple(case.id for case in instance.project.cases()) == cases
                and list(EclFile(str(grid))["GRIDUNIT"]) == before,
                request=request,
                error=str(error),
            )
        else:
            evidence.check("reject_existing_export", False)


def readback(
    sessions: ResInsightSessionService,
    imports: OpmImportService,
    store: SqliteWorkspaceStore,
    binding: PreparedCase,
    evidence: Evidence,
    label: str,
) -> dict[str, Any]:
    with store.open_artifact(binding.receipt) as stream:
        receipt = PreparedCaseReceipt.model_validate_json(stream.read())
    materialized = imports.reopen_persistent(binding.model, receipt.directory)
    grid_units = list(EclFile(str(receipt.directory / "grid.EGRID"))["GRIDUNIT"])
    evidence.check(f"{label}_field_grid", grid_units[0].strip() == "FEET", units=grid_units)
    with sessions.access_objects((binding.case,)) as access:
        application = cast(RipsApplication, access.application)

        def inspect() -> dict[str, Any]:
            case: Any = next(
                case
                for case in application.project().cases()
                if str(case.address()) == access.objects[0].address
            )
            inspect_case(case, materialized, evidence)
            return {
                "path": case.file_path,
                "case_id": case.id,
                "centers": [MessageToDict(item) for item in case.grid().cell_centers()],
                "corners": [MessageToDict(item) for item in case.grid().cell_corners()],
                "active": [MessageToDict(item) for item in case.cell_info_for_active_cells()],
                "properties": {
                    name: case.active_cell_property(
                        "STATIC_NATIVE" if name in {"DX", "DY", "DZ"} else "INPUT_PROPERTY",
                        name,
                        0,
                    )
                    for name, _ in materialized.inspection.properties.keyword_arrays()
                },
                "views": [view.id for view in case.views()],
            }

        actual = application.call(inspect)
    record(evidence, label, actual)
    record(evidence, f"{label}-receipt", receipt.model_dump(mode="json"))
    return actual


def capture(access: ApplicationAccess, evidence: Evidence) -> None:
    application = cast(RipsApplication, access.application)

    def snapshot() -> None:
        case = application.project().cases()[0]
        view = configure_snapshot(case, evidence)
        view.export_snapshot(
            prefix="restored", export_folder=str(evidence.output), width=1000, height=800
        )

    application.call(snapshot, mutation=True)


def run(executable: Path, source: Path, evidence: Evidence) -> None:
    output = evidence.output
    store = SqliteWorkspaceStore.create(output / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="P09 lifetime")))
    imports = OpmImportService(store)
    imported = value(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=source,
                entrypoint="SPE1.DATA",
                datum="SPE1 local datum",
            )
        )
    )
    sessions = ResInsightSessionService(store, RipsApplicationFactory(output / "client-logs"))
    wells = ResInsightWellService(
        store, sessions, imports, RipsWellBackend(), source_root=output / "native-sources"
    )
    launch = LaunchRequest(session_id=session.session_id, executable=executable)
    record(evidence, "launch-request", launch.model_dump(mode="json"))
    owned = value(sessions.launch(launch))
    assert owned.process is not None
    record(evidence, "owned-connection", owned.model_dump(mode="json"))
    evidence.record(
        "native_command",
        command=psutil.Process(owned.process.pid).cmdline(),
        executable=str(executable),
    )
    try:
        instance = rips.Instance(port=owned.endpoint.port)
        reject_exports(instance, imports, imported.prepared.revision.model, evidence)
        load = PreparedCaseRequest(context=owned.context, model=imported.prepared.revision.model)
        record(evidence, "load-request", load.model_dump(mode="json"))
        binding = value(wells.load(load))
        before = readback(sessions, imports, store, binding, evidence, "before")
        evidence.check("working_view_created", len(before["views"]) == 1)
        definition = ModeledWellDefinition(
            name="PROD",
            coordinates=imported.prepared.revision.coordinates,
            targets=tuple(
                TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=depth)
                for depth in (0.0, 8325.0, 8430.0)
            ),
            perforations=(
                PerforationInterval(start_md_ft=8326.0, end_md_ft=8424.0, diameter_ft=0.5),
            ),
        )
        create = WellCreateRequest(binding=binding, definition=definition)
        record(evidence, "create-request", create.model_dump(mode="json"))
        created = value(wells.create(create))
        record(evidence, "created", created.model_dump(mode="json"))
        exported = value(wells.export(WellExportRequest(well=created.well, expected_version=0)))
        record(evidence, "export-before", exported.model_dump(mode="json"))
        saved = value(
            sessions.save_project(
                ProjectSaveRequest(context=created.well.context, path=output / "saved-project.rsp")
            )
        )
        value(wells.close())
        closed = value(sessions.close_project(ProjectCloseRequest(context=saved.context)))
        reopened = value(
            sessions.open_project(
                ProjectOpenRequest(context=closed.context, path=output / "saved-project.rsp")
            )
        )
        record(evidence, "reopened-project", reopened.model_dump(mode="json"))
        value(
            sessions.close(
                CloseRequest(
                    session_id=session.session_id, connection_id=owned.context.connection_id
                )
            )
        )
        store = SqliteWorkspaceStore.open(output / "workspace")
        imports = OpmImportService(store)
        sessions = ResInsightSessionService(
            store, RipsApplicationFactory(output / "restored-client-logs")
        )
        current = value(
            sessions.attach(AttachRequest(session_id=session.session_id, endpoint=owned.endpoint))
        )
        evidence.check("same_owned_process", current.process == owned.process)
        wells = ResInsightWellService(
            store, sessions, imports, RipsWellBackend(), source_root=output / "native-sources"
        )
        project = value(sessions.inspect_project(session.session_id))
        case = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.CASE)
        well = next(
            item.ref
            for item in project.objects
            if item.ref.kind == ObjectKind.WELL and item.name == "PROD"
        )
        restore = PreparedCaseRestoreRequest(
            model=binding.model, case=case, receipt=binding.receipt
        )
        record(evidence, "restore-request", restore.model_dump(mode="json"))
        restored = value(wells.restore_case(restore))
        after = readback(sessions, imports, store, restored, evidence, "after")
        evidence.check(
            "saved_model_readback_matches",
            all(
                after[key] == before[key]
                for key in ("path", "centers", "corners", "active", "properties")
            ),
        )
        adopt = WellAdoptRequest(
            binding=restored,
            well=well,
            definition=created.definition,
            trajectory=created.trajectory,
        )
        record(evidence, "adopt-request", adopt.model_dump(mode="json"))
        adopted = value(wells.adopt_well(adopt))
        record(evidence, "adopted", adopted.model_dump(mode="json"))
        evidence.check(
            "new_well_lifetime",
            adopted.version == 0
            and adopted.well.context.connection_id != created.well.context.connection_id
            and adopted.well.context.project_generation > well.context.project_generation,
        )
        evidence.check(
            "old_reference_rejected", isinstance(wells.inspect(created.well).outcome, Failure)
        )
        evidence.check(
            "durable_export_retrieved", value(wells.get_export(exported.artifact)) == exported
        )
        repeated = value(wells.export(WellExportRequest(well=adopted.well, expected_version=0)))
        record(evidence, "export-after", repeated.model_dump(mode="json"))
        evidence.check(
            "completion_identity",
            repeated.wellhead == exported.wellhead and repeated.connections == exported.connections,
        )
        evidence.check(
            "reference_completion_factors",
            len(repeated.connections) == 3
            and all(
                connection.cell.i == connection.cell.j == 4
                and connection.cell.k == index
                and math.isclose(connection.compdat_factor_field, factor, rel_tol=1e-6)
                for index, (connection, factor) in enumerate(
                    zip(
                        repeated.connections,
                        (10.078780273272798, 1.5913863589378099, 10.397057545060358),
                        strict=True,
                    )
                )
            ),
        )
        sessions.mutate_project(adopted.well.context, lambda access: capture(access, evidence))
        evidence.check("snapshot_created", len(tuple(output.glob("restored*.png"))) == 1)
    except BaseException as error:
        evidence.record("probe_error", error=repr(error))
        raise
    finally:
        current = value(sessions.get_connection(session.session_id))
        evidence.check("cleanup_identity", current.process == owned.process)
        cleanup = sessions.close(
            CloseRequest(
                session_id=session.session_id,
                connection_id=current.context.connection_id,
                action=CloseAction.TERMINATE,
            ),
            attached_termination_authorized=True,
        )
        record(evidence, "cleanup", cleanup.model_dump(mode="json"))
        value(cleanup)
        value(wells.close())
        evidence.check("owned_process_absent", not psutil.pid_exists(owned.process.pid))


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
    record(
        evidence,
        "versions",
        {
            "repository_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "native_commit": arguments.native_commit,
            "versions": {
                name: version(name)
                for name in ("resinsight-mcp", "rips", "opm", "grpcio", "protobuf")
            },
            "rips_file": rips.__file__,
            "rips_install": json.loads(distribution("rips").read_text("direct_url.json") or "null"),
        },
    )
    run(arguments.executable.resolve(strict=True), arguments.source.resolve(strict=True), evidence)


if __name__ == "__main__":
    main()
