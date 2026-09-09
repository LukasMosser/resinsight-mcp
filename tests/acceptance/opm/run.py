"""Run the reviewed public MCP acceptance after separate native runtime authorization."""

import argparse
import asyncio
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from native_steps import Native
from public_client import Evidence, PublicClient, TrialFailure, connect, write
from workflow_steps import Workflow

REPOSITORY = Path(__file__).resolve().parents[3]


def command(arguments: list[str]) -> str:
    return subprocess.run(
        arguments, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def versions(arguments: argparse.Namespace) -> dict[str, Any]:
    script = """
import importlib.metadata as metadata
import json
import platform
import sys
packages = {}
names = ('resinsight-mcp', 'rips', 'opm', 'numpy', 'mcp',
         'grpcio', 'protobuf', 'pillow', 'pydantic')
for name in names:
    package = metadata.distribution(name)
    packages[name] = {'version': package.version, 'location': str(package.locate_file('')),
                      'direct_url': json.loads(package.read_text('direct_url.json') or 'null')}
print(json.dumps({'python': sys.version, 'executable': sys.executable,
                  'platform': platform.platform(), 'packages': packages}))
"""
    installed = json.loads(command([str(arguments.python), "-I", "-c", script]))
    for name in ("resinsight-mcp", "rips"):
        origin = installed["packages"][name]["direct_url"]
        if origin is None or origin.get("dir_info", {}).get("editable"):
            raise TrialFailure(f"{name} requires a recorded noneditable installation.")
    if installed["packages"]["opm"]["version"] != "2025.10":
        raise TrialFailure("The acceptance requires the reviewed OPM 2025.10 reader.")
    return {
        "arguments": vars(arguments)
        | {name: str(value) for name, value in vars(arguments).items() if isinstance(value, Path)},
        "driver_commit": command(["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"]),
        "driver_python": sys.version,
        "driver_platform": platform.platform(),
        "installed_application_source_commit": arguments.source_commit,
        "native_source_status": command(
            ["git", "-C", str(arguments.native_source), "status", "--porcelain"]
        ),
        "native_source_commit": command(
            ["git", "-C", str(arguments.native_source), "rev-parse", "HEAD"]
        ),
        "installed_runtime": installed,
        "command": [sys.executable, *sys.argv],
    }


async def cleanup(api: PublicClient, workflow: Workflow) -> None:
    errors = []
    for name, operation in (("jobs", workflow.jobs.cleanup), ("ResInsight", workflow.native.close)):
        try:
            await operation(api)
        except Exception as error:
            errors.append({"owner": name, "error": repr(error)})
    write(
        api.evidence.output / "public-cleanup.json", {"errors": errors, "emergency_actions": False}
    )
    if errors:
        raise TrialFailure(
            "Public cleanup failed. Review the recorded ownership before emergency action."
        )


async def trial(arguments: argparse.Namespace, evidence: Evidence) -> None:
    workflow = Workflow(Native("session_" + uuid4().hex, arguments.executable))
    try:
        async with connect(arguments, evidence, create=True) as api:
            try:
                await workflow.initial(api)
                await workflow.before_disconnect(api)
            except BaseException:
                await cleanup(api, workflow)
                raise
        async with connect(arguments, evidence, create=False) as api:
            try:
                await workflow.after_disconnect(api)
            finally:
                await cleanup(api, workflow)
    except BaseException as error:
        write(
            evidence.output / "failure.json",
            {
                "error": repr(error),
                "accepted": False,
                "outstanding_native_connection": workflow.native.connection,
                "known_jobs": list(workflow.jobs.known.values()),
                "emergency_cleanup": (
                    "No direct runtime action was attempted. "
                    "Verify exact recorded identities before any emergency action."
                ),
            },
        )
        raise
    write(
        evidence.output / "acceptance.json",
        {
            "automated_checks_passed": True,
            "acceptance_complete": False,
            "check_count": len(evidence.checks),
            "public_tool_calls": evidence.calls,
            "sessions": [workflow.native.session_id, workflow.foreign_id],
            "results": workflow.results,
            "native_cleanup": "public application_close with verified lifetime end",
            "job_cleanup": "public terminal job records; stopped containers retained",
            "selected_wells": (
                "References establish existence. They do not establish exclusive visibility."
            ),
            "image_review": "Pending separate visual inspection of the saved PNGs.",
            "numerical_scope": (
                "Complete public arrays, controls, identity, and native result verification. "
                "No independent simulator accuracy claim."
            ),
        },
    )


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        type=Path,
        required=True,
        help="Installed interpreter used by the shipped launcher.",
    )
    parser.add_argument(
        "--executable", type=Path, required=True, help="Exact approved ResInsight executable."
    )
    parser.add_argument(
        "--docker", type=Path, required=True, help="Absolute approved Docker executable."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Unused absolute evidence directory outside the repository.",
    )
    parser.add_argument(
        "--source-commit",
        required=True,
        help="Full application source commit used to build the installed wheel.",
    )
    parser.add_argument(
        "--native-source",
        type=Path,
        required=True,
        help="Native source checkout for exact build provenance.",
    )
    result = parser.parse_args()
    for name in ("python", "executable", "docker", "output", "native_source"):
        path = getattr(result, name)
        if not path.is_absolute():
            parser.error(f"--{name.replace('_', '-')} requires an absolute path.")
    if not re.fullmatch("[0-9a-f]{40}", result.source_commit):
        parser.error("--source-commit requires a complete lowercase Git commit.")
    if result.output.exists() or result.output.resolve().is_relative_to(REPOSITORY):
        parser.error("--output must be unused and outside the repository.")
    if command(["git", "-C", str(REPOSITORY), "status", "--porcelain"]):
        parser.error("Runtime acceptance requires a clean driver source worktree.")
    return result


def main() -> None:
    options = arguments()
    provenance = versions(options)
    options.output.mkdir()
    for name in ("calls", "native-logs"):
        (options.output / name).mkdir()
    write(options.output / "versions.json", provenance)
    evidence = Evidence(options.output)
    asyncio.run(trial(options, evidence))


if __name__ == "__main__":
    main()
