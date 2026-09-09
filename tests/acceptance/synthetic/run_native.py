"""Review a generated P08 result through one owned native application.

This standalone Python trial does not provide MCP result loading or model inference.
"""

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import psutil
import rips
from opm.io.ecl import EGrid, ERst, ESmry
from PIL import Image

from resinsight_mcp.contracts.observations import Camera, Projection
from resinsight_mcp.models.synthetic import SyntheticModelReceipt, read_grid_id, read_specification
from resinsight_mcp.resinsight.sessions.rips import RipsApplication, RipsApplicationFactory
from resinsight_mcp.resinsight.views._camera import read_camera, view_matrix

GEOMETRY_TOLERANCE_FT = 1e-6


def write(path: Path, record: Any) -> None:
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def vector(value: Any) -> list[float]:
    return [value.x, value.y, value.z]


def ijk(value: Any) -> list[int]:
    return [value.i, value.j, value.k]


class Trial:
    def __init__(self, output: Path, numerical: Path, executable: Path) -> None:
        self.output = output
        self.numerical = numerical
        self.executable = executable.resolve()
        self.application: RipsApplication | None = None
        self.result_file = numerical / "generated-1" / "results" / "SYNTHETIC.EGRID"
        self.receipt = SyntheticModelReceipt.model_validate_json(
            (numerical / "generated-receipt.json").read_text()
        )
        source = (numerical / "generated-1" / "inputs" / "SYNTHETIC.DATA").read_text()
        self.specification = read_specification(source)
        assert read_grid_id(source) == self.receipt.active_cells.grid_id
        assert (
            self.specification.grid.active_cells(
                self.receipt.active_cells.model, read_grid_id(source)
            )
            == self.receipt.active_cells
        )

    def event(self, name: str, **details: Any) -> None:
        record = {"at": datetime.now(UTC).isoformat(), "event": name, **details}
        with (self.output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    def reference(self) -> dict[str, Any]:
        acceptance = json.loads((self.numerical / "acceptance.json").read_text())
        comparison = json.loads((self.numerical / "comparison.json").read_text())
        source_record = json.loads((self.numerical / "generated-source-record.json").read_text())
        assert acceptance["passed"] and comparison["passed"]
        assert source_record["model"] == self.receipt.active_cells.model.model_dump(mode="json")
        assert source_record["sources"][
            "SYNTHETIC.DATA"
        ] == self.receipt.specification_source.model_dump(mode="json")
        grid = EGrid(str(self.result_file))
        restart = ERst(str(self.result_file.with_suffix(".UNRST")))
        summary = ESmry(str(self.result_file.with_suffix(".SMSPEC")))
        assert tuple(grid.dimension) == self.specification.grid.dimensions == (10, 10, 3)
        assert grid.active_cells == 300
        cells = [list(grid.ijk_from_active_index(index)) for index in range(grid.active_cells)]
        assert cells == [[cell.i, cell.j, cell.k] for cell in self.receipt.active_cells.cells]
        assert 2 in restart.report_steps
        assert summary.units("TIME").strip() == "DAYS"
        assert summary.units("WBHP:PROD").strip() == "PSIA"
        assert [float(item) for item in summary["TIME", True]] == [1.0, 2.0]
        pressure = restart["PRESSURE", 2]
        assert len(pressure) == 300 and np.all(np.isfinite(pressure))
        tolerance = comparison["comparisons"]["generated_against_p07"]["PRESSURE:2"]
        assert tolerance["relative_tolerance"] == 0
        assert tolerance["absolute_tolerance"] == 2 * float(np.spacing(np.max(np.abs(pressure))))
        record = {
            "numerical_source_commit": acceptance["tested_commit"],
            "result_file": str(self.result_file),
            "receipt": "generated-receipt.json",
            "specification": self.specification.model_dump(mode="json"),
            "source_record": source_record,
            "flow_command": json.loads(
                (self.numerical / "generated-1" / "flow.command.json").read_text()
            ),
            "opm_dimensions": list(grid.dimension),
            "opm_active_cells": cells,
            "pressure": [float(item) for item in pressure],
            "pressure_dtype": str(pressure.dtype),
            "pressure_unit": "PSIA",
            "pressure_unit_evidence": "Generated FIELD inputs and OPM WBHP:PROD summary units.",
            "report_days": 2.0,
            "pressure_absolute_tolerance": tolerance["absolute_tolerance"],
            "pressure_relative_tolerance": 0,
            "tolerance_basis": comparison["tolerance_basis"],
        }
        write(self.output / "reference.json", record)
        for name in (
            "generated-receipt.json",
            "generated-source-record.json",
            "acceptance.json",
            "comparison.json",
        ):
            shutil.copyfile(self.numerical / name, self.output / name)
        return record

    def verify_owned(self, reason: str) -> psutil.Process:
        assert self.application is not None
        identity = self.application.verify_process()
        process = psutil.Process(identity.pid)
        assert str(process.create_time()) == identity.start_marker
        command = process.cmdline()
        assert Path(process.exe()).resolve() == self.executable
        assert Path(command[0]).resolve() == self.executable
        assert command[1:3] == ["--server", "0"]
        assert command[3] == "--portnumberfile"
        assert Path(command[4]).parent.resolve() == (self.output / "native-logs").resolve()
        assert int(Path(command[4]).read_text().strip()) == self.application.endpoint.port
        self.event(
            "owned_process_verified",
            reason=reason,
            identity=identity.model_dump(mode="json"),
            endpoint=self.application.endpoint.model_dump(mode="json"),
            command=command,
        )
        return process

    def geometry(self, case: Any, reference: dict[str, Any]) -> None:
        self.event(
            "native_geometry_requested",
            methods=[
                "grid.dimensions",
                "cell_count",
                "cell_info_for_active_cells",
                "active_cell_centers",
                "active_cell_corners",
                "reservoir_boundingbox",
                "reservoir_depth_range",
            ],
        )
        dimensions = ijk(case.grid().dimensions())
        counts = case.cell_count()
        information = case.cell_info_for_active_cells()
        centers = [vector(item) for item in case.active_cell_centers()]
        corners = [
            [vector(getattr(cell, f"c{corner}")) for corner in range(8)]
            for cell in case.active_cell_corners()
        ]
        cells = [ijk(item.local_ijk) for item in information]
        bbox = case.reservoir_boundingbox()
        record = {
            "dimensions": dimensions,
            "active_cells": counts.active_cell_count,
            "reservoir_cells": counts.reservoir_cell_count,
            "cell_info": [
                {
                    "grid_index": item.grid_index,
                    "local_ijk": ijk(item.local_ijk),
                    "parent_grid_index": item.parent_grid_index,
                    "parent_ijk": ijk(item.parent_ijk),
                }
                for item in information
            ],
            "centers_positive_depth_ft": centers,
            "corners_positive_depth_ft": corners,
            "native_bounding_box": {
                name: getattr(bbox, name)
                for name in ("min_x", "max_x", "min_y", "max_y", "min_z", "max_z")
            },
            "depth_range_ft": list(case.reservoir_depth_range()),
            "unit_limit": (
                "RIPS arrays carry no independent unit labels. "
                "FIELD source units and numeric dimensions establish this trial's interpretation."
            ),
        }
        write(self.output / "native-geometry.json", record)
        assert dimensions == reference["opm_dimensions"]
        assert counts.active_cell_count == counts.reservoir_cell_count == 300
        assert cells == reference["opm_active_cells"]
        assert all(item.grid_index == item.parent_grid_index == 0 for item in information)
        assert all(ijk(item.parent_ijk) == ijk(item.local_ijk) for item in information)
        grid = self.specification.grid
        tops = [
            grid.top_depth_ft + sum(layer.thickness_ft for layer in grid.layers[:k])
            for k in range(len(grid.layers))
        ]
        expected_centers = [
            [
                (i + 0.5) * grid.dx_ft,
                (j + 0.5) * grid.dy_ft,
                tops[k] + grid.layers[k].thickness_ft / 2,
            ]
            for i, j, k in cells
        ]
        expected_extents = [
            [grid.dx_ft, grid.dy_ft, grid.layers[k].thickness_ft] for _, _, k in cells
        ]
        expected_minima = [[i * grid.dx_ft, j * grid.dy_ft, tops[k]] for i, j, k in cells]
        corner_values = np.asarray(corners)
        errors = {
            "center_maximum_error_ft": float(
                np.max(np.abs(np.asarray(centers) - expected_centers))
            ),
            "corner_extent_maximum_error_ft": float(
                np.max(np.abs(np.ptp(corner_values, axis=1) - expected_extents))
            ),
            "corner_minimum_maximum_error_ft": float(
                np.max(np.abs(np.min(corner_values, axis=1) - expected_minima))
            ),
            "depth_range_maximum_error_ft": float(
                np.max(
                    np.abs(
                        np.asarray(record["depth_range_ft"])
                        - [
                            grid.top_depth_ft,
                            grid.top_depth_ft + sum(layer.thickness_ft for layer in grid.layers),
                        ]
                    )
                )
            ),
        }
        comparison = {
            "passed": all(error <= GEOMETRY_TOLERANCE_FT for error in errors.values()),
            "cells_compared": len(cells),
            "absolute_tolerance_ft": GEOMETRY_TOLERANCE_FT,
            "relative_tolerance": 0,
            "tolerance_basis": (
                "One millionth of a foot allows only native floating-point "
                "serialization rounding for exact integer-foot reference geometry."
            ),
            "errors": errors,
            "i_fastest_identity_matches": True,
        }
        write(self.output / "geometry-comparison.json", comparison)
        assert comparison["passed"], comparison
        self.event("geometry_verified", **comparison)

    def pressure(self, case: Any, reference: dict[str, Any]) -> int:
        self.event(
            "native_pressure_requested",
            methods=["time_steps", "days_since_start", "active_cell_property"],
            property="PRESSURE",
            category="DYNAMIC_NATIVE",
            report_days=2.0,
        )
        dates = case.time_steps()
        days = list(case.days_since_start())
        reports = [
            {
                "index": index,
                "days": elapsed,
                "date": f"{item.year:04}-{item.month:02}-{item.day:02}",
            }
            for index, (elapsed, item) in enumerate(zip(days, dates, strict=True))
        ]
        write(self.output / "native-reports.json", reports)
        indices = [
            item["index"]
            for item in reports
            if item["days"] == 2.0 and item["date"] == "2015-01-03"
        ]
        assert len(indices) == 1
        index = indices[0]
        assert isinstance(index, int)
        pressure = list(case.active_cell_property("DYNAMIC_NATIVE", "PRESSURE", index))
        write(
            self.output / "native-pressure.json",
            {
                "report_index": index,
                "report_days": 2.0,
                "values": pressure,
                "unit_interpretation": "PSIA from the preserved FIELD model and OPM comparison",
            },
        )
        assert len(pressure) == 300 and np.all(np.isfinite(pressure))
        difference = float(np.max(np.abs(np.asarray(pressure) - reference["pressure"])))
        result = {
            "passed": difference <= reference["pressure_absolute_tolerance"],
            "cells_compared": 300,
            "maximum_absolute_difference_psia": difference,
            "absolute_tolerance_psia": reference["pressure_absolute_tolerance"],
            "relative_tolerance": 0,
            "minimum_psia": min(pressure),
            "maximum_psia": max(pressure),
            "report_days": 2.0,
            "report_index": index,
        }
        write(self.output / "pressure-comparison.json", result)
        assert result["passed"], result
        self.event("pressure_verified", **result)
        return index

    def snapshot(self, case: Any, index: int) -> None:
        case.name_setting = "CUSTOM_NAME"
        case.name = "P08 generated FIELD pressure (psia), day 2"
        case.update()
        view = case.create_view()
        view.apply_cell_result("DYNAMIC_NATIVE", "PRESSURE")
        view.current_time_step = index
        view.grid_z_scale = 20
        view.disable_lighting = True
        view.show_grid_box = True
        view.update()
        view = case.view(view.id)
        legends = [
            item
            for item in view.cell_result().result_var_legend_definition_list()
            if item.result_variable_usage == "PRESSURE"
        ]
        assert len(legends) == 1
        legend = legends[0]
        legend.range_type = "USER_DEFINED_MAX_MIN"
        legend.mapping_mode = "LinearContinuous"
        legend.user_defined_min = 4000
        legend.user_defined_max = 5600
        legend.update()
        original = read_camera(
            view.camera_matrix,
            view.camera_point_of_interest,
            view.perspective_projection,
            view.actual_camera_field_of_view_y_degrees,
            view.actual_camera_parallel_projection_height,
        )
        distance = math.dist(original.position, original.target)
        camera = Camera(
            position=(
                original.target[0] + 0.6 * distance,
                original.target[1] - 0.6 * distance,
                original.target[2] + 0.6 * distance,
            ),
            target=original.target,
            up=(0, 0, 1),
            projection=Projection.PERSPECTIVE,
            field_of_view_degrees=40,
        )
        view.set_camera_projection(
            perspective=True, field_of_view_y_degrees=40, parallel_projection_height=1
        )
        view = case.view(view.id)
        view.camera_point_of_interest = list(camera.target)
        view.camera_matrix = view_matrix(camera)
        view.update()
        folder = self.output / "images"
        folder.mkdir()
        self.event(
            "snapshot_requested",
            width=1400,
            height=1000,
            pressure_legend_psia=[4000, 5600],
            vertical_exaggeration=20,
            camera=camera.model_dump(mode="json"),
        )
        view = case.view(view.id)
        assert view.current_time_step == index
        self.event("snapshot_time_verified", report_index=view.current_time_step, report_days=2.0)
        view.export_snapshot(export_folder=str(folder), width=1400, height=1000)
        images = list(folder.glob("*.png"))
        assert len(images) == 1
        with Image.open(images[0]) as picture:
            picture.load()
            assert picture.size == (1400, 1000)
        self.event(
            "snapshot_completed",
            path=str(images[0]),
            mcp_image_delivery=False,
            model_provider_transfer=False,
        )

    def run(self) -> None:
        reference = self.reference()
        self.application = RipsApplicationFactory(self.output / "native-logs").launch(
            self.executable
        )
        self.verify_owned("after launch")
        project = cast(Any, self.application.project())
        self.event("native_load_requested", method="Project.load_case", path=str(self.result_file))
        case = self.application.call(lambda: project.load_case(str(self.result_file)))
        self.event("native_load_completed", case_id=case.id, case_path=case.file_path)
        assert Path(case.file_path).resolve() == self.result_file.resolve()
        self.geometry(case, reference)
        index = self.pressure(case, reference)
        self.snapshot(case, index)

    def cleanup(self) -> None:
        if self.application is None:
            self.event("cleanup_not_attempted", reason="No verified launch receipt exists.")
            return
        process = self.verify_owned("before native Exit")
        identity = self.application.process
        try:
            self.application.terminate()
        finally:
            self.application.disconnect()
        assert not process.is_running()
        self.event(
            "cleanup_completed",
            identity=identity.model_dump(mode="json"),
            method="Verified owned native Exit",
            process_absent=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--numerical", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--native-commit", required=True)
    parser.add_argument("--native-build-record", type=Path, required=True)
    arguments = parser.parse_args()
    assert all(
        path.is_absolute() for path in (arguments.output, arguments.numerical, arguments.executable)
    )
    arguments.output.mkdir()
    source = Path(__file__).resolve().parents[3]
    native_build = json.loads(arguments.native_build_record.read_text())
    assert (
        native_build["native_commit"] == arguments.native_commit and native_build["exit_code"] == 0
    )
    shutil.copyfile(arguments.native_build_record, arguments.output / "native-build.json")
    write(
        arguments.output / "environment.json",
        {
            "started_at": datetime.now(UTC).isoformat(),
            "command": sys.argv,
            "source_commit": subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
            ).strip(),
            "working_tree": subprocess.check_output(
                ["git", "-C", str(source), "status", "--short"], text=True
            ).splitlines(),
            "native_commit": arguments.native_commit,
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {
                name: version(name) for name in ("rips", "opm", "numpy", "psutil", "Pillow")
            },
            "rips_module": rips.__file__,
            "pythonpath": os.environ.get("PYTHONPATH"),
            "qt_plugin_path": os.environ.get("QT_PLUGIN_PATH"),
            "scope": (
                "Standalone Python native readback. "
                "No MCP result loader, simulator run, or model-provider trial."
            ),
        },
    )
    trial = Trial(arguments.output, arguments.numerical, arguments.executable)
    passed = False
    try:
        trial.run()
        passed = True
    except BaseException as error:
        trial.event("acceptance_failed", error_type=type(error).__name__, message=str(error))
        raise
    finally:
        trial.cleanup()
        write(
            arguments.output / "result.json",
            {
                "passed": passed,
                "applications": 1,
                "mcp_result_loading": False,
                "model_provider_transfer": False,
                "native_editor_inspection": "Deferred under issue 34",
            },
        )


if __name__ == "__main__":
    main()
