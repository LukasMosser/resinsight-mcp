"""Synthetic gate fixtures do not establish real native application acceptance."""

import base64
import json
import tomllib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import (
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    Unit,
)
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import ArtifactId, ConnectionId, EditId, ObservationId
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import (
    Camera,
    CellRangeFilter,
    EditedView,
    ImageArtifact,
    Legend,
    Observation,
    Projection,
    Property,
    ViewContext,
    ViewEditReceipt,
    ViewUpdateRequest,
)
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    Endpoint,
    ObjectKind,
    ObjectRef,
    ProjectObject,
    ProjectState,
)
from resinsight_mcp.mcp.catalog import ViewRenderRequest

from . import run_observer as observer


def encoded(value: Record, image: str | None = None) -> dict:
    result = OperationResult(outcome=Success(value=value))
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=result.model_dump_json())
    ]
    if image is not None:
        content.append(ImageContent(type="image", data=image, mimeType="image/png"))
    return CallToolResult(
        content=content,
        structuredContent=result.model_dump(mode="json"),
    ).model_dump(mode="json")


def observation(context: ViewContext) -> Observation:
    return Observation(
        observation_id=ObservationId.new(),
        context=context,
        image=ImageArtifact(
            artifact=ArtifactRef(session_id=context.model.session_id, artifact_id=ArtifactId.new()),
            width=1200,
            height=800,
        ),
        captured_at=datetime.now(UTC),
    )


@pytest.fixture
def trial(tmp_path: Path, result: Result) -> tuple[observer.Trial, ProjectState]:
    context = ApplicationContext(
        session_id=result.model.session_id, connection_id=ConnectionId.new(), project_generation=1
    )
    project = ProjectState(
        context=context,
        objects=tuple(
            ProjectObject(
                ref=ObjectRef(context=context, kind=kind, object_id=str(index)), name=name
            )
            for index, (kind, name) in enumerate(
                (
                    (ObjectKind.CASE, "Fixture case"),
                    (ObjectKind.VIEW, "Target"),
                    (ObjectKind.VIEW, "Control"),
                    (ObjectKind.WELL, "Fixture well"),
                )
            )
        ),
    )
    camera = Camera(
        position=(20.0, 20.0, 20.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 0.0, 1.0),
        projection=Projection.ORTHOGRAPHIC,
        parallel_scale=1000.0,
    )
    contexts = []
    for index, scene in enumerate((0, 0, 1, 2, 3)):
        cropped = index == 4
        contexts.append(
            ViewContext(
                model=result.model,
                result_id=result.result_id,
                grid_id=result.grid_id,
                case=project.objects[0].ref,
                view=project.objects[2 if index == 1 else 1].ref,
                selected_wells=(project.objects[3].ref,),
                scene_version=scene,
                property=Property(
                    name="PRESSURE" if index < 3 else "SGAS",
                    unit=Unit.PSI if index < 3 else Unit.ONE,
                ),
                report_time=result.report_series.reports[0 if index < 2 else -1],
                coordinates=CoordinateFrame(
                    length_unit=Unit.FOOT,
                    depth_direction=DepthDirection.POSITIVE_DOWN,
                    datum="Gate fixture",
                ),
                camera=camera.model_copy(update={"parallel_scale": 500.0}) if cropped else camera,
                vertical_exaggeration=10.0,
                legend=Legend(minimum=1000.0, maximum=5000.0)
                if index < 3
                else Legend(minimum=0.0, maximum=1.0),
                filters=(
                    CellRangeFilter(
                        grid_id=result.grid_id,
                        minimum=CellIndex(i=1, j=1, k=0),
                        maximum=CellIndex(i=2, j=2, k=1),
                        include=True,
                    ),
                )
                if cropped
                else (),
            )
        )
    manifest = observer.Trial(
        workspace=tmp_path / "unused-workspace",
        application_logs=tmp_path / "unused-logs",
        endpoint=Endpoint(port=50051),
        session_id=result.model.session_id,
        result_id=result.result_id,
        case_name="Fixture case",
        target_view_name="Target",
        control_view_name="Control",
        well_name="Fixture well",
        requests=tuple(
            observer.TrialRequest(
                view_name="Control" if index == 1 else "Target",
                context=item.model_dump(mode="json", exclude={"case", "view", "selected_wells"}),
                width=1200,
                height=800,
            )
            for index, item in enumerate(contexts)
        ),
    )
    return manifest, project


def evidence(tmp_path: Path, trial: observer.Trial, project: ProjectState) -> list[dict]:
    """Create synthetic protocol events solely for testing the acceptance gate."""
    stream = BytesIO()
    Image.new("RGB", (1200, 800), "navy").save(stream, format="PNG")
    image = base64.b64encode(stream.getvalue()).decode("ascii")
    calls = []

    def append(tool: str, arguments: dict, response: dict) -> None:
        calls.append(
            {
                "type": "mcp_tool_call",
                "status": "completed",
                "server": "p06_views",
                "tool": tool,
                "arguments": arguments,
                "result": {
                    "content": response["content"],
                    "structured_content": response["structuredContent"],
                },
            }
        )

    append("project_inspect", {"session_id": str(trial.session_id)}, encoded(project))
    observations = []
    for item in trial.requests:
        context = observer.requested_context(trial, project, item)
        request = ViewUpdateRequest(context=context, width=1200, height=800)
        captured = observation(
            context.model_copy(update={"scene_version": context.scene_version + 1})
        )
        observations.append(captured)
        edited = EditedView(
            edit=ViewEditReceipt(
                edit_id=EditId.new(),
                previous_scene_version=context.scene_version,
                context=captured.context,
            ),
            observation=OperationResult(outcome=Success(value=captured)),
        )
        append("view_apply", request.model_dump(mode="json"), encoded(edited, image))
    control = observation(observations[1].context)
    render = ViewRenderRequest(
        session_id=trial.session_id, context=control.context, width=1200, height=800
    )
    append("view_render", render.model_dump(mode="json"), encoded(control, image))
    answer = {
        "status": "observed",
        **{field: "Synthetic gate description." for field in observer.DESCRIPTION_FIELDS},
    }
    (tmp_path / "answer.json").write_text(json.dumps(answer))
    return [
        *({"type": "item.completed", "item": call} for call in calls),
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}},
        {"type": "turn.completed"},
    ]


def check(tmp_path: Path, trial: observer.Trial, events: list[dict]) -> int:
    calls = [
        event["item"] for event in events if event.get("item", {}).get("type") == "mcp_tool_call"
    ]
    server = [
        {
            "tool": call["tool"],
            "arguments": call["arguments"],
            "response": {
                "content": call["result"]["content"],
                "structuredContent": call["result"]["structured_content"],
                "isError": False,
            },
        }
        for call in calls
    ]
    (tmp_path / "server-responses.jsonl").write_text("\n".join(json.dumps(item) for item in server))
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    return observer.audit(tmp_path, trial, 0)


def test_complete_images_pass_transport_gate_only(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState]
) -> None:
    manifest, project = trial
    events = evidence(tmp_path, manifest, project)
    assert check(tmp_path, manifest, events) == 0
    report = json.loads((tmp_path / "audit.json").read_text())
    assert report["native_images"] == 6
    assert report["visual_review_required"] is True
    assert report["visual_claims_verified"] is False


@pytest.mark.parametrize("problem", ["missing", "hidden", "empty", "dimensions"])
def test_unusable_image_rejects_visual_claims(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState], problem: str
) -> None:
    manifest, project = trial
    events = evidence(tmp_path, manifest, project)
    response = events[4]["item"]["result"]
    image = response["content"][1]
    if problem == "missing":
        response["content"].pop()
    elif problem == "hidden":
        image["annotations"] = {"audience": ["user"]}
    elif problem == "empty":
        image["data"] = ""
    else:
        response["structured_content"]["outcome"]["value"]["observation"]["outcome"]["value"][
            "image"
        ]["width"] = 100
        response["content"][0]["text"] = json.dumps(response["structured_content"])
    assert check(tmp_path, manifest, events) == 1


@pytest.mark.parametrize(
    "problem",
    [
        "order",
        "session",
        "reference",
        "duplicate_image",
        "control_context",
        "early_answer",
        "extra_tool",
        "unfinished",
    ],
)
def test_malformed_sequence_rejects_visual_claims(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState], problem: str
) -> None:
    manifest, project = trial
    events = evidence(tmp_path, manifest, project)
    if problem == "order":
        events[2], events[3] = events[3], events[2]
    elif problem == "session":
        events[0]["item"]["arguments"] = {}
    elif problem == "reference":
        events[1]["item"]["arguments"]["context"]["view"]["object_id"] = "invented"
    elif problem == "duplicate_image":
        first = events[1]["item"]["result"]["structured_content"]["outcome"]["value"][
            "observation"
        ]["outcome"]["value"]
        final = events[6]["item"]["result"]
        final["structured_content"]["outcome"]["value"]["observation_id"] = first["observation_id"]
        final["content"][0]["text"] = json.dumps(final["structured_content"])
    elif problem == "control_context":
        events[6]["item"]["arguments"]["context"]["scene_version"] = 2
    elif problem == "early_answer":
        events[6], events[7] = events[7], events[6]
    elif problem == "extra_tool":
        events.insert(1, {"type": "item.completed", "item": {"type": "command_execution"}})
    else:
        events.pop()
    assert check(tmp_path, manifest, events) == 1


def test_no_image_answer_cannot_pass_native_acceptance(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState]
) -> None:
    manifest, project = trial
    events = evidence(tmp_path, manifest, project)
    answer = {"status": "no_image", **{field: None for field in observer.DESCRIPTION_FIELDS}}
    (tmp_path / "answer.json").write_text(json.dumps(answer))
    events[-2]["item"]["text"] = json.dumps(answer)
    assert check(tmp_path, manifest, events) == 1


def test_wrong_native_camera_rejects_visual_claims(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState]
) -> None:
    manifest, project = trial
    events = evidence(tmp_path, manifest, project)
    response = events[1]["item"]["result"]
    edited = response["structured_content"]["outcome"]["value"]
    edited["edit"]["context"]["camera"]["parallel_scale"] = 300
    edited["observation"]["outcome"]["value"]["context"]["camera"]["parallel_scale"] = 300
    response["content"][0]["text"] = json.dumps(response["structured_content"])
    assert check(tmp_path, manifest, events) == 1
    report = json.loads((tmp_path / "audit.json").read_text())
    assert "native camera differs" in report["error"]


def test_command_preserves_generated_native_client_path(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState], monkeypatch: pytest.MonkeyPatch
) -> None:
    native_python = "/native/bundle/Contents/MacOS/Python"
    monkeypatch.setenv("PYTHONPATH", native_python)
    manifest, _ = trial
    invocation = observer.command(
        tmp_path / "codex",
        tmp_path / "observer",
        tmp_path / "evidence",
        tmp_path / "trial.json",
        manifest,
    )
    setting = next(
        item for item in invocation if item.startswith("mcp_servers.p06_views.env.PYTHONPATH=")
    )
    paths = json.loads(setting.split("=", 1)[1]).split(observer.os.pathsep)
    assert native_python in paths
    assert paths.index(native_python) < len(paths) - 1


def test_command_limits_preapproval_to_owned_view_operations(
    tmp_path: Path, trial: tuple[observer.Trial, ProjectState]
) -> None:
    manifest, _ = trial
    invocation = observer.command(
        tmp_path / "codex",
        tmp_path / "observer",
        tmp_path / "evidence",
        tmp_path / "trial.json",
        manifest,
    )
    configuration = tomllib.loads(
        "\n".join(invocation[index + 1] for index, item in enumerate(invocation) if item == "-c")
    )
    assert set(configuration["mcp_servers"]) == {"p06_views"}
    server = configuration["mcp_servers"]["p06_views"]
    assert server["tools"] == {
        "view_apply": {"approval_mode": "approve"},
        "view_render": {"approval_mode": "approve"},
    }
    assert set(server["enabled_tools"]) == {"project_inspect", "view_apply", "view_render"}
    assert "default_tools_approval_mode" not in server
    assert "approval_policy" not in configuration
