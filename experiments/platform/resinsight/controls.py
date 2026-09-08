"""Run the P01 control probe against one owned ResInsight GUI process."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rips
from google.protobuf.json_format import MessageToDict
from PIL import Image


def event(output: Path, step: str, **details: Any) -> None:
    record = {"time": datetime.now(UTC).isoformat(), "step": step, **details}
    with (output / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)


def attach(process: subprocess.Popen[bytes], port_file: Path) -> Any:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Owned ResInsight exited with {process.returncode}")
        if port_file.exists() and port_file.read_text().strip():
            return rips.Instance(port=int(port_file.read_text().strip()), launched=True)
        time.sleep(0.25)
    raise TimeoutError("Owned ResInsight did not publish its port within 120 seconds")


def snapshot(view: Any, output: Path, name: str) -> None:
    folder = output / name
    folder.mkdir()
    view.export_snapshot(prefix=name, export_folder=str(folder), width=1280, height=900)
    files = list(folder.glob("*.png"))
    if not files:
        raise RuntimeError(f"Snapshot export produced no PNG: {folder}")
    for path in files:
        with Image.open(path) as picture:
            picture.load()
            event(output, "snapshot", file=str(path), dimensions=picture.size)


def load_case(instance: Any, attached: Any, grid_path: Path, output: Path) -> Any:
    case = instance.project.load_case(str(grid_path))
    if case is None or attached.project.case(case.id) is None:
        raise RuntimeError("Loaded case was not visible through the explicit-port attachment")
    dimensions = case.grid().dimensions()
    count = case.cell_count()
    box = case.reservoir_boundingbox()
    geometry = {
        key: getattr(box, key) for key in ("min_x", "max_x", "min_y", "max_y", "min_z", "max_z")
    }
    event(
        output,
        "case_loaded",
        case_id=case.id,
        dimensions=[dimensions.i, dimensions.j, dimensions.k],
        active_cells=count.active_cell_count,
        bounding_box=geometry,
    )
    if (dimensions.i, dimensions.j, dimensions.k) != (10, 10, 3):
        raise RuntimeError("This probe requires the P01 SPE1 grid with dimensions 10 × 10 × 3")
    expected = {
        "min_x": 0,
        "max_x": 10000,
        "min_y": 0,
        "max_y": 10000,
        "min_z": -8425,
        "max_z": -8325,
    }
    if count.active_cell_count != 300 or any(
        not math.isclose(geometry[key], value, abs_tol=0.01) for key, value in expected.items()
    ):
        raise RuntimeError("Grid geometry differs from the inspected FIELD fixture")
    return case


def change_view(case: Any, output: Path) -> Any:
    properties = case.available_properties(rips.PropertyType.DYNAMIC_NATIVE)
    if not {"PRESSURE", "SGAS"}.issubset(properties):
        raise RuntimeError(f"Required dynamic properties are missing: {properties}")
    final_step = len(case.time_steps()) - 1
    if final_step < 1:
        raise RuntimeError("Result change requires at least two time steps")
    view = case.create_view()
    view.name = "P01 control probe"
    view.grid_z_scale = 20
    view.update()
    for variable, step, name in (
        ("PRESSURE", 0, "pressure_initial"),
        ("SGAS", final_step, "gas_final"),
    ):
        view.apply_cell_result("DYNAMIC_NATIVE", variable)
        view.set_time_step(step)
        fresh = case.view(view.id)
        result = fresh.cell_result()
        if (
            fresh.current_time_step != step
            or result.result_variable != variable
            or result.result_type != "DYNAMIC_NATIVE"
            or fresh.grid_z_scale != 20
        ):
            raise RuntimeError("View result or time-step readback differs from the requested state")
        values = case.active_cell_property("DYNAMIC_NATIVE", variable, step)
        event(
            output,
            "view_changed",
            variable=result.result_variable,
            time_step=fresh.current_time_step,
            grid_z_scale=fresh.grid_z_scale,
            value_count=len(values),
            minimum=min(values),
            maximum=max(values),
        )
        snapshot(view, output, name)
    return view


def create_well(instance: Any, case: Any, view: Any, output: Path) -> Any:
    center = case.grid().cell_centers()[case.grid().property_data_index_from_ijk(5, 5, 1)]
    if not math.isclose(center.x, 4500) or not math.isclose(center.y, 4500):
        raise RuntimeError("Selected well column differs from the inspected fixture")
    well = instance.project.well_path_collection().add_new_object(rips.ModeledWellPath)
    well.name = "P01CTRL"
    well.update()
    geometry = well.well_path_geometry()
    targets = [[center.x, center.y, depth] for depth in (0.0, 8325.0, 8430.0)]
    for target in targets:
        geometry.append_well_target(coordinate=target, absolute=True)
    interval = well.append_perforation_interval(
        start_md=8326.0, end_md=8424.0, diameter=0.5, skin_factor=0.0
    )
    event(
        output,
        "well_created",
        name=well.name,
        targets=targets,
        target_z_meaning="positive-down depth in fixture feet",
        start_md=interval.start_measured_depth,
        end_md=interval.end_measured_depth,
        diameter=interval.diameter,
        skin_factor=interval.skin_factor,
    )
    trajectory = well.trajectory_properties(resampling_interval=50.0)
    (output / "trajectory.json").write_text(json.dumps(trajectory, indent=2) + "\n")
    # The upstream coordinate_z field contains positive-down true vertical depth.
    samples = list(
        zip(
            trajectory["coordinate_x"],
            trajectory["coordinate_y"],
            trajectory["coordinate_z"],
            trajectory["measured_depth"],
            strict=True,
        )
    )
    if not samples or any(
        not (
            math.isclose(x, 4500, abs_tol=0.001)
            and math.isclose(y, 4500, abs_tol=0.001)
            and math.isclose(depth, md, abs_tol=0.001)
        )
        for x, y, depth, md in samples
    ):
        raise RuntimeError("Modeled trajectory does not match the requested vertical well")
    snapshot(view, output, "modeled_well")
    instance.project.save(str(output / "controls.rsp"))
    event(output, "trajectory_verified", samples=len(samples), final_sample=samples[-1])
    return well


def export_completions(case: Any, well: Any, output: Path) -> None:
    folder = output / "completions"
    folder.mkdir()
    tables = well.completion_data(case_id=case.id)
    (output / "completion_data.json").write_text(json.dumps(MessageToDict(tables), indent=2) + "\n")
    event(output, "completion_data_read", row_count=len(tables.compdat))
    case.export_well_path_completions(
        time_step=0,
        well_path_names=[well.name],
        file_split="UNIFIED_FILE",
        compdat_export="TRANSMISSIBILITIES",
        include_perforations=True,
        include_fishbones=False,
        export_welspec=True,
        export_comments=True,
        custom_file_name=str(folder / "P01CTRL.inc"),
    )
    rows = list(tables.compdat)
    cells = {(row.grid_i, row.grid_j, row.upper_k, row.lower_k) for row in rows}
    files = sorted(str(path) for path in folder.iterdir() if path.is_file())
    event(output, "completion_export", files=files, row_count=len(rows), cells=sorted(cells))
    if cells != {(5, 5, 1, 1), (5, 5, 2, 2), (5, 5, 3, 3)}:
        raise RuntimeError(
            "Completion cells differ from the well column. Check modeled-well FIELD units."
        )
    if not files or any(row.well_name != well.name for row in rows):
        raise RuntimeError("Completion export is missing files or has an unexpected well name")
    if any(not math.isfinite(row.transmissibility) or row.transmissibility <= 0 for row in rows):
        raise RuntimeError("Completion transmissibility must be finite and positive")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    clients: list[Any] = []
    with (output / "application.log").open("wb") as log:
        process = subprocess.Popen(
            [
                str(args.executable.resolve()),
                "--server",
                "0",
                "--portnumberfile",
                str(output / "port.txt"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        event(output, "owned_launch", pid=process.pid, executable=str(args.executable.resolve()))
        try:
            instance = attach(process, output / "port.txt")
            clients.append(instance)
            port = int((output / "port.txt").read_text().strip())
            attached = rips.Instance(port=port, launched=False)
            clients.append(attached)
            event(
                output,
                "explicit_attachment",
                port=port,
                server_version=instance.version_string(),
                client_version=instance.client_version_string(),
                is_gui=instance.is_gui(),
            )
            if (instance.major_version(), instance.minor_version(), instance.patch_version()) != (
                2026,
                9,
                0,
            ):
                raise RuntimeError("This probe requires ResInsight 2026.09.0")
            if not instance.is_gui():
                raise RuntimeError("Snapshot evidence requires the GUI application")
            case = load_case(instance, attached, args.grid.resolve(), output)
            view = change_view(case, output)
            well = create_well(instance, case, view, output)
            export_completions(case, well, output)
            event(output, "complete")
        except Exception as error:
            event(output, "failed", error_type=type(error).__name__, message=str(error))
            raise
        finally:
            for client in clients:
                client.stop_heartbeat()
                client.channel.close()
            if args.keep_open:
                event(output, "owned_process_retained", pid=process.pid)
            else:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        event(output, "owned_process_kill", pid=process.pid)
                        process.kill()
                        process.wait(timeout=10)
                event(
                    output, "owned_process_closed", pid=process.pid, return_code=process.returncode
                )


if __name__ == "__main__":
    main()
