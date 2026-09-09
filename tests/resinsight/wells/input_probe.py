"""Verify modeled well factors from fixed input files without simulation."""

import argparse
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
import rips
from google.protobuf.json_format import MessageToDict

from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.imports import ImportRequest, MaterializedModel, OpmImportService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    if not isinstance(result.outcome, Success):
        raise RuntimeError(str(result.outcome))
    return result.outcome.value


class Evidence:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.events: list[dict[str, Any]] = []

    def record(self, label: str, **values: Any) -> None:
        self.events.append({"label": label, **values})
        (self.output / "events.json").write_text(json.dumps(self.events, indent=2) + "\n")

    def check(self, label: str, passed: bool, **values: Any) -> None:
        self.record(label, passed=bool(passed), **values)
        if not passed:
            raise RuntimeError(label)


def reject_inputs(instance: Any, model: MaterializedModel, evidence: Evidence) -> None:
    cases = tuple(case.id for case in instance.project.cases())
    for name, source, old, new in (
        ("lab", "SPE1.DATA", "FIELD", "LAB"),
        ("parse", "SPE1.DATA", "RUNSPEC", "NOTAKEYWORD"),
        ("large", "SPE1.DATA", "10 10 3 /", "101 101 1 /"),
        ("range", "includes/grid.inc", "8325", "1e39"),
    ):
        root = Path(shutil.copytree(model.directory, evidence.output / name))
        path = root / source
        content = path.read_text()
        if old not in content:
            raise RuntimeError(f"The {name} negative fixture does not match the preserved deck.")
        path.write_text(content.replace(old, new))
        try:
            instance.project.load_prepared_input_grid(path=str(root / "SPE1.DATA"))
        except rips.exception.RipsError as error:
            evidence.check(
                "rejected_input",
                cases == tuple(case.id for case in instance.project.cases()),
                kind=name,
                error=str(error),
            )
        else:
            evidence.check("rejected_input", False, kind=name)


def inspect_case(case: Any, model: MaterializedModel, evidence: Evidence) -> None:
    expected = model.inspection
    dims = case.grid().dimensions()
    evidence.check("grid_dimensions", (dims.i, dims.j, dims.k) == expected.summary.dimensions)
    evidence.check(
        "active_cell_count", case.cell_count().active_cell_count == len(expected.active_cells)
    )
    centers = case.grid().cell_centers()
    evidence.check(
        "cell_depths",
        len(centers) == len(expected.cell_depths_ft)
        and all(
            math.isclose(center.z, depth, rel_tol=1e-6, abs_tol=1e-3)
            for center, depth in zip(centers, expected.cell_depths_ft, strict=True)
        ),
        first_center=MessageToDict(centers[0]),
    )
    volumes = case.active_cell_property("STATIC_NATIVE", "riCELLVOLUME", 0)
    evidence.check(
        "cell_volumes",
        len(volumes) == len(expected.cell_volumes_ft3)
        and all(
            math.isclose(observed, wanted, rel_tol=1e-6)
            for observed, wanted in zip(volumes, expected.cell_volumes_ft3, strict=True)
        ),
        first_volume_ft3=volumes[0],
    )
    for name, wanted in expected.properties.keyword_arrays():
        observed = case.active_cell_property("INPUT_PROPERTY", name, 0)
        evidence.check(
            "property_values",
            len(observed) == len(wanted)
            and all(
                math.isclose(actual, intended, rel_tol=1e-6, abs_tol=1e-8)
                for actual, intended in zip(observed, wanted, strict=True)
            ),
            name=name,
            first=observed[0],
            last=observed[-1],
        )


def inspect_well(instance: Any, case: Any, evidence: Evidence) -> None:
    well = instance.project.well_path_collection().create_modeled_well_path_for_case(
        case_id=case.id, name="P09INPUT"
    )
    geometry = well.well_path_geometry()
    geometry.use_auto_generated_target_at_sea_level = False
    geometry.update()
    for depth in (0.0, 8325.0, 8430.0):
        geometry.append_well_target(coordinate=[4500.0, 4500.0, depth], absolute=True)
    trajectory = well.trajectory_properties(resampling_interval=50.0)
    evidence.check(
        "field_trajectory", math.isclose(trajectory["coordinate_z"][-1], 8430.0, abs_tol=1e-3)
    )
    well.append_perforation_interval(start_md=8326.0, end_md=8424.0, diameter=0.5, skin_factor=0.0)
    tables = well.completion_data(case_id=case.id)
    evidence.record("completion_data", data=MessageToDict(tables))
    cells = {(row.grid_i, row.grid_j, row.upper_k, row.lower_k) for row in tables.compdat}
    evidence.check("completion_cells", cells == {(5, 5, 1, 1), (5, 5, 2, 2), (5, 5, 3, 3)})
    reference = {1: 10.078780273272798, 2: 1.5913863589378099, 3: 10.397057545060358}
    for row in tables.compdat:
        evidence.check(
            "completion_factor",
            math.isclose(row.transmissibility, reference[row.upper_k], rel_tol=1e-6),
            k=row.upper_k,
            factor=row.transmissibility,
        )
    case.export_well_path_completions(
        time_step=0,
        well_path_names=[well.name],
        file_split="UNIFIED_FILE",
        include_fishbones=False,
        custom_file_name=str(evidence.output / "P09INPUT.inc"),
    )


def run_native(executable: Path, model: MaterializedModel, evidence: Evidence) -> None:
    output = evidence.output
    command = [str(executable), "--server", "0", "--portnumberfile", str(output / "port.txt")]
    evidence.record(
        "command",
        command=command,
        environment={
            key: os.environ.get(key) for key in ("LC_ALL", "QT_PLUGIN_PATH", "PYTHONPATH")
        },
    )
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
            instance: Any = rips.Instance(port=int((output / "port.txt").read_text()))
            evidence.record("connected", version=instance.version_string(), port=instance.port)
            reject_inputs(instance, model, evidence)
            case = instance.project.load_prepared_input_grid(path=str(model.entrypoint))
            evidence.record("case_loaded", case_id=case.id)
            properties = case.import_properties(file_names=[str(model.property_file)])
            evidence.record("properties_loaded", names=properties.values)
            view = case.create_view()
            inspect_case(case, model, evidence)
            inspect_well(instance, case, evidence)
            instance.project.save(str(output / "prepared-input.rsp"))
            view.export_snapshot(
                prefix="prepared", export_folder=str(output), width=1000, height=800
            )
        except BaseException as error:
            evidence.record("probe_error", error=repr(error))
            raise
        finally:
            if process.poll() is None:
                if psutil.Process(process.pid).create_time() != identity:
                    raise RuntimeError("The owned process identity changed.")
                process.terminate()
                process.wait(timeout=20)
            evidence.record(
                "cleanup",
                pid=process.pid,
                exit_code=process.returncode,
                alive=psutil.pid_exists(process.pid),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(exist_ok=False)
    evidence = Evidence(output)
    store = SqliteWorkspaceStore.create(output / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="P09 inputs")))
    service = OpmImportService(store)
    receipt = value(
        service.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=arguments.source.resolve(),
                entrypoint="SPE1.DATA",
                datum="SPE1 local datum",
            )
        )
    )
    (output / "import-receipt.json").write_text(receipt.model_dump_json(indent=2) + "\n")
    with service.materialize(receipt.prepared.revision.model) as model:
        (output / "inspection.json").write_text(model.inspection.model_dump_json(indent=2) + "\n")
        shutil.copyfile(model.property_file, output / "properties.GRDECL")
        run_native(arguments.executable.resolve(strict=True), model, evidence)


if __name__ == "__main__":
    main()
