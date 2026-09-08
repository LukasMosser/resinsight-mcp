"""Acceptance requires usable images, matching records, and a completed answer."""

import base64
import json
from importlib import import_module
from pathlib import Path

import pytest

from resinsight_mcp.contracts.identifiers import ObservationId, SessionId
from resinsight_mcp.mcp.content import encode_result

marker_service = import_module("marker_service")
observer = import_module("run_observer")


def evidence(tmp_path: Path, mode: str) -> tuple[dict[str, str], dict, list[dict]]:
    session_id, observation_id = SessionId.new(), ObservationId.new()
    store = marker_service.prepare(tmp_path, mode, session_id, observation_id)
    response = encode_result(store.get_observation(session_id, observation_id), store)
    if mode == "hidden":
        response.content = [item for item in response.content if item.type != "image"]
    (tmp_path / "server-content.json").write_text(response.model_dump_json())
    ids = {"session_id": str(session_id), "observation_id": str(observation_id)}
    result = {
        "content": [item.model_dump() for item in response.content],
        "structured_content": response.structuredContent,
    }
    witness = json.loads((tmp_path / "witness.json").read_text())
    answer = (
        {"status": "observed", **witness}
        if mode == "visible"
        else {"status": "no_image", "row": None, "column": None}
    )
    call = {
        "type": "mcp_tool_call",
        "status": "failed" if mode == "empty" else "completed",
        "server": "p05_image",
        "tool": "observation_get",
        "arguments": ids,
        "result": result,
    }
    events = [
        {"type": "item.completed", "item": call},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}},
        {"type": "turn.completed"},
    ]
    (tmp_path / "answer.json").write_text(json.dumps(answer))
    return ids, result, events


def check(tmp_path: Path, mode: str, ids: dict[str, str], events: list[dict]) -> int:
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    return observer.audit(tmp_path, mode, ids, 0)


@pytest.mark.parametrize("mode", ["visible", "hidden", "empty"])
def test_valid_trial(tmp_path: Path, mode: str) -> None:
    ids, _, events = evidence(tmp_path, mode)
    assert check(tmp_path, mode, ids, events) == 0


@pytest.mark.parametrize("problem", ["missing", "empty", "corrupt", "hidden", "mime", "dimensions"])
def test_unusable_image_rejects_correct_answer(tmp_path: Path, problem: str) -> None:
    ids, result, events = evidence(tmp_path, "visible")
    image = result["content"][1]
    if problem == "missing":
        result["content"].pop()
    elif problem in ("empty", "corrupt"):
        image["data"] = (
            "" if problem == "empty" else base64.b64encode(b"not an image").decode("ascii")
        )
    elif problem == "hidden":
        image["annotations"] = {"audience": ["user"]}
    elif problem == "mime":
        image["mimeType"] = "image/jpeg"
    else:
        result["structured_content"]["outcome"]["value"]["image"]["width"] = 300
        result["content"][0]["text"] = json.dumps(result["structured_content"])
    assert check(tmp_path, "visible", ids, events) == 1


@pytest.mark.parametrize(
    "problem",
    [
        "text",
        "identifier",
        "missing_value",
        "early_answer",
        "wrong_answer",
        "extra_tool",
        "unfinished",
    ],
)
def test_invalid_evidence_rejected(tmp_path: Path, problem: str) -> None:
    ids, result, events = evidence(tmp_path, "visible")
    if problem == "text":
        result["content"][0]["text"] = "{}"
    elif problem == "identifier":
        result["structured_content"]["outcome"]["value"]["observation_id"] = str(
            ObservationId.new()
        )
        result["content"][0]["text"] = json.dumps(result["structured_content"])
    elif problem == "missing_value":
        result["structured_content"]["outcome"].pop("value")
        result["content"][0]["text"] = json.dumps(result["structured_content"])
    elif problem == "early_answer":
        events[0], events[1] = events[1], events[0]
    elif problem == "wrong_answer":
        events[1]["item"]["text"] = "{}"
    elif problem == "extra_tool":
        events.insert(1, {"type": "item.completed", "item": {"type": "command_execution"}})
    else:
        events.pop()
    assert check(tmp_path, "visible", ids, events) == 1


@pytest.mark.parametrize("mode", ["hidden", "empty"])
def test_guess_rejected_without_image(tmp_path: Path, mode: str) -> None:
    ids, _, events = evidence(tmp_path, mode)
    guess = {"status": "observed", **json.loads((tmp_path / "witness.json").read_text())}
    (tmp_path / "answer.json").write_text(json.dumps(guess))
    events[1]["item"]["text"] = json.dumps(guess)
    assert check(tmp_path, mode, ids, events) == 1
