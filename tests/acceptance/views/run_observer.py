"""Run a model through real native view changes and audit its received images."""

import argparse
import base64
import binascii
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Self

from mcp.types import CallToolResult, ImageContent
from PIL import Image
from pydantic import Field, ValidationError, model_validator

import resinsight_mcp
from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import ResultId, SessionId
from resinsight_mcp.contracts.observations import (
    EditedView,
    Observation,
    ViewContext,
    ViewEditReceipt,
    ViewUpdateRequest,
)
from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ObjectRef, ProjectState
from resinsight_mcp.mcp.catalog import ViewRenderRequest
from resinsight_mcp.resinsight.views._camera import camera_matches

HERE = Path(__file__).resolve().parent
DESCRIPTION_FIELDS = (
    "pressure_change",
    "saturation_display",
    "filtered_geometry_change",
    "control_view_change",
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
PROMPT = (
    "Use only project_inspect, view_apply, and view_render from p06_views. "
    "Call project_inspect exactly once with the supplied session_id. "
    "Resolve the exact case, target view, control view, and well names from its objects. "
    "Use their complete returned references without inventing identifiers. "
    "For each request, add the case and view references to context. "
    "Set selected_wells to a list containing the named well reference. "
    "Call view_apply for the five requests in their given order. "
    "Use each supplied width and height. "
    "Retain the observation.context from the second call, which changes the control view. "
    "Then call view_render exactly once with the unchanged control context and session_id. "
    "Use width 1200 and height 800. "
    "Receive and inspect all six returned native images before answering. "
    "If code mode is required, use it only for these calls. "
    "Forward their image content unchanged. "
    "Do not use files, resources, or other tools. "
    "Describe pressure changes between target images one and three. "
    "Include visible spatial and color facts. "
    "Describe the saturation display in target image four using visible spatial and color facts. "
    "Describe the visible geometry and camera changes between target images four and five. "
    "Describe any visible control-view change between image two and the final control image. "
    "Do not infer visual changes from metadata alone. "
    "Use the images to support each spatial and color description. "
    "If any image is missing or hidden, return status no_image and null for all four descriptions. "
    "Otherwise return status observed and the four descriptions in the required JSON answer."
)


class TrialRequest(Record):
    view_name: Text
    context: dict[str, Any]
    width: Literal[1200]
    height: Literal[800]

    @model_validator(mode="after")
    def check_unresolved_references(self) -> Self:
        if {"case", "view", "selected_wells"} & self.context.keys():
            raise ValueError("Trial contexts must omit object references until project inspection.")
        return self


class Trial(Record):
    workspace: Path
    application_logs: Path
    endpoint: Endpoint
    session_id: SessionId
    result_id: ResultId
    case_name: Text
    target_view_name: Text
    control_view_name: Text
    well_name: Text
    requests: tuple[TrialRequest, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def check_trial(self) -> Self:
        if not self.workspace.is_absolute() or not self.application_logs.is_absolute():
            raise ValueError("Trial paths must be absolute.")
        if self.target_view_name == self.control_view_name:
            raise ValueError("The target and control views must have different names.")
        names = tuple(item.view_name for item in self.requests)
        if names != (
            self.target_view_name,
            self.control_view_name,
            self.target_view_name,
            self.target_view_name,
            self.target_view_name,
        ):
            raise ValueError("The trial requires the target, control, and three target requests.")
        if tuple(item.context.get("scene_version") for item in self.requests) != (0, 0, 1, 2, 3):
            raise ValueError(
                "The trial must advance target scenes while retaining the control scene."
            )
        return self

    def observer_input(self) -> dict[str, Any]:
        """Expose requested settings and names without filesystem or application log access."""
        return self.model_dump(
            mode="json", exclude={"workspace", "application_logs", "endpoint", "result_id"}
        )


def exact_object(project: ProjectState, kind: ObjectKind, name: str) -> ObjectRef:
    matches = [item.ref for item in project.objects if item.ref.kind == kind and item.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {kind} named {name!r}.")
    return matches[0]


def requested_context(trial: Trial, project: ProjectState, item: TrialRequest) -> ViewContext:
    return ViewContext.model_validate_json(
        json.dumps(
            {
                **item.context,
                "case": exact_object(project, ObjectKind.CASE, trial.case_name).model_dump(
                    mode="json"
                ),
                "view": exact_object(project, ObjectKind.VIEW, item.view_name).model_dump(
                    mode="json"
                ),
                "selected_wells": [
                    exact_object(project, ObjectKind.WELL, trial.well_name).model_dump(mode="json")
                ],
            }
        )
    )


def command(codex: Path, observer: Path, evidence: Path, manifest: Path, trial: Trial) -> list[str]:
    """Use isolated configuration and the user's existing ChatGPT login."""
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
    inherited_paths = [item for item in os.environ.get("PYTHONPATH", "").split(os.pathsep) if item]
    python_path = os.pathsep.join(
        (
            str(HERE.parent),
            *inherited_paths,
            str(Path(resinsight_mcp.__file__).resolve().parents[1]),
        )
    )
    settings = {
        "model_reasoning_effort": '"low"',
        "forced_login_method": '"chatgpt"',
        "web_search": '"disabled"',
        "features.shell_tool": "false",
        "mcp_servers.p06_views.command": json.dumps(sys.executable),
        "mcp_servers.p06_views.args": json.dumps(
            ["-m", "views.server", "--trial", str(manifest), "--evidence", str(evidence)]
        ),
        "mcp_servers.p06_views.env.PYTHONPATH": json.dumps(python_path),
        "mcp_servers.p06_views.required": "true",
        "mcp_servers.p06_views.enabled_tools": '["project_inspect","view_apply","view_render"]',
        "mcp_servers.p06_views.tools.view_apply.approval_mode": '"approve"',
        "mcp_servers.p06_views.tools.view_render.approval_mode": '"approve"',
    }
    for key, value in settings.items():
        result.extend(("-c", f"{key}={value}"))
    for feature in DISABLED_FEATURES:
        result.extend(("--disable", feature))
    return [*result, PROMPT + " Trial: " + json.dumps(trial.observer_input())]


def run(codex: Path, manifest: Path, evidence: Path) -> int:
    """Record the model run; successful transport still requires separate visual review."""
    trial = Trial.model_validate_json(manifest.read_text())
    evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(manifest, evidence / "trial.json")
    environment = os.environ.copy()
    environment["PATH"] = str(codex.parent) + os.pathsep + environment.get("PATH", "")
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        environment.pop(key, None)
    source = Path(resinsight_mcp.__file__).resolve().parent
    shutil.copytree(
        source, evidence / "source" / "resinsight_mcp", ignore=shutil.ignore_patterns("__pycache__")
    )
    with tempfile.TemporaryDirectory(prefix="resinsight-p06-observer-") as directory:
        invocation = command(codex, Path(directory), evidence, evidence / "trial.json", trial)
        metadata = {
            "command": invocation,
            "production_package": str(source),
            "source_commit": subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
            ).strip(),
            "source_status": subprocess.check_output(
                ["git", "-C", str(source), "status", "--short"], text=True
            ),
            "source_snapshot": "source/resinsight_mcp",
            "codex": subprocess.check_output(
                [str(codex), "--version"], env=environment, text=True
            ).strip(),
            "python": sys.version,
            "macos": platform.mac_ver()[0],
            "machine": platform.machine(),
            "mcp": version("mcp"),
            "Pillow": version("Pillow"),
            "rips": version("rips"),
            "api_key_environment_removed": ["OPENAI_API_KEY", "CODEX_API_KEY"],
            "observer_directory_initially_empty": not any(Path(directory).iterdir()),
        }
        (evidence / "invocation.json").write_text(json.dumps(metadata, indent=2) + "\n")
        with (
            (evidence / "events.jsonl").open("w") as events,
            (evidence / "client.log").open("w") as log,
        ):
            try:
                completed = subprocess.run(
                    invocation, env=environment, stdout=events, stderr=log, timeout=600, check=False
                )
                exit_code = completed.returncode
            except subprocess.TimeoutExpired:
                exit_code = 124
        (evidence / "exit-code.txt").write_text(f"{exit_code}\n")
    return audit(evidence, trial, exit_code)


def structured_value[T](response: dict, result_type: type[OperationResult[T]]) -> T:
    """Require text and structured content to describe the same successful typed result."""
    structured = response["structured_content"]
    content = response["content"]
    if (
        not content
        or content[0].get("type") != "text"
        or json.loads(content[0]["text"]) != structured
    ):
        raise ValueError("The text and structured response differ.")
    result = result_type.model_validate_json(json.dumps(structured))
    if not isinstance(result.outcome, Success):
        raise ValueError("The requested operation did not succeed.")
    return result.outcome.value


def received_image(response: dict, observation: Observation) -> None:
    """Decode the image received by the model without comparing pixels."""
    content = response["content"]
    if [item.get("type") for item in content] != ["text", "image"]:
        raise ValueError("The response must contain exactly one text and one native image.")
    image = ImageContent.model_validate(content[1])
    if image.mimeType != "image/png":
        raise ValueError("The image must use the PNG media type.")
    if image.annotations is not None and image.annotations.audience is not None:
        if "assistant" not in image.annotations.audience:
            raise ValueError("The image is hidden from the model.")
    with Image.open(BytesIO(base64.b64decode(image.data, validate=True))) as decoded:
        decoded.load()
        if decoded.format != "PNG" or decoded.size != (1200, 800):
            raise ValueError("The decoded image does not have the trial dimensions.")
        if decoded.size != (observation.image.width, observation.image.height):
            raise ValueError("The decoded dimensions differ from the observation.")


def valid_final(events: list[dict], answer: dict) -> bool:
    completed = [
        (index, event["item"])
        for index, event in enumerate(events)
        if event.get("type") == "item.completed"
    ]
    calls = [index for index, item in completed if item.get("type") == "mcp_tool_call"]
    messages = [(index, item) for index, item in completed if item.get("type") == "agent_message"]
    if len(calls) != 7 or not messages or messages[-1][0] <= calls[-1]:
        return False
    if not events or events[-1].get("type") != "turn.completed":
        return False
    try:
        return json.loads(messages[-1][1]["text"]) == answer
    except (KeyError, TypeError, ValueError):
        return False


def checked_calls(events: list[dict], server_responses: list[dict]) -> list[dict]:
    items = [event["item"] for event in events if event.get("type") == "item.completed"]
    if any(
        item.get("type") not in {"mcp_tool_call", "agent_message", "reasoning"} for item in items
    ):
        raise ValueError("The observer used an unrelated tool.")
    calls = [item for item in items if item.get("type") == "mcp_tool_call"]
    names = ["project_inspect", *(["view_apply"] * 5), "view_render"]
    if [call.get("tool") for call in calls] != names or len(server_responses) != len(calls):
        raise ValueError("The observer did not complete the exact seven-call sequence.")
    for call, recorded in zip(calls, server_responses, strict=True):
        if call.get("server") != "p06_views" or call.get("status") != "completed":
            raise ValueError("The observer used another server or received a failed call.")
        if (call["tool"], call["arguments"]) != (recorded["tool"], recorded["arguments"]):
            raise ValueError("The server and model call records differ.")
        native = CallToolResult.model_validate(recorded["response"])
        if native.isError:
            raise ValueError("The server returned an error.")
        received = call["result"]
        delivered = CallToolResult.model_validate(
            {"content": received["content"], "structuredContent": received["structured_content"]}
        )
        if native.structuredContent != delivered.structuredContent:
            raise ValueError("The model and server structured results differ.")
        if [item.type for item in native.content] != [item.type for item in delivered.content]:
            raise ValueError("The model did not receive every native content item.")
    return calls


def checked_edit(call: dict, trial: Trial, expected: ViewUpdateRequest) -> Observation:
    request = ViewUpdateRequest.model_validate_json(json.dumps(call["arguments"]))
    if request != expected:
        raise ValueError("The observer changed a requested view argument or reference.")
    edited = structured_value(call["result"], OperationResult[EditedView])
    if not isinstance(edited.edit, ViewEditReceipt) or not isinstance(
        edited.observation.outcome, Success
    ):
        raise ValueError("The view edit lacks a confirmed receipt and observation.")
    observation = edited.observation.outcome.value
    if edited.edit.previous_scene_version != request.context.scene_version:
        raise ValueError("The edit used another previous scene version.")
    actual = observation.context
    if not camera_matches(expected.context.camera, actual.camera):
        raise ValueError("The native camera differs from the requested pose or projection.")
    if (
        actual.model_copy(
            update={
                "camera": expected.context.camera,
                "scene_version": expected.context.scene_version,
            }
        )
        != expected.context
    ):
        raise ValueError("The native result differs from the requested view settings.")
    if actual.model.session_id != trial.session_id or actual.result_id != trial.result_id:
        raise ValueError("The observation belongs to another trial result.")
    received_image(call["result"], observation)
    return observation


def checked_observations(calls: list[dict], trial: Trial) -> list[Observation]:
    if calls[0]["arguments"] != {"session_id": str(trial.session_id)}:
        raise ValueError("Project inspection must use the explicit trial session.")
    project = structured_value(calls[0]["result"], OperationResult[ProjectState])
    if project.context.session_id != trial.session_id:
        raise ValueError("Project inspection returned another session.")
    observations = []
    for call, item in zip(calls[1:6], trial.requests, strict=True):
        expected = ViewUpdateRequest(
            context=requested_context(trial, project, item), width=item.width, height=item.height
        )
        observations.append(checked_edit(call, trial, expected))
    control = observations[1]
    expected_render = ViewRenderRequest(
        session_id=trial.session_id, context=control.context, width=1200, height=800
    )
    render = ViewRenderRequest.model_validate_json(json.dumps(calls[6]["arguments"]))
    if render != expected_render:
        raise ValueError("The final render did not request the unchanged control view.")
    final = structured_value(calls[6]["result"], OperationResult[Observation])
    if final.context != control.context:
        raise ValueError("The control view context changed during target edits.")
    received_image(calls[6]["result"], final)
    observations.append(final)
    if len({item.observation_id for item in observations}) != 6:
        raise ValueError("The six captures did not use unique observation identifiers.")
    if len({item.image.artifact for item in observations}) != 6:
        raise ValueError("The six captures reused an image artifact.")
    if observations[0].context.legend != observations[2].context.legend:
        raise ValueError("The pressure comparison changed legend bounds.")
    if observations[3].context.legend != observations[4].context.legend:
        raise ValueError("The saturation comparison changed legend bounds.")
    return observations


def audit(evidence: Path, trial: Trial, exit_code: int) -> int:
    """Gate transport evidence; spatial claims remain subject to human visual review."""
    report: dict[str, Any] = {
        "passed": False,
        "exit_code": exit_code,
        "visual_review_required": True,
        "visual_claims_verified": False,
    }
    try:
        if exit_code != 0:
            raise ValueError("The observer process did not complete successfully.")
        answer = json.loads((evidence / "answer.json").read_text())
        events = [json.loads(line) for line in (evidence / "events.jsonl").read_text().splitlines()]
        responses = [
            json.loads(line)
            for line in (evidence / "server-responses.jsonl").read_text().splitlines()
        ]
        if not valid_final(events, answer):
            raise ValueError("The final answer did not follow all completed native calls.")
        if set(answer) != {"status", *DESCRIPTION_FIELDS} or answer["status"] != "observed":
            raise ValueError("The observer did not report all six images as observed.")
        if any(
            not isinstance(answer[field], str) or not answer[field].strip()
            for field in DESCRIPTION_FIELDS
        ):
            raise ValueError("The observer omitted a visual description.")
        calls = checked_calls(events, responses)
        observations = checked_observations(calls, trial)
        report.update(
            passed=True,
            answer=answer,
            observation_ids=[str(item.observation_id) for item in observations],
            completed_mcp_calls=len(calls),
            native_images=len(observations),
        )
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
        ValidationError,
        binascii.Error,
        Image.DecompressionBombError,
    ) as error:
        report["error"] = str(error)
    (evidence / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    sys.exit(
        run(arguments.codex.resolve(), arguments.trial.resolve(), arguments.evidence.resolve())
    )
