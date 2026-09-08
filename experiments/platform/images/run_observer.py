"""Run one blind marker observation through the bundled Codex CLI."""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT = (
    "Call the observe tool from p01_image exactly once. "
    "Read the red marker's row and column from the returned image. "
    "Rows count from top to bottom and columns count from left to right. "
    "If code mode is required, use it only to call observe "
    "and forward its image content unchanged. "
    "Do not use any other tools, files, or resources. "
    "Return status observed with the row and column if you receive the image. "
    "If no image reaches you, return status no_image with null row and column instead of guessing."
)
DISABLED_FEATURES = (
    "apps",
    "plugins",
    "hooks",
    "browser_use",
    "computer_use",
    "multi_agent",
    "unified_exec",
    "image_generation",
    "view_image",
    "tool_suggest",
    "skill_search",
)


def command(codex: Path, observer: Path, evidence: Path) -> list[str]:
    """Build temporary configuration without changing the user's files."""
    result = [
        str(codex),
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--strict-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(observer),
        "--model",
        "gpt-6-astra",
        "--output-schema",
        str(HERE / "answer-schema.json"),
        "--output-last-message",
        str(evidence / "answer.json"),
        "--json",
    ]
    settings = {
        "model_reasoning_effort": '"low"',
        "forced_login_method": '"chatgpt"',
        "web_search": '"disabled"',
        "features.shell_tool": "false",
        "mcp_servers.p01_image.command": json.dumps(sys.executable),
        "mcp_servers.p01_image.args": json.dumps(
            [str(HERE / "marker_server.py"), "--evidence", str(evidence)]
        ),
        "mcp_servers.p01_image.required": "true",
        "mcp_servers.p01_image.enabled_tools": '["observe"]',
    }
    for key, value in settings.items():
        result.extend(("-c", f"{key}={value}"))
    for feature in DISABLED_FEATURES:
        result.extend(("--disable", feature))
    return [*result, PROMPT]


def run(codex: Path, evidence: Path) -> int:
    """Capture the observer result without reading the hidden witness."""
    evidence.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["PATH"] = str(codex.parent) + os.pathsep + environment.get("PATH", "")
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        environment.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="resinsight-p01-observer-") as directory:
        invocation = command(codex, Path(directory), evidence)
        metadata = {
            "command": invocation,
            "python": sys.version,
            "macos": platform.mac_ver()[0],
            "machine": platform.machine(),
            "mcp": version("mcp"),
            "Pillow": version("Pillow"),
            "api_key_environment_removed": ["OPENAI_API_KEY", "CODEX_API_KEY"],
            "observer_directory_initially_empty": not any(Path(directory).iterdir()),
        }
        (evidence / "invocation.json").write_text(json.dumps(metadata, indent=2) + "\n")
        with (evidence / "events.jsonl").open("w") as events:
            with (evidence / "client.log").open("w") as log:
                completed = subprocess.run(
                    invocation,
                    env=environment,
                    stdout=events,
                    stderr=log,
                    timeout=180,
                    check=False,
                )
        (evidence / "exit-code.txt").write_text(f"{completed.returncode}\n")
        return completed.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    sys.exit(run(arguments.codex.resolve(), arguments.evidence.resolve()))
