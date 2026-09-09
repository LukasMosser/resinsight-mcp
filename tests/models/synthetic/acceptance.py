"""Compare repeated P07 and generated reference runs in the approved Flow image."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.models.imports import ImportReceipt, ImportRequest, OpmImportService
from resinsight_mcp.models.synthetic import (
    SyntheticModelRequest,
    SyntheticModelService,
    read_grid_id,
    read_specification,
    reference_specification,
)
from resinsight_mcp.workspaces import SqliteWorkspaceStore

IMAGE = (
    "openporousmedia/opmreleases@"
    "sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1"
)
WALL_LIMIT_SECONDS = 60
SUMMARY_UNITS = {"FOPR": "STB/DAY", "WBHP:PROD": "PSIA", "WBHP:INJ": "PSIA"}


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


def write_json(path: Path, record: Any) -> None:
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def command(arguments: list[str], log: Path, *, timeout: int = WALL_LIMIT_SECONDS) -> None:
    started = time.monotonic()
    record: dict[str, Any] = {"arguments": arguments, "wall_limit_seconds": timeout}
    try:
        with log.open("w") as output:
            result = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        record["exit_status"] = result.returncode
        assert result.returncode == 0, f"Command failed. Inspect {log}."
    except subprocess.TimeoutExpired:
        record["timed_out"] = True
        raise
    finally:
        record["wall_seconds"] = time.monotonic() - started
        write_json(log.with_suffix(".command.json"), record)


def flow_command(docker: str, arguments: list[str], log: Path, mounts: list[str]) -> None:
    container = f"resinsight-p08-{uuid4().hex}"
    invocation = [
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
        "--name",
        container,
        *mounts,
        IMAGE,
        "flow",
        *arguments,
    ]
    try:
        command(invocation, log)
    except subprocess.TimeoutExpired:
        command([docker, "rm", "--force", container], log.with_name("timeout-cleanup.log"))
        raise


def materialize(store: SqliteWorkspaceStore, receipt: ImportReceipt, destination: Path) -> str:
    revision = receipt.prepared.revision
    entrypoint = ""
    for artifact_id in revision.inputs.artifacts:
        ref = ArtifactRef(session_id=revision.model.session_id, artifact_id=artifact_id)
        artifact = value(store.get_artifact(ref))
        target = destination / artifact.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with store.open_artifact(ref) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
        if artifact_id == revision.inputs.entrypoint:
            entrypoint = artifact.relative_path
    assert entrypoint
    return entrypoint


def prepare_sources(output: Path) -> dict[str, str]:
    fixture = Path(__file__).resolve().parents[1] / "imports" / "data" / "spe1"
    store = SqliteWorkspaceStore.create(output / "workspace")
    baseline_session = value(
        store.create_session(Session(session_id=SessionId.new(), name="P08 preserved P07"))
    )
    generated_session = value(
        store.create_session(Session(session_id=SessionId.new(), name="P08 generated reference"))
    )
    baseline = value(
        OpmImportService(store).import_model(
            ImportRequest(
                session_id=baseline_session.session_id,
                source_root=fixture,
                entrypoint="SPE1.DATA",
                datum="SPE1 local depth datum",
            )
        )
    )
    generated = value(
        SyntheticModelService(store).create_model(
            SyntheticModelRequest(
                session_id=generated_session.session_id,
                datum="SPE1 local depth datum",
                specification=reference_specification(),
            )
        )
    )
    write_json(output / "generated-receipt.json", generated.model_dump(mode="json"))
    sources = {}
    for name, receipt in (("p07", baseline), ("generated", generated.imported)):
        sources[name] = materialize(store, receipt, output / "sources" / name)
        write_json(output / f"{name}-import.json", receipt.model_dump(mode="json"))
        with store.open_artifact(receipt.record) as source:
            write_json(output / f"{name}-source-record.json", json.load(source))
    write_json(output / "source-entrypoints.json", sources)
    return sources


def input_record(entrypoint: Path) -> dict[str, Any]:
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import Parser
    from opm.io.schedule import Schedule

    deck = Parser().parse(str(entrypoint))
    state = EclipseState(deck)
    schedule = Schedule(deck, state)
    grid = state.grid()
    properties = {
        name: [float(item) for item in deck[name].get_raw_array()]
        for name in ("DX", "DY", "DZ", "TOPS", "PORO", "PERMX", "PERMY", "PERMZ")
    }
    physics = {
        name: [
            {
                item.name(): item.get_raw_data_list() if item.is_double() else item.value
                for item in record
                if item.valid
            }
            for record in deck[name]
        ]
        for name in (
            "PVTW",
            "ROCK",
            "SWOF",
            "SGOF",
            "DENSITY",
            "PVDG",
            "PVTO",
            "EQUIL",
            "RSVD",
            "DRSDT",
        )
    }
    connections = {
        well.name: [[cell.i, cell.j, cell.k] for cell in well.connections()]
        for well in schedule.get_wells(len(schedule.reportsteps) - 1)
    }
    assert connections == {"PROD": [[9, 9, 2]], "INJ": [[0, 0, 0]]}
    assert grid.nactive == 300
    return {
        "unit_system": "FIELD",
        "dimensions": [grid.nx, grid.ny, grid.nz],
        "active_cells": [list(grid.getIJK(index)) for index in range(grid.nactive)],
        "connections_zero_based": connections,
        "report_dates": [item.isoformat() for item in schedule.reportsteps],
        "properties": properties,
        "physics_inputs_in_field_units": physics,
    }


def result_record(root: Path, entrypoint: str) -> dict[str, Any]:
    from opm.io.ecl import EGrid, ERst, ESmry

    basename = root / "results" / Path(entrypoint).stem
    grid = EGrid(str(basename.with_suffix(".EGRID")))
    restart = ERst(str(basename.with_suffix(".UNRST")))
    summary = ESmry(str(basename.with_suffix(".SMSPEC")))
    assert tuple(grid.dimension) == (10, 10, 3)
    assert grid.active_cells == 300
    assert {1, 2} <= set(restart.report_steps)
    assert summary.units("TIME").strip() == "DAYS"
    report_times = [float(item) for item in summary["TIME", True]]
    assert report_times == [1.0, 2.0]
    quantities = {}
    for step in (1, 2):
        values = restart["PRESSURE", step]
        assert len(values) == grid.active_cells and np.all(np.isfinite(values))
        quantities[f"PRESSURE:{step}"] = {
            "unit": "PSIA",
            "elapsed_days": float(step),
            "dtype": str(values.dtype),
            "values": [float(item) for item in values],
            "minimum": float(np.min(values)),
            "maximum": float(np.max(values)),
        }
    for name, unit in SUMMARY_UNITS.items():
        assert summary.units(name).strip() == unit
        values = summary[name, True]
        assert len(values) == 2 and np.all(np.isfinite(values))
        quantities[name] = {
            "unit": unit,
            "elapsed_days": report_times,
            "dtype": str(values.dtype),
            "values": [float(item) for item in values],
        }
    return {
        "dimensions": list(grid.dimension),
        "active_cells": [list(grid.ijk_from_active_index(index)) for index in range(300)],
        "report_dates": [
            (summary.start_date + timedelta(days=item)).isoformat() for item in report_times
        ],
        "quantities": quantities,
        "output_files": sorted(item.name for item in (root / "results").iterdir()),
    }


def compare(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    assert reference["active_cells"] == candidate["active_cells"]
    assert reference["report_dates"] == candidate["report_dates"]
    comparisons = {}
    for name, quantity in reference["quantities"].items():
        other = candidate["quantities"][name]
        assert quantity["unit"] == other["unit"]
        assert quantity["elapsed_days"] == other["elapsed_days"]
        reference_values = np.array(quantity["values"])
        candidate_values = np.array(other["values"])
        magnitude = np.array(np.max(np.abs(reference_values)), dtype=quantity["dtype"])
        tolerance = 2 * float(np.spacing(magnitude))
        difference = float(np.max(np.abs(reference_values - candidate_values)))
        comparisons[name] = {
            "unit": quantity["unit"],
            "elapsed_days": quantity["elapsed_days"],
            "absolute_tolerance": tolerance,
            "relative_tolerance": 0,
            "maximum_absolute_difference": difference,
            "passed": difference <= tolerance,
        }
    return comparisons


def analyze(output: Path, sources: dict[str, str]) -> None:
    inputs = {
        name: input_record(output / "sources" / name / entrypoint)
        for name, entrypoint in sources.items()
    }
    assert inputs["p07"] == inputs["generated"]
    generated_text = (output / "sources" / "generated" / sources["generated"]).read_text()
    specification = read_specification(generated_text)
    receipt = json.loads((output / "generated-receipt.json").read_text())
    assert str(read_grid_id(generated_text)) == receipt["active_cells"]["grid_id"]
    assert specification == reference_specification()
    write_json(output / "input-semantics.json", inputs)
    results = {}
    for name, entrypoint in sources.items():
        for repeat in (1, 2):
            run = f"{name}-{repeat}"
            results[run] = result_record(output / run, entrypoint)
            assert results[run]["active_cells"] == inputs[name]["active_cells"]
    write_json(output / "numerical-values.json", results)
    comparisons = {
        "p07_repeatability": compare(results["p07-1"], results["p07-2"]),
        "generated_repeatability": compare(results["generated-1"], results["generated-2"]),
        "generated_against_p07": compare(results["p07-1"], results["generated-1"]),
    }
    passed = all(
        item["passed"] for comparison in comparisons.values() for item in comparison.values()
    )
    write_json(
        output / "comparison.json",
        {
            "passed": passed,
            "tolerance_basis": (
                "Two representable output increments at the largest reference magnitude, "
                "using the dtype returned by OPM's reader. Relative tolerance is zero. "
                "Measured repeat differences do not enlarge this tolerance."
            ),
            "comparisons": comparisons,
        },
    )
    assert passed, "Numerical values exceed the declared output-precision tolerance."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir()
    record: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "tested_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree": subprocess.check_output(
            ["git", "status", "--short"], text=True
        ).splitlines(),
        "host": platform.platform(),
        "python": sys.version,
        "packages": {name: version(name) for name in ("opm", "numpy", "pydantic")},
        "flow_image": IMAGE,
        "limits": {
            "cpus": 2,
            "memory": "2g",
            "network": "none",
            "wall_seconds": WALL_LIMIT_SECONDS,
        },
        "scope": "Python service numerical acceptance without ResInsight or MCP simulation.",
        "data_terms": "SPE1: copyright 2015 Statoil, ODbL 1.0, Database Contents License 1.0.",
    }
    try:
        command([arguments.docker, "version"], output / "docker-version.log")
        command([arguments.docker, "image", "inspect", IMAGE], output / "image-inspect.log")
        flow_command(arguments.docker, ["--version"], output / "flow-version.log", [])
        sources = prepare_sources(output)
        for name, entrypoint in sources.items():
            for repeat in (1, 2):
                run = output / f"{name}-{repeat}"
                run.mkdir()
                shutil.copytree(output / "sources" / name, run / "inputs")
                (run / "results").mkdir()
                flow_command(
                    arguments.docker,
                    [f"/input/{entrypoint}", "--output-dir=/output"],
                    run / "flow.log",
                    [
                        "--mount",
                        f"type=bind,source={run / 'inputs'},target=/input,readonly",
                        "--mount",
                        f"type=bind,source={run / 'results'},target=/output",
                    ],
                )
        analyze(output, sources)
        record["passed"] = True
    except Exception as error:
        record["passed"] = False
        record["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "acceptance.json", record)


if __name__ == "__main__":
    main()
