"""Observe real P01 simulator results through the production view transport."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from importlib.metadata import version
from math import dist
from pathlib import Path
from typing import Any, cast

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    ReportSeries,
    ReportTime,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    GridId,
    JobId,
    ResultId,
    RevisionId,
    SessionId,
)
from resinsight_mcp.contracts.jobs import Job, JobState, Result
from resinsight_mcp.contracts.models import (
    ArtifactRef,
    Backend,
    ModelInputs,
    ModelRevision,
    Session,
)
from resinsight_mcp.contracts.sessions import Endpoint
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.views._camera import read_camera
from resinsight_mcp.workspaces import SqliteWorkspaceStore

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


@contextmanager
def native_application(executable: Path, output: Path) -> Iterator[RipsApplication]:
    """Supervise the exact trial child even when native attachment fails."""
    port_file = output / "native.port"
    application: RipsApplication | None = None
    with (output / "native.log").open("x") as log:
        process = subprocess.Popen(
            [str(executable), "--server", "0", "--portnumberfile", str(port_file)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        deadline = time.monotonic() + 120
        while not port_file.exists():
            if process.poll() is not None:
                raise RuntimeError("The trial application exited before readiness.")
            if time.monotonic() >= deadline:
                raise TimeoutError("The trial application did not publish its endpoint.")
            time.sleep(0.05)
        endpoint = Endpoint(port=int(port_file.read_text().strip()))
        application = RipsApplicationFactory(output / "application-logs").attach(endpoint)
        assert application.process.pid == process.pid
        (output / "native-process.json").write_text(application.process.model_dump_json() + "\n")
        yield application
    finally:
        try:
            if application is not None:
                application.disconnect()
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=30)


def archive(
    store: SqliteWorkspaceStore, session: Session, source: Path, kind: ArtifactKind
) -> Artifact:
    artifact = Artifact(
        ref=ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new()),
        relative_path=f"p01/{kind}/{source.name}",
        kind=kind,
    )
    with source.open("rb") as stream:
        return value(store.write_artifact(artifact, stream))


def seed_records(
    output: Path, case_file: Path, input_file: Path, record_file: Path
) -> tuple[SqliteWorkspaceStore, Session, ModelRevision, Job, Path]:
    """Backfill the completed P01 run without claiming a new simulator execution."""
    record = json.loads(record_file.read_text())
    assert record["exit_status"] == 0
    assert record["completed_report_steps"] == 120
    assert record["final_simulated_days"] == 3650
    store = SqliteWorkspaceStore.create(output / "workspace")
    session = value(
        store.create_session(Session(session_id=SessionId.new(), name="P06 real views"))
    )
    input_artifact = archive(store, session, input_file, ArtifactKind.INPUT)
    archive(store, session, record_file, ArtifactKind.LOG)
    model = ModelRef(session_id=session.session_id, revision_id=RevisionId.new())
    revision = value(
        store.save_revision(
            ModelRevision(
                model=model,
                inputs=ModelInputs(
                    artifacts=(input_artifact.ref.artifact_id,),
                    entrypoint=input_artifact.ref.artifact_id,
                ),
                unit_system=UnitSystem.FIELD,
                coordinates=CoordinateFrame(
                    length_unit=Unit.FOOT,
                    depth_direction=DepthDirection.POSITIVE_DOWN,
                    datum="SPE1 local origin",
                ),
            )
        )
    )
    native_data = output / "native-data"
    native_data.mkdir()
    for source in sorted(case_file.parent.glob(f"{case_file.stem}.*")):
        assert source.is_file()
        kind = ArtifactKind.LOG if source.suffix in (".DBG", ".PRT") else ArtifactKind.OUTPUT
        archive(store, session, source, kind)
        shutil.copyfile(source, native_data / source.name)
    job = value(
        store.save_job(
            Job(job_id=JobId.new(), model=model, backend=Backend.OPM_FLOW, state=JobState.QUEUED)
        )
    )
    running = value(store.save_job(job.transition(JobState.RUNNING), expected=job))
    completed = value(
        store.save_job(running.transition(JobState.SUCCEEDED, exit_code=0), expected=running)
    )
    (output / "historical-run.json").write_text(
        json.dumps(
            {
                "purpose": "Backfill the recorded P01 run. No simulator ran during this trial.",
                "source_record": str(record_file),
                "source_case": str(case_file),
                "source_input": str(input_file),
                "record": record,
                "job": completed.model_dump(mode="json"),
            },
            indent=2,
        )
        + "\n"
    )
    return store, session, revision, completed, native_data / case_file.name


def seed_application(
    application: RipsApplication, case_file: Path, output: Path
) -> tuple[Any, Any, Any, str]:
    project = cast(Any, application.project())
    case = project.load_case(str(case_file))
    assert case is not None
    target = case.create_view()
    control = case.create_view()
    for view in (target, control):
        view.grid_z_scale = 20
        view.update()
    well_name = "P06 selection well"
    well_file = output / "selection-well.dev"
    well_file.write_text(f"'{well_name}'\n500 500 8200 0\n500 500 8500 300\n")
    wells = project.import_well_paths(well_path_files=[str(well_file)])
    assert len(wells) == 1 and wells[0].name == well_name, [well.name for well in wells]
    target = next(view for view in project.views() if view.id == target.id)
    control = next(view for view in project.views() if view.id == control.id)
    return case, target, control, well_name


def manifest(
    output: Path,
    application: RipsApplication,
    store: SqliteWorkspaceStore,
    session: Session,
    revision: ModelRevision,
    job: Job,
    case_file: Path,
) -> Path:
    case, target, control, well_name = seed_application(application, case_file, output)
    dates = case.time_steps()
    days = case.days_since_start()
    assert len(dates) == len(days)
    reports = ReportSeries(
        reports=tuple(
            ReportTime(
                index=i, elapsed_days=day, calendar_date=date(item.year, item.month, item.day)
            )
            for i, (day, item) in enumerate(zip(days, dates, strict=True))
        )
    )
    assert reports.reports[-1].elapsed_days == 3650
    assert reports.reports[-1].calendar_date == date(2024, 12, 29)
    result = value(
        store.save_result(
            Result(
                result_id=ResultId.new(),
                job_id=job.job_id,
                model=revision.model,
                grid_id=GridId.new(),
                report_series=reports,
            )
        )
    )
    camera = read_camera(
        target.camera_matrix,
        target.camera_point_of_interest,
        target.perspective_projection,
        target.actual_camera_field_of_view_y_degrees,
        target.actual_camera_parallel_projection_height,
    )
    extent = dist(camera.position, camera.target) * 0.6
    camera = camera.model_copy(
        update={
            "position": (
                camera.target[0] + extent,
                camera.target[1] - extent,
                camera.target[2] + extent,
            ),
            "up": (0.0, 0.0, 1.0),
        }
    )
    base = {
        "model": revision.model.model_dump(mode="json"),
        "result_id": str(result.result_id),
        "grid_id": str(result.grid_id),
        "scene_version": 0,
        "property": {"name": "PRESSURE", "unit": "psi"},
        "report_time": reports.reports[0].model_dump(mode="json"),
        "coordinates": revision.coordinates.model_dump(mode="json"),
        "camera": camera.model_dump(mode="json"),
        "vertical_exaggeration": 20,
        "legend": {"minimum": 1000, "maximum": 5000},
        "filters": [],
    }
    late = {**base, "scene_version": 1, "report_time": reports.reports[-1].model_dump(mode="json")}
    saturation = {
        **late,
        "scene_version": 2,
        "property": {"name": "SGAS", "unit": "1"},
        "legend": {"minimum": 0, "maximum": 1},
    }
    x, y, z = (p - t for p, t in zip(camera.position, camera.target, strict=True))
    rotated = camera.model_copy(
        update={"position": (camera.target[0] - y, camera.target[1] + x, camera.target[2] + z)}
    )
    cropped = {
        **saturation,
        "scene_version": 3,
        "camera": rotated.model_dump(mode="json"),
        "filters": [
            {
                "grid_id": str(result.grid_id),
                "minimum": {"i": 0, "j": 0, "k": 0},
                "maximum": {"i": 4, "j": 9, "k": 2},
                "include": True,
            }
        ],
    }
    target_name, control_name = f"View {target.id}", f"View {control.id}"
    document = {
        "workspace": str(output / "workspace"),
        "application_logs": str(output / "observer-application-logs"),
        "endpoint": application.endpoint.model_dump(mode="json"),
        "session_id": str(session.session_id),
        "result_id": str(result.result_id),
        "case_name": case.name,
        "target_view_name": target_name,
        "control_view_name": control_name,
        "well_name": well_name,
        "requests": [
            {"view_name": name, "context": context, "width": 1200, "height": 800}
            for name, context in (
                (target_name, base),
                (control_name, base),
                (target_name, late),
                (target_name, saturation),
                (target_name, cropped),
            )
        ],
    }
    destination = output / "manifest.json"
    destination.write_text(json.dumps(document, indent=2) + "\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--p01-record", type=Path, required=True)
    parser.add_argument("--native-source", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir()
    environment = {
        "started_at": datetime.now(UTC).isoformat(),
        "command": sys.argv,
        "platform": platform.platform(),
        "python": sys.version,
        "versions": {name: version(name) for name in ("rips", "psutil", "mcp", "grpcio", "Pillow")},
        "source_commit": subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
        ).strip(),
        "native_commit": subprocess.check_output(
            ["git", "-C", str(arguments.native_source), "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    (output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    store, session, revision, job, case_file = seed_records(
        output, arguments.case.resolve(), arguments.input.resolve(), arguments.p01_record.resolve()
    )
    with native_application(arguments.executable, output) as application:
        settings = manifest(output, application, store, session, revision, job, case_file)
        completed = subprocess.run(
            [
                sys.executable,
                str(HERE / "run_observer.py"),
                "--codex",
                str(arguments.codex),
                "--trial",
                str(settings),
                "--evidence",
                str(output / "observer"),
            ],
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                "The native image observer trial failed. Inspect its saved evidence."
            )


if __name__ == "__main__":
    main()
