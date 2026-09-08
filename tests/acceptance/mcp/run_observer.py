"""Run one blind marker observation through the bundled Codex CLI."""

import argparse
import base64
import binascii
import json
import os
import platform
import subprocess
import sys
import tempfile
import uuid
from importlib.metadata import version
from io import BytesIO
from pathlib import Path

from mcp.types import ImageContent
from PIL import Image
from pydantic import ValidationError

import resinsight_mcp
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.observations import Observation

HERE = Path(__file__).resolve().parent
PROMPT = (
    "Call the observation_get tool from p05_image exactly once. "
    "Read the red marker's row and column from the returned image. "
    "Rows count from top to bottom and columns count from left to right. "
    "If code mode is required, use it only to call observation_get "
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


def command(
    codex: Path, observer: Path, evidence: Path, mode: str, ids: dict[str, str]
) -> list[str]:
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
        "mcp_servers.p05_image.command": json.dumps(sys.executable),
        "mcp_servers.p05_image.args": json.dumps(
            [
                str(HERE / "marker_service.py"),
                "--evidence",
                str(evidence),
                "--mode",
                mode,
                "--session-id",
                ids["session_id"],
                "--observation-id",
                ids["observation_id"],
            ]
        ),
        "mcp_servers.p05_image.required": "true",
        "mcp_servers.p05_image.enabled_tools": '["observation_get"]',
    }
    for key, value in settings.items():
        result.extend(("-c", f"{key}={value}"))
    for feature in DISABLED_FEATURES:
        result.extend(("--disable", feature))
    return [*result, PROMPT + " Use these exact arguments: " + json.dumps(ids)]


def run(codex: Path, evidence: Path, mode: str) -> int:
    """Capture the observer result without reading the hidden witness."""
    evidence.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["PATH"] = str(codex.parent) + os.pathsep + environment.get("PATH", "")
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        environment.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="resinsight-p05-observer-") as directory:
        ids = {
            "session_id": "session_" + uuid.uuid4().hex,
            "observation_id": "observation_" + uuid.uuid4().hex,
        }
        invocation = command(codex, Path(directory), evidence, mode, ids)
        metadata = {
            "command": invocation,
            "production_package": str(Path(resinsight_mcp.__file__).resolve()),
            "codex": subprocess.check_output(
                [str(codex), "--version"], env=environment, text=True
            ).strip(),
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
        return audit(evidence, mode, ids, completed.returncode)


def valid_content(response: dict, mode: str, ids: dict[str, str]) -> bool:
    """Require matching typed metadata and an image the model can receive."""
    try:
        content = response["content"]
        structured = response["structured_content"]
        result = OperationResult[Observation].model_validate_json(json.dumps(structured))
        if json.loads(content[0]["text"]) != structured:
            return False
        if isinstance(result.outcome, Success):
            observation = result.outcome.value
            if (str(observation.observation_id), str(observation.context.model.session_id)) != (
                ids["observation_id"],
                ids["session_id"],
            ):
                return False
            if mode == "visible":
                image = ImageContent.model_validate(content[1])
                if image.mimeType != "image/png":
                    return False
                if image.annotations is not None and image.annotations.audience is not None:
                    if "assistant" not in image.annotations.audience:
                        return False
                with Image.open(BytesIO(base64.b64decode(image.data, validate=True))) as decoded:
                    decoded.load()
                    return decoded.format == "PNG" and decoded.size == (
                        observation.image.width,
                        observation.image.height,
                    )
            return mode == "hidden"
        return mode == "empty" and result.outcome.error.code == "render_failed"
    except (KeyError, IndexError, TypeError, ValueError, OSError, ValidationError, binascii.Error):
        return False


def valid_final(events: list[dict], answer: dict) -> bool:
    """Require the final answer after the completed observation call."""
    completed = [
        (index, event["item"])
        for index, event in enumerate(events)
        if event.get("type") == "item.completed"
    ]
    calls = [index for index, item in completed if item.get("type") == "mcp_tool_call"]
    messages = [(index, item) for index, item in completed if item.get("type") == "agent_message"]
    if len(calls) != 1 or not messages or messages[-1][0] <= calls[0]:
        return False
    if not events or events[-1].get("type") != "turn.completed":
        return False
    try:
        return json.loads(messages[-1][1]["text"]) == answer
    except (KeyError, TypeError, ValueError):
        return False


def audit(evidence: Path, mode: str, ids: dict[str, str], exit_code: int) -> int:
    """Reject wrong answers, missing images, and unauthorized tool calls."""
    if exit_code != 0:
        (evidence / "audit.json").write_text(
            json.dumps({"passed": False, "exit_code": exit_code}) + "\n"
        )
        return 1
    answer = json.loads((evidence / "answer.json").read_text())
    events = [json.loads(line) for line in (evidence / "events.jsonl").read_text().splitlines()]
    items = [event["item"] for event in events if event.get("type") == "item.completed"]
    calls = [item for item in items if item.get("type") == "mcp_tool_call"]
    forbidden = [
        item
        for item in items
        if item.get("type") not in ("mcp_tool_call", "agent_message", "reasoning")
    ]
    witness = json.loads((evidence / "witness.json").read_text())
    expected = (
        {"status": "observed", **witness}
        if mode == "visible"
        else {"status": "no_image", "row": None, "column": None}
    )
    response = calls[0].get("result", {}) if len(calls) == 1 else {}
    server_result = json.loads((evidence / "server-content.json").read_text())
    content = response.get("content", [])
    types = [item["type"] for item in content]
    required = ["text", "image"] if mode == "visible" else ["text"]
    passed = (
        exit_code == 0
        and valid_content(response, mode, ids)
        and valid_final(events, answer)
        and answer == expected
        and not forbidden
        and len(calls) == 1
        and calls[0].get("server") == "p05_image"
        and calls[0].get("tool") == "observation_get"
        and calls[0].get("arguments") == ids
        and types == required
        and server_result.get("isError") == (mode == "empty")
        and calls[0].get("status") == ("failed" if mode == "empty" else "completed")
    )
    report = {
        "passed": passed,
        "mode": mode,
        "answer": answer,
        "expected": expected,
        "content_types": types,
        "completed_mcp_calls": len(calls),
        "forbidden_items": forbidden,
    }
    (evidence / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--mode", choices=("visible", "empty", "hidden"), required=True)
    arguments = parser.parse_args()
    sys.exit(run(arguments.codex.resolve(), arguments.evidence.resolve(), arguments.mode))
