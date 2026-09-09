"""Inspect modeled well behavior in one owned native process."""

import argparse
import json
import math
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import psutil
import rips
from google.protobuf.json_format import MessageToDict

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--executable", type=Path, required=True)
parser.add_argument("--grid", type=Path, required=True)
parser.add_argument("--creation", choices=("generic", "case-aware"), required=True)
arguments = parser.parse_args()
OUT = arguments.output.resolve()
OUT.mkdir(exist_ok=False)
EXE = arguments.executable.resolve(strict=True)
GRID = arguments.grid.resolve(strict=True)
events = []


def record(label, **values):
    events.append({"label": label, **values})
    (OUT / "events.json").write_text(json.dumps(events, indent=2) + "\n")


def observe(well, label):
    trajectory = well.trajectory_properties(resampling_interval=50.0)
    record(
        label,
        name=well.name,
        trajectory=trajectory,
        targets=[target.target_point for target in well.well_path_geometry().well_path_targets()],
    )
    return trajectory


def check(label, passed, **values):
    record(label, passed=bool(passed), **values)
    if not passed:
        raise RuntimeError(label)


def reject_creation(collection, project, case_id, name):
    before = [well.name for well in project.well_paths()]
    try:
        collection.create_modeled_well_path_for_case(case_id=case_id, name=name)
    except rips.exception.RipsError as error:
        check(
            "invalid_creation",
            before == [well.name for well in project.well_paths()],
            case_id=case_id,
            name=name,
            error=str(error),
        )
    else:
        check("invalid_creation", False, case_id=case_id, name=name)


def check_export(path, rows):
    import opm.io.deck  # noqa: F401
    from opm.io.parser import Parser

    deck = Parser().parse(str(path))
    records = [{item.name(): item for item in row} for row in deck["COMPDAT"]]
    expected = {(row.grid_i, row.grid_j, row.upper_k, row.lower_k): row for row in rows}
    check("export_row_count", len(records) == len(expected))
    for row in records:
        cell = tuple(row[key].value for key in ("I", "J", "K1", "K2"))
        native = expected[cell]
        check(
            "export_connection",
            row["WELL"].value == native.well_name
            and row["STATE"].value == "OPEN"
            and math.isclose(
                row["CONNECTION_TRANSMISSIBILITY_FACTOR"].value,
                native.transmissibility,
                rel_tol=1e-6,
            ),
            cell=cell,
        )


command = [str(EXE), "--server", "0", "--portnumberfile", str(OUT / "port.txt")]
record(
    "command",
    command=command,
    environment={key: os.environ.get(key) for key in ("LC_ALL", "QT_PLUGIN_PATH", "PYTHONPATH")},
)
with (OUT / "application.log").open("w") as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    identity = psutil.Process(process.pid).create_time()
    record("owned_process", pid=process.pid, start_marker=identity)
    instance = None
    try:
        deadline = time.monotonic() + 45
        while not (OUT / "port.txt").exists():
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("The owned application did not publish its port.")
            time.sleep(0.1)
        port = int((OUT / "port.txt").read_text())
        instance = rips.Instance(port=port)
        record("connected", port=port, version=instance.version_string())
        case = instance.project.load_case(str(GRID))
        record("case", case_id=case.id, name=case.name)
        view = case.create_view()
        collection = instance.project.well_path_collection()
        if arguments.creation == "case-aware":
            reject_creation(collection, instance.project, -999, "P09BAD")
            reject_creation(collection, instance.project, case.id, "")
        scenarios = (
            ("P09ORIG", True, [0.0, 8325.0, 8430.0]),
            ("P09NOAUTO", False, [0.0, 8325.0, 8430.0]),
            ("P09AUTO", True, [8325.0, 8430.0]),
        )
        if arguments.creation == "case-aware":
            scenarios = scenarios[1:]
        for name, auto, depths in scenarios:
            if arguments.creation == "generic":
                well = collection.add_new_object(rips.ModeledWellPath)
                well.name = name
                well.update()
            else:
                well = collection.create_modeled_well_path_for_case(case_id=case.id, name=name)
                reject_creation(collection, instance.project, case.id, name)
            geometry = well.well_path_geometry()
            geometry.use_auto_generated_target_at_sea_level = auto
            geometry.update()
            for depth in depths:
                geometry.append_well_target(coordinate=[4500.0, 4500.0, depth], absolute=True)
            trajectory = observe(well, "after_append")
            if arguments.creation == "case-aware":
                check(
                    "positive_down_trajectory",
                    len(trajectory["coordinate_z"]) == 170
                    and trajectory["coordinate_z"][-1] == 8430.0,
                )
            targets = geometry.well_path_targets()
            targets[-1].target_point = [4500.0, 4500.0, 8450.0]
            targets[-1].update()
            trajectory = observe(well, "after_target_update")
            if arguments.creation == "case-aware":
                check("target_update_recomputes", trajectory["coordinate_z"][-1] == 8450.0)
            well.append_perforation_interval(
                start_md=8326.0, end_md=8424.0, diameter=0.5, skin_factor=0.0
            )
            try:
                tables = well.completion_data(case_id=case.id)
                record(
                    "completion_data",
                    name=name,
                    data=MessageToDict(tables),
                )
                case.export_well_path_completions(
                    time_step=0,
                    well_path_names=[name],
                    file_split="UNIFIED_FILE",
                    include_fishbones=False,
                    custom_file_name=str(OUT / (name + ".inc")),
                )
                record("export", name=name, paths=[str(path) for path in OUT.glob(name + "*.inc")])
                if arguments.creation == "case-aware":
                    cells = {
                        (row.grid_i, row.grid_j, row.upper_k, row.lower_k) for row in tables.compdat
                    }
                    check("active_connections", cells == {(5, 5, 1, 1), (5, 5, 2, 2), (5, 5, 3, 3)})
                    check_export(OUT / (name + ".inc"), tables.compdat)
            except Exception as error:
                record("completion_error", name=name, error=str(error))
                if arguments.creation == "case-aware":
                    raise
        instance.project.save(str(OUT / "modeled.rsp"))
        saved = ET.parse(OUT / "modeled.rsp")
        units = {
            well.findtext("Name"): well.findtext("UnitSystem")
            for well in saved.iter("ModeledWellPath")
        }
        record("saved_well_units", units=units)
        if arguments.creation == "case-aware":
            check("field_well_units", set(units.values()) == {"UNITS_FIELD"})
        view.export_snapshot(prefix="modeled", export_folder=str(OUT), width=1000, height=800)
    except BaseException as error:
        record("probe_error", error=repr(error))
        raise
    finally:
        if process.poll() is None:
            if psutil.Process(process.pid).create_time() != identity:
                raise RuntimeError("The owned process identity changed.")
            if instance is not None:
                instance.exit()
            else:
                process.terminate()
            process.wait(timeout=20)
        record(
            "cleanup",
            pid=process.pid,
            exit_code=process.returncode,
            alive=psutil.pid_exists(process.pid),
        )
