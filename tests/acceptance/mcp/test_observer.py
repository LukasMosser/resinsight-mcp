"""Acceptance requires image evidence and rejects guesses and extra tools."""

import json
from pathlib import Path

import pytest

from tests.acceptance.mcp.run_observer import audit


@pytest.mark.parametrize(
    ("mode", "answer", "types", "extra_tool", "accepted"),
    [
        ("visible", {"status": "observed", "row": 2, "column": 3}, ["text", "image"], False, True),
        ("visible", {"status": "observed", "row": 2, "column": 3}, ["text"], False, False),
        ("visible", {"status": "observed", "row": 1, "column": 3}, ["text", "image"], False, False),
        ("visible", {"status": "observed", "row": 2, "column": 3}, ["text", "image"], True, False),
        ("hidden", {"status": "no_image", "row": None, "column": None}, ["text"], False, True),
        ("hidden", {"status": "observed", "row": 2, "column": 3}, ["text"], False, False),
        ("empty", {"status": "no_image", "row": None, "column": None}, ["text"], False, True),
    ],
)
def test_gate(
    tmp_path: Path, mode: str, answer: dict, types: list[str], extra_tool: bool, accepted: bool
) -> None:
    ids = {"session_id": "session", "observation_id": "observation"}
    result = {"content": [{"type": kind} for kind in types], "isError": mode == "empty"}
    result["structured_content"] = {
        "outcome": {"status": "failure", "error": {"code": "render_failed"}}
        if mode == "empty"
        else {"status": "success"}
    }
    call = {
        "type": "mcp_tool_call",
        "status": "failed" if mode == "empty" else "completed",
        "server": "p05_image",
        "tool": "observation_get",
        "arguments": ids,
        "result": result,
    }
    events = [{"type": "item.completed", "item": call}]
    if extra_tool:
        events.append({"type": "item.completed", "item": {"type": "command_execution"}})
    (tmp_path / "server-content.json").write_text(json.dumps(result))
    (tmp_path / "answer.json").write_text(json.dumps(answer))
    (tmp_path / "witness.json").write_text(json.dumps({"row": 2, "column": 3}))
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    assert (audit(tmp_path, mode, ids, 0) == 0) is accepted
