"""Exercise the maintained modeled well service in one owned native process."""

import argparse
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Protocol, cast

import psutil

from resinsight_mcp.contracts.errors import ErrorCode, Failure, MutationEffect
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import AttachRequest, CloseRequest, Endpoint
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.models.wells.records import (
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCaseRequest,
    TrajectoryPoint,
    WellCreateRequest,
    WellExportRequest,
    WellUpdateRequest,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.wells import ResInsightWellService, RipsWellBackend
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .input_probe import Evidence, value


class View(Protocol):
    def export_snapshot(self, prefix: str, export_folder: str, width: int, height: int) -> None: ...


class DisplayCase(Protocol):
    def address(self) -> int: ...
    def create_view(self) -> View: ...


class DisplayProject(Protocol):
    def cases(self) -> list[DisplayCase]: ...
    def save(self, path: str) -> None: ...


def snapshot(access: ApplicationAccess, case_address: str, output: Path) -> None:
    application = cast(RipsApplication, access.application)

    def capture() -> None:
        project = cast(DisplayProject, application.project())
        case = next(item for item in project.cases() if str(item.address()) == case_address)
        view = case.create_view()
        view.export_snapshot(prefix="service", export_folder=str(output), width=1000, height=800)
        project.save(str(output / "service-project.rsp"))

    application.call(capture, mutation=True)


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
            binding = value(
                wells.load(
                    PreparedCaseRequest(
                        context=connection.context, model=receipt.prepared.revision.model
                    )
                )
            )
            evidence.record("prepared_case", data=binding.model_dump(mode="json"))
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
            sessions.mutate_project(
                project.context, lambda access: snapshot(access, case_address, output)
            )
        except BaseException as error:
            evidence.record("probe_error", error=repr(error))
            raise
        finally:
            if connection is not None:
                evidence.record(
                    "detached",
                    result=sessions.close(
                        CloseRequest(
                            session_id=session.session_id,
                            connection_id=connection.context.connection_id,
                        )
                    ).model_dump(mode="json"),
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
