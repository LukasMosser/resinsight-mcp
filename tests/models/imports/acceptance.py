"""Run a bounded import trial through the proved P01 applications."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import grpc
import rips
from PIL import Image

from resinsight_mcp.contracts.errors import Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef, Backend, PreparationRequest, Session
from resinsight_mcp.contracts.sessions import CloseAction, CloseRequest, LaunchRequest
from resinsight_mcp.models.imports import ImportReceipt, ImportRequest, OpmImportService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore

IMAGE = (
    "openporousmedia/opmreleases@"
    "sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1"
)


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


def command(arguments: list[str], output: Path, *, timeout: int = 60) -> None:
    with output.open("w") as log:
        log.write(json.dumps(arguments) + "\n")
        log.flush()
        completed = subprocess.run(
            arguments, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False
        )
        log.write(f"\nExit status: {completed.returncode}\n")
    assert completed.returncode == 0, output.read_text()


def import_inputs(output: Path) -> tuple[SqliteWorkspaceStore, ImportReceipt]:
    fixture = Path(__file__).parent / "data" / "spe1"
    source = output / "source-copy"
    shutil.copytree(fixture, source)
    store = SqliteWorkspaceStore.create(output / "workspace")
    session = value(
        store.create_session(Session(session_id=SessionId.new(), name="P07 acceptance"))
    )
    service = OpmImportService(store)
    request = ImportRequest(
        session_id=session.session_id,
        source_root=source.resolve(),
        entrypoint="SPE1.DATA",
        datum="SPE1 local depth datum",
    )
    rejected_source = output / "invalid-source"
    shutil.copytree(source, rejected_source)
    (rejected_source / "includes" / "props.inc").unlink()
    rejected = service.import_model(request.model_copy(update={"source_root": rejected_source}))
    assert isinstance(rejected.outcome, Failure)
    assert not value(store.list_artifacts(session.session_id))
    assert not value(store.list_jobs(session.session_id))
    (output / "invalid-input.json").write_text(rejected.model_dump_json(indent=2))
    receipt = value(service.import_model(request))
    shutil.rmtree(source)
    assert not source.exists()
    assert (
        value(
            service.prepare(
                PreparationRequest(revision=receipt.prepared.revision, backend=Backend.OPM_FLOW)
            )
        )
        == receipt.prepared
    )
    (output / "import-receipt.json").write_text(receipt.model_dump_json(indent=2))
    with store.open_artifact(receipt.record) as stream:
        (output / "import-record.json").write_text(stream.read().decode("utf-8"))
    inputs = output / "prepared-inputs"
    for artifact_id in receipt.prepared.revision.inputs.artifacts:
        ref = ArtifactRef(session_id=session.session_id, artifact_id=artifact_id)
        artifact = value(store.get_artifact(ref))
        destination = inputs / artifact.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with store.open_artifact(ref) as source_stream, destination.open("wb") as target:
            shutil.copyfileobj(source_stream, target)
    return store, receipt


def simulate(output: Path, docker: str) -> None:
    command([docker, "version"], output / "docker-version.log")
    base = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--platform",
        "linux/arm64",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--network",
        "none",
    ]
    command([*base, IMAGE, "flow", "--version"], output / "flow-version.log")
    results = output / "results"
    results.mkdir()
    container = f"resinsight-p07-{uuid4().hex}"
    arguments = [
        *base,
        "--name",
        container,
        "--mount",
        f"type=bind,source={output / 'prepared-inputs'},target=/input,readonly",
        "--mount",
        f"type=bind,source={results},target=/output",
        IMAGE,
        "flow",
        "/input/SPE1.DATA",
        "--output-dir=/output",
    ]
    try:
        command(arguments, output / "flow-run.log")
    except subprocess.TimeoutExpired:
        command([docker, "rm", "--force", container], output / "container-timeout-cleanup.log")
        raise
    for extension in ("EGRID", "INIT", "UNRST", "SMSPEC", "UNSMRY"):
        assert (results / f"SPE1.{extension}").is_file()


def display(
    output: Path, executable: Path, store: SqliteWorkspaceStore, receipt: ImportReceipt
) -> dict[str, Any]:
    service = ResInsightSessionService(store, RipsApplicationFactory(output / "application-logs"))
    model = receipt.prepared.revision.model
    connection = value(
        service.launch(LaunchRequest(session_id=model.session_id, executable=executable))
    )
    try:
        with grpc.insecure_channel(f"127.0.0.1:{connection.endpoint.port}") as channel:
            project = cast(Any, rips.Project).create(channel)
            case_path = output / "results" / "SPE1.EGRID"
            case = project.load_case(str(case_path))
            assert case is not None
            case.name_setting = rips.NameSetting.CUSTOM_NAME
            case.name = f"P07 imported {model.revision_id}"
            case.update()
            dimensions = case.grid().dimensions()
            cells = case.cell_count().active_cell_count
            assert (dimensions.i, dimensions.j, dimensions.k) == receipt.summary.dimensions
            assert cells == receipt.summary.active_cells == 300
            step = len(case.time_steps()) - 1
            assert step == receipt.summary.report_steps
            view = case.create_view()
            view.name = "P07 imported FIELD model"
            view.grid_z_scale = 20
            view.update()
            view.apply_cell_result("DYNAMIC_NATIVE", "PRESSURE")
            view.set_time_step(step)
            view.export_snapshot(
                export_folder=str(output), prefix="imported-model", width=1200, height=800
            )
            images = tuple(output.glob("imported-model*.png"))
            assert len(images) == 1
            with Image.open(images[0]) as picture:
                picture.load()
                assert picture.size == (1200, 800)
            pressure = case.active_cell_property("DYNAMIC_NATIVE", "PRESSURE", step)
            assert len(pressure) == cells
            return {
                "model": model.model_dump(mode="json"),
                "connection": connection.model_dump(mode="json"),
                "case_id": case.id,
                "case_name": case.name,
                "case_path": str(case_path),
                "dimensions": [dimensions.i, dimensions.j, dimensions.k],
                "active_cells": cells,
                "report_step": step,
                "time_steps": [
                    {"year": item.year, "month": item.month, "day": item.day}
                    for item in case.time_steps()
                ],
                "property": "PRESSURE",
                "pressure_range_psi": [min(pressure), max(pressure)],
                "snapshot": images[0].name,
                "resinsight_version": rips.Instance(port=connection.endpoint.port).version_string(),
            }
    finally:
        value(
            service.close(
                CloseRequest(
                    session_id=model.session_id,
                    connection_id=connection.context.connection_id,
                    action=CloseAction.TERMINATE,
                )
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resinsight", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir()
    store, receipt = import_inputs(output)
    simulate(output, arguments.docker)
    loaded = display(output, arguments.resinsight, store, receipt)
    record = {
        "time": datetime.now(UTC).isoformat(),
        "tested_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree": subprocess.check_output(
            ["git", "status", "--short"], text=True
        ).splitlines(),
        "host": platform.platform(),
        "python": sys.version,
        "packages": {name: version(name) for name in ("opm", "rips", "pydantic", "pillow")},
        "resinsight_executable": str(arguments.resinsight),
        "qt_plugin_path": os.environ["QT_PLUGIN_PATH"],
        "flow_image": IMAGE,
        "prepared": receipt.prepared.model_dump(mode="json"),
        "loaded_case": loaded,
        "invalid_input_rejected_before_simulator": True,
        "source_copy_removed_before_stored_preparation": True,
        "limits": "Two CPUs, 2 GiB memory, no network, 60-second Flow timeout.",
    }
    (output / "acceptance.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
