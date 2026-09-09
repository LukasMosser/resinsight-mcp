"""Exercise the full shipped composition without launching native applications or Flow."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from test_launcher import (
    SESSION_TOOLS,
    WORKSPACE_TOOLS,
    discovery,
    launcher,
    startup_environment,
    value,
)
from test_model_launcher import MODEL_TOOLS

from resinsight_mcp.contracts.errors import Success
from resinsight_mcp.contracts.identifiers import ConnectionId, JobId, ResultId, SessionId
from resinsight_mcp.workspaces import SqliteWorkspaceStore

WORKFLOW_TOOLS = {
    "model_load_case",
    "model_restore_case",
    "well_create",
    "well_update",
    "well_inspect",
    "well_adopt",
    "well_export",
    "well_export_get",
    "model_publish_schedule",
    "job_submit",
    "job_poll",
    "job_cancel",
    "opm_collect",
    "result_get",
    "result_load",
    "result_rebind",
    "result_cell_property",
    "result_curve",
    "result_compare_cells",
    "result_compare_curves",
    "result_show_curve",
    "view_apply",
    "view_render",
}


def test_full_launcher_uses_concrete_services_and_explicit_sessions(tmp_path: Path) -> None:
    root, logs = tmp_path / "workspace", tmp_path / "logs"
    logs.mkdir()
    env = startup_environment(tmp_path, "workflow-ready")
    session_id = str(SessionId.new())
    foreign_id = str(SessionId.new())
    options = ("--resinsight-log-directory", str(logs), "--enable-opm-workflow")

    async def exercise() -> None:
        async with launcher(root, "--create-workspace", *options, env=env) as client:
            await discovery(client, WORKSPACE_TOOLS | SESSION_TOOLS | MODEL_TOOLS | WORKFLOW_TOOLS)
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools["job_submit"].inputSchema["properties"]) == {
                "prepared",
                "limits",
                "resource_policy",
            }
            assert tools["job_submit"].inputSchema["additionalProperties"] is False
            for requested, name in ((session_id, "Baseline"), (foreign_id, "Other study")):
                value(
                    await client.call_tool(
                        "session_create", {"session_id": requested, "name": name}
                    )
                )
            specification = value(await client.call_tool("model_template", {}))
            created = value(
                await client.call_tool(
                    "model_create",
                    {
                        "session_id": session_id,
                        "datum": "Workflow local FIELD datum",
                        "specification": specification,
                    },
                )
            )
            model = created["imported"]["prepared"]["revision"]["model"]
            assert created["imported"]["summary"]["active_cells"] == 300
            context = {
                "session_id": session_id,
                "connection_id": str(ConnectionId.new()),
                "project_generation": 0,
            }
            calls = (
                ("model_load_case", {"context": context, "model": model}, "not_found"),
                (
                    "model_load_case",
                    {"context": context | {"session_id": foreign_id}, "model": model},
                    "invalid_model",
                ),
                (
                    "well_inspect",
                    {"context": context, "kind": "well", "object_id": "PROD"},
                    "stale_object",
                ),
                ("job_poll", {"session_id": session_id, "job_id": str(JobId.new())}, "not_found"),
                (
                    "opm_collect",
                    {"session_id": session_id, "job_id": str(JobId.new())},
                    "not_found",
                ),
                (
                    "result_get",
                    {"session_id": session_id, "result_id": str(ResultId.new())},
                    "not_found",
                ),
                (
                    "result_curve",
                    {
                        "result": {"session_id": session_id, "result_id": str(ResultId.new())},
                        "scope": "well",
                        "keyword": "WBHP",
                        "well_name": "PROD",
                    },
                    "not_found",
                ),
            )
            for name, request, expected in calls:
                refused = await client.call_tool(name, request)
                assert refused.isError, refused
                assert refused.structuredContent is not None
                assert refused.structuredContent["outcome"]["error"]["code"] == expected, name
            store = SqliteWorkspaceStore.open(root)
            assert not value(await client.call_tool("connection_list", {}))
            foreign_artifacts = store.list_artifacts(SessionId(foreign_id)).outcome
            assert isinstance(foreign_artifacts, Success)
            assert foreign_artifacts.value == ()
        async with launcher(root, *options, env=env) as client:
            assert value(await client.call_tool("model_get", model))["model"] == model
        async with launcher(root) as client:
            await discovery(client, WORKSPACE_TOOLS)
            refused = await client.call_tool(
                "result_get", {"session_id": session_id, "result_id": str(ResultId.new())}
            )
            assert refused.isError
            assert refused.structuredContent is not None
            assert refused.structuredContent["outcome"]["error"]["code"] == "unsupported_operation"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("missing-logs", "requires a ResInsight log directory"),
        ("docker-alone", "requires the OPM workflow configuration"),
        ("relative-docker", "Docker executable must use an absolute path"),
        ("missing-workflow-interface", "Project.export_prepared_input_grid"),
        ("workflow-docker-failure", "Docker"),
    ],
)
def test_invalid_workflow_configuration_creates_no_workspace(
    tmp_path: Path, problem: str, expected: str
) -> None:
    root, logs = tmp_path / "workspace", tmp_path / "logs"
    logs.mkdir()
    options = ["--enable-opm-workflow", "--resinsight-log-directory", str(logs)]
    if problem == "missing-logs":
        options = ["--enable-opm-workflow"]
    elif problem == "docker-alone":
        options = ["--docker-executable", str(tmp_path / "docker")]
    elif problem == "relative-docker":
        options += ["--docker-executable", "docker"]
    elif problem == "workflow-docker-failure":
        options += ["--docker-executable", str(tmp_path / "absent-docker")]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspace-root",
            str(root),
            "--create-workspace",
            *options,
        ],
        env=startup_environment(tmp_path, problem),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "Configuration failed" in result.stderr
    assert expected in result.stderr
    assert not root.exists()
