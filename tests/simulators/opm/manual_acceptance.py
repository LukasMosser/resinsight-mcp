"""Run the bounded Flow probe explicitly, or compare existing outputs without a launch."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from opm.io.ecl import EclFile, EGrid, eclArrType
from pydantic import BaseModel

from resinsight_mcp.contracts.errors import ContractError, Failure, OperationResult
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.jobs import Job, JobRef, JobRequest, JobState, ResourceLimits, Result
from resinsight_mcp.contracts.models import PreparedModel, Session
from resinsight_mcp.jobs._common import require
from resinsight_mcp.jobs._container import OwnedContainer
from resinsight_mcp.models.imports import (
    DerivedModelRequest,
    ImportReceipt,
    ImportRequest,
    OpmImportService,
)
from resinsight_mcp.simulators.opm import FlowConfiguration, FlowRunRecord, OpmFlowService
from resinsight_mcp.workspaces import SqliteWorkspaceStore

REPOSITORY = Path(__file__).resolve().parents[3]
REFERENCE = Path(__file__).parent / "data/reference"
TERMINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED, JobState.UNKNOWN}
TIMESTAMP_SOURCE = (
    "https://github.com/OPM/opm-common/blob/release/2026.04/final/"
    "opm/io/eclipse/OutputStream.cpp#L647-L682"
)


def write(path: Path, record: BaseModel | dict[str, Any]) -> None:
    payload = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def command(*arguments: str) -> str:
    return subprocess.run(
        arguments, check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()


def environment() -> dict[str, Any]:
    if command("git", "-C", str(REPOSITORY), "status", "--porcelain"):
        raise ValueError("Runtime acceptance requires a clean source worktree.")
    return {
        "source_commit": command("git", "-C", str(REPOSITORY), "rev-parse", "HEAD"),
        "at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {name: version(name) for name in ("opm", "numpy", "pydantic")},
        "tools": {name: command(name, "--version") for name in ("uv", "ruff", "ty")},
    }


def reference(job: Job) -> JobRef:
    return JobRef(session_id=job.model.session_id, job_id=job.job_id)


def inspect(job: Job) -> dict[str, Any] | None:
    if job.container_id is None:
        return None
    assert job.submission is not None
    snapshot = OwnedContainer(job.submission, job.container_id).inspect()
    if snapshot.state.running:
        raise RuntimeError("A terminal job still has a running owned container.")
    record = json.loads(command(job.submission.argv[0], "container", "inspect", job.container_id))[
        0
    ]
    return {
        "Id": record["Id"],
        "Image": record["Image"],
        "Name": record["Name"],
        "Config": {key: record["Config"][key] for key in ("Image", "Labels", "Cmd")},
        "State": record["State"],
        "Mounts": record["Mounts"],
        "HostConfig": {
            key: record["HostConfig"][key] for key in ("Memory", "NanoCpus", "NetworkMode")
        },
    }


@dataclass
class Probe:
    output: Path
    configuration: FlowConfiguration
    source: dict[str, Any]
    session_id: SessionId | None = None

    @property
    def workspace(self) -> Path:
        return self.output / "workspace"

    def service(self) -> OpmFlowService:
        return OpmFlowService(self.workspace, self.configuration)

    def submit(self, name: str, request: JobRequest) -> Job:
        path = self.output / f"{name}-request.json"
        write(path, request)
        completed = subprocess.run(
            (
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--output",
                str(self.output),
                "--docker",
                str(self.configuration.docker),
                "--submit-request",
                str(path),
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        (self.output / f"{name}-submit.json").write_text(completed.stdout)
        job = require(OperationResult[Job].model_validate_json(completed.stdout))
        return job

    def wait(self, job: Job, *, cancel: bool) -> Job:
        service = self.service()
        end = time.monotonic() + 90
        while time.monotonic() < end:
            job = require(service.poll(reference(job)))
            if (
                cancel
                and not job.cancel_requested
                and job.state == JobState.RUNNING
                and job.container_id
            ):
                require(service.request_cancel(reference(job)))
            if job.state in TERMINAL:
                return job
            time.sleep(0.05)
        raise RuntimeError("The trial did not reach a terminal state within 90 seconds.")

    def collect(self, name: str, job: Job) -> tuple[Result | None, Path | None]:
        service = self.service()
        assert require(service.poll(reference(job))) == job
        collected = service.collect(reference(job))
        write(self.output / f"{name}-collection.json", collected)
        if job.state != JobState.SUCCEEDED:
            assert isinstance(collected.outcome, Failure)
            return None, None
        result = require(collected)
        assert require(self.service().collect(reference(job))) == result
        assert job.submission is not None and job.submission.run_metadata is not None
        with service.store.open_artifact(job.submission.run_metadata) as stream:
            run = FlowRunRecord.model_validate_json(stream.read())
        outputs = run.directory / "outputs"
        dataset = require(service.verify_outputs(result, outputs))
        write(self.output / f"{name}-dataset.json", dataset)
        assert result.manifest is not None
        with service.store.open_artifact(result.manifest.assessment_evidence) as stream:
            (self.output / f"{name}-assessment.json").write_text(stream.read().decode())
        return result, outputs

    def run(
        self, name: str, prepared: PreparedModel, limits: ResourceLimits, *, cancel: bool = False
    ) -> dict[str, Any]:
        start = time.monotonic()
        job = self.wait(
            self.submit(name, JobRequest(prepared=prepared, limits=limits)), cancel=cancel
        )
        write(self.output / f"{name}-job.json", job)
        for index, ref in enumerate(job.logs):
            with self.service().store.open_artifact(ref) as stream:
                (self.output / f"{name}-log-{index}.log").write_text(stream.read().decode())
        container = inspect(job)
        write(self.output / f"{name}-container.json", {"container": container})
        result, outputs = self.collect(name, job)
        record = {
            "source_commit": self.source["source_commit"],
            "job": job.model_dump(mode="json"),
            "container": container,
            "elapsed_wall_seconds": time.monotonic() - start,
            "submission_client_exited": True,
            "fresh_service_poll_equal": True,
            "result": None if result is None else result.model_dump(mode="json"),
            "source_outputs": None if outputs is None else str(outputs),
        }
        write(self.output / f"{name}-trial.json", record)
        print(f"{name}: {job.state.value}, exit {job.exit_code}", flush=True)
        return record

    def cleanup(self) -> None:
        records = []
        if self.session_id is None:
            return
        for job in require(self.service().store.list_jobs(self.session_id)):
            ref = reference(job)
            try:
                assert job.submission is not None
                owned = OwnedContainer(job.submission, job.container_id)
                before = owned.find()
                if before is not None:
                    owned.stop()
                    owned.remove()
                absent = owned.find() is None
                if not absent:
                    raise RuntimeError("A verified removal did not establish container absence.")
                records.append(
                    {
                        "job": ref.model_dump(mode="json"),
                        "before": None if before is None else before.model_dump(mode="json"),
                        "absent": absent,
                    }
                )
            except (
                ContractError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                records.append({"job": ref.model_dump(mode="json"), "error": str(error)})
        write(self.output / "cleanup.json", {"records": records})
        if any("error" in record for record in records):
            raise RuntimeError("Owned container cleanup has failures; inspect cleanup.json.")


def derive(probe: Probe, base: ImportReceipt, name: str, old: str, new: str) -> ImportReceipt:
    imports = OpmImportService(probe.service().store)
    source = probe.output / f"{name}-source"
    with imports.materialize(base.prepared.revision.model) as materialized:
        shutil.copytree(materialized.directory, source)
    path = source / "includes/schedule.inc"
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError("The canonical schedule does not contain the expected single control.")
    path.write_text(text.replace(old, new))
    result = require(
        imports.derive_model(
            DerivedModelRequest(
                parent=base.prepared.revision.model,
                source_root=source,
                entrypoint="SPE1.DATA",
            )
        )
    )
    write(probe.output / f"{name}-receipt.json", result)
    return result


def compare(name: str, actual: Any, expected: Any, precision: str | None = None) -> dict[str, Any]:
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape:
        return {"name": name, "accepted": False, "reason": "shape differs"}
    if not np.issubdtype(expected.dtype, np.floating):
        return {
            "name": name,
            "accepted": bool(np.array_equal(actual, expected)),
            "count": int(expected.size),
            "comparison": "exact parsed identity",
        }
    finite = bool(np.all(np.isfinite(actual)) and np.all(np.isfinite(expected)))
    if not finite:
        return {"name": name, "accepted": False, "reason": "nonfinite values"}
    dtype = np.dtype(precision or expected.dtype)
    magnitude = np.asarray(np.max(np.abs(expected), initial=0), dtype=dtype)
    tolerance = 2 * abs(float(np.spacing(magnitude)))
    delta = float(
        np.max(np.abs(actual.astype(np.float64) - expected.astype(np.float64)), initial=0)
    )
    return {
        "name": name,
        "accepted": finite and bool(np.allclose(actual, expected, rtol=0, atol=tolerance)),
        "count": int(expected.size),
        "reference_dtype": str(dtype),
        "maximum_absolute_difference": delta,
        "absolute_tolerance": tolerance,
        "relative_tolerance": 0,
        "finite": finite,
    }


def compare_file(
    actual_path: Path, expected_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actual, expected = EclFile(str(actual_path)), EclFile(str(expected_path))
    extension = actual_path.suffix.removeprefix(".")
    checks = [{"name": f"{extension}:array_layout", "accepted": actual.arrays == expected.arrays}]
    timestamps = []
    if actual.arrays != expected.arrays:
        return checks, timestamps
    occurrences: dict[str, int] = defaultdict(int)
    for index, (name, kind, _) in enumerate(expected.arrays):
        occurrence = occurrences[name]
        occurrences[name] += 1
        if kind == eclArrType.MESS:
            continue
        values, reference_values = actual[index], expected[index]
        if extension == "SMSPEC" and name == "RUNTIMEI":
            timestamps.append(
                {
                    "name": "SMSPEC:RUNTIMEI compute start and write times",
                    "indices": list(range(3, 15)),
                    "actual": values[3:15].tolist(),
                    "reference": reference_values[3:15].tolist(),
                    "source": TIMESTAMP_SOURCE,
                }
            )
            checks.append(
                compare("SMSPEC:RUNTIMEI simulation state", values[:3], reference_values[:3])
            )
            checks.append(
                compare("SMSPEC:RUNTIMEI remaining metadata", values[15:], reference_values[15:])
            )
        else:
            checks.append(compare(f"{extension}:{name}:{occurrence}", values, reference_values))
    return checks, timestamps


def assess(actual: Path, expected: Path, output: Path) -> dict[str, Any]:
    checks, timestamps = [], []
    for extension in ("EGRID", "INIT", "UNRST", "SMSPEC", "UNSMRY"):
        file_checks, file_times = compare_file(
            actual / f"SPE1.{extension}", expected / f"SPE1.{extension}"
        )
        checks.extend(file_checks)
        timestamps.extend(file_times)
    actual_grid, reference_grid = (EGrid(str(path / "SPE1.EGRID")) for path in (actual, expected))
    checks.append(
        compare(
            "active-cell corners",
            [actual_grid.xyz_from_active_index(index) for index in range(actual_grid.active_cells)],
            [
                reference_grid.xyz_from_active_index(index)
                for index in range(reference_grid.active_cells)
            ],
            precision="float32",
        )
    )
    record = {
        "reference": str(expected),
        "reader_versions": {name: version(name) for name in ("opm", "numpy")},
        "rule": (
            "Two output-dtype increments at the largest absolute reference magnitude, "
            "with zero relative tolerance. Parsed simulation identities must match exactly."
        ),
        "accepted": all(check["accepted"] for check in checks),
        "checks": checks,
        "per_run_wall_clock_metadata": timestamps,
    }
    write(output, record)
    return record


def run_trials(probe: Probe, expected: Path) -> None:
    store = SqliteWorkspaceStore.create(probe.workspace)
    imports = OpmImportService(store)
    session = require(
        store.create_session(Session(session_id=SessionId.new(), name="P11 manual acceptance"))
    )
    probe.session_id = session.session_id
    base = require(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=REPOSITORY / "tests/models/imports/data/spe1",
                entrypoint="SPE1.DATA",
                datum="SPE1 local depth datum",
            )
        )
    )
    write(probe.output / "baseline-receipt.json", base)
    changed = derive(probe, base, "changed", "'ORAT' 20000", "'ORAT' 15000")
    long_run = derive(probe, base, "long", " 1 1 /", " 255*1 /")
    try:
        limits = ResourceLimits(cpu_count=2, memory_mib=2048, wall_time_seconds=60)
        baseline = probe.run("baseline", base.prepared, limits)
        assert baseline["job"]["state"] == "succeeded"
        assert assess(
            Path(baseline["source_outputs"]), expected, probe.output / "reference-assessment.json"
        )["accepted"]
        assert probe.run("changed", changed.prepared, limits)["job"]["state"] == "succeeded"
        canceled = probe.run(
            "canceled",
            long_run.prepared,
            ResourceLimits(cpu_count=1, memory_mib=2048, wall_time_seconds=60),
            cancel=True,
        )
        assert canceled["job"]["state"] == "canceled"
        assert canceled["job"]["exit_code"] == canceled["container"]["State"]["ExitCode"] == 137
        deadline = probe.run(
            "deadline",
            long_run.prepared,
            ResourceLimits(cpu_count=1, memory_mib=2048, wall_time_seconds=1),
        )
        assert (
            deadline["job"]["state"] == "failed"
            and "deadline" in deadline["job"]["error"]["message"]
        )
        assert deadline["job"]["exit_code"] == deadline["container"]["State"]["ExitCode"] == 137
        failed = probe.run(
            "memory-failure",
            base.prepared,
            ResourceLimits(cpu_count=1, memory_mib=16, wall_time_seconds=60),
        )
        assert failed["job"]["state"] == "failed" and failed["container"]["State"]["OOMKilled"]
    finally:
        probe.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New output directory, or comparison JSON with --assess-existing.",
    )
    parser.add_argument("--docker", type=Path, default=FlowConfiguration().docker)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument(
        "--assess-existing",
        type=Path,
        help="Compare this output directory without Docker or a workspace.",
    )
    parser.add_argument("--submit-request", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    configuration = FlowConfiguration(docker=args.docker)
    if args.submit_request:
        request = JobRequest.model_validate_json(args.submit_request.read_text())
        print(
            OpmFlowService(args.output / "workspace", configuration)
            .submit(request)
            .model_dump_json()
        )
    elif args.assess_existing:
        record = assess(args.assess_existing, args.reference, args.output)
        print(json.dumps({"accepted": record["accepted"], "checks": len(record["checks"])}))
        if not record["accepted"]:
            raise SystemExit(1)
    else:
        configuration.check_dependencies()
        source = environment()
        output = args.output.resolve()
        if output.is_relative_to(REPOSITORY):
            raise ValueError("Use an output directory outside the repository.")
        output.mkdir()
        write(output / "environment.json", source)
        write(
            output / "runtime-preflight.json",
            {
                "versions": configuration.runtime_versions(),
                "image": configuration.image,
                "platform": configuration.platform,
                "passed": True,
            },
        )
        run_trials(Probe(output, configuration, source), args.reference)


if __name__ == "__main__":
    main()
