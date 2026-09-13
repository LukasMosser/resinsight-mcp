"""Bound one trusted parser child with visible memory, disk, and time budgets."""

import json
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import psutil

from resinsight_mcp.models.general.arrays import AuthoringPolicy, fail

from .records import ValidationMetrics, ValidationSummary


def disk_mib(directory: Path) -> float:
    return sum(path.stat().st_size for path in directory.iterdir() if path.is_file()) / 1024**2


def require_limits(elapsed: float, peak: float, disk: float, policy: AuthoringPolicy) -> None:
    if elapsed > policy.parser_timeout_seconds:
        fail(
            "OPM validation exceeded the configured "
            f"{policy.parser_timeout_seconds:g}-second deadline."
        )
    if peak > policy.parser_memory_mib:
        fail(
            f"OPM validation exceeded the configured {policy.parser_memory_mib} MiB memory budget."
        )
    if disk > policy.compilation_disk_mib:
        fail(f"Compilation exceeded the configured {policy.compilation_disk_mib} MiB disk budget.")


def validate(
    root: Path, directory: Path, policy: AuthoringPolicy
) -> tuple[ValidationSummary, ValidationMetrics]:
    start, peak = time.monotonic(), 0.0
    with (directory / "validation.log").open("wb") as log:
        with subprocess.Popen(
            (
                sys.executable,
                "-I",
                "-m",
                "resinsight_mcp.models.general.compilation.worker",
                str(root),
                str(directory),
            ),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        ) as child:
            try:
                while child.poll() is None:
                    try:
                        peak = max(peak, psutil.Process(child.pid).memory_info().rss / 1024**2)
                    except psutil.NoSuchProcess:
                        # Process statistics can disappear before waitpid reports the exit.
                        try:
                            child.wait(timeout=0.02)
                        except subprocess.TimeoutExpired:
                            fail("The parser worker identity is unavailable.")
                    elapsed, disk = time.monotonic() - start, disk_mib(directory)
                    require_limits(elapsed, peak, disk, policy)
                    time.sleep(0.02)
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()
    report = directory / "validation.json"
    if not report.exists():
        with (directory / "validation.log").open() as log:
            detail = "".join(deque(log, maxlen=20))[-3000:]
        fail(
            f"OPM validation exited with status {child.returncode} "
            f"without a validation report. {detail}"
        )
    payload = json.loads(report.read_text())
    if "error" in payload:
        fail(f"OPM validation failed: {payload['error']}")
    if child.returncode != 0:
        fail(f"OPM validation exited with status {child.returncode}.")
    disk = disk_mib(directory)
    require_limits(time.monotonic() - start, peak, disk, policy)
    return ValidationSummary.model_validate(payload), ValidationMetrics(
        elapsed_seconds=time.monotonic() - start,
        peak_worker_memory_mib=peak,
        staged_disk_mib=disk,
        memory_limit_mib=policy.parser_memory_mib,
        timeout_seconds=policy.parser_timeout_seconds,
        disk_limit_mib=policy.compilation_disk_mib,
    )
