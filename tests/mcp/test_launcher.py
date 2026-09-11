"""Exercise the shipped launcher, with no ResInsight or simulator acceptance claim."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Any

import psutil
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextResourceContents

from resinsight_mcp.contracts.identifiers import SessionId

WORKSPACE_TOOLS = {"session_create", "session_list", "session_get", "observation_get"}
MANAGED_WORKSPACE_TOOLS = {
    "workspace_create",
    "workspace_list",
    "workspace_select",
    "workspace_current",
}
SESSION_TOOLS = {
    "session_select",
    "connection_list",
    "connection_get",
    "application_launch",
    "application_attach",
    "application_close",
    "project_inspect",
    "project_open",
    "project_save",
    "project_close",
    "object_resolve",
}


def startup_environment(tmp_path: Path, mode: str) -> dict[str, str]:
    hook = tmp_path / "startup"
    hook.mkdir()
    shutil.copyfile(Path(__file__).with_name("launcher_startup.py"), hook / "sitecustomize.py")
    return {**os.environ, "PYTHONPATH": str(hook), "LAUNCHER_TEST_STARTUP": mode}


@asynccontextmanager
async def launcher(
    root: Path, *options: str, env: dict[str, str] | None = None
) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "resinsight_mcp.mcp", "--workspace-root", str(root), *options],
        env=env if env is not None else dict(os.environ),
    )
    with (root.parent / "launcher-stderr.log").open("a") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=20)
            ) as client:
                await client.initialize()
                yield client


@asynccontextmanager
async def managed_launcher(
    root: Path, *options: str, env: dict[str, str] | None = None
) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "resinsight_mcp.mcp", "--workspaces-root", str(root), *options],
        env=env if env is not None else dict(os.environ),
    )
    with (root.parent / "managed-launcher-stderr.log").open("a") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=20)
            ) as client:
                await client.initialize()
                yield client


def value(response: CallToolResult) -> Any:
    assert not response.isError, response
    assert response.structuredContent is not None
    assert response.structuredContent["outcome"]["status"] == "success"
    return response.structuredContent["outcome"]["value"]


async def discovery(client: ClientSession, expected: set[str]) -> None:
    assert {tool.name for tool in (await client.list_tools()).tools} == expected
    resources = (await client.list_resources()).resources
    catalog = await client.read_resource(
        next(r.uri for r in resources if str(r.uri) == "resinsight://catalog")
    )
    content = catalog.contents[0]
    assert isinstance(content, TextResourceContents)
    assert {tool["name"] for tool in json.loads(content.text)["tools"]} == expected


def test_workspace_launcher_creates_and_reopens_without_native_import(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    env = startup_environment(tmp_path, "missing-rips")
    record = {"session_id": str(SessionId.new()), "name": "Durable launcher session"}

    async def exercise() -> None:
        async with launcher(root, "--create-workspace", env=env) as client:
            await discovery(client, WORKSPACE_TOOLS)
            assert value(await client.call_tool("session_create", record)) == record
        async with launcher(root, env=env) as client:
            await discovery(client, WORKSPACE_TOOLS)
            assert (
                value(await client.call_tool("session_get", {"session_id": record["session_id"]}))
                == record
            )

    asyncio.run(exercise())
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspace-root",
            str(root),
            "--create-workspace",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert refused.returncode == 2
    assert "Configuration failed" in refused.stderr


def test_managed_launcher_selects_isolated_workspaces_and_reopens(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    first_id = str(SessionId.new())
    second_id = str(SessionId.new())

    async def exercise() -> None:
        async with managed_launcher(root) as client:
            await discovery(client, WORKSPACE_TOOLS | MANAGED_WORKSPACE_TOOLS)
            current = await client.call_tool("workspace_current", {})
            assert current.structuredContent is not None
            assert current.structuredContent["outcome"] == {
                "status": "success",
                "value": None,
            }
            assert value(await client.call_tool("workspace_list", {})) == []

            unselected = await client.call_tool("session_list", {})
            assert unselected.isError
            assert unselected.structuredContent is not None
            assert unselected.structuredContent["outcome"]["error"]["code"] == (
                "invalid_transition"
            )

            first = value(await client.call_tool("workspace_create", {"name": "first"}))
            second = value(await client.call_tool("workspace_create", {"name": "second"}))
            listed = value(await client.call_tool("workspace_list", {}))
            assert [item["name"] for item in listed] == ["first", "second"]
            assert Path(first["root"]).name == "first"
            assert Path(second["root"]).name == "second"

            duplicate = await client.call_tool("workspace_create", {"name": "first"})
            assert duplicate.isError
            assert duplicate.structuredContent is not None
            assert duplicate.structuredContent["outcome"]["error"]["code"] == "conflict"
            missing = await client.call_tool("workspace_select", {"name": "missing"})
            assert missing.isError
            assert missing.structuredContent is not None
            assert missing.structuredContent["outcome"]["error"]["code"] == "not_found"

            value(await client.call_tool("workspace_select", {"name": "first"}))
            value(
                await client.call_tool(
                    "session_create", {"session_id": first_id, "name": "First workspace"}
                )
            )
            value(await client.call_tool("workspace_select", {"name": "second"}))
            assert value(await client.call_tool("session_list", {})) == []
            value(
                await client.call_tool(
                    "session_create", {"session_id": second_id, "name": "Second workspace"}
                )
            )
            value(await client.call_tool("workspace_select", {"name": "first"}))
            sessions = value(await client.call_tool("session_list", {}))
            assert [item["session_id"] for item in sessions] == [first_id]

        async with managed_launcher(root) as client:
            current = await client.call_tool("workspace_current", {})
            assert current.structuredContent is not None
            assert current.structuredContent["outcome"]["value"] is None
            listed = value(await client.call_tool("workspace_list", {}))
            assert [item["name"] for item in listed] == ["first", "second"]
            value(await client.call_tool("workspace_select", {"name": "first"}))
            first_session = value(await client.call_tool("session_get", {"session_id": first_id}))
            assert first_session["name"] == "First workspace"
            value(await client.call_tool("workspace_select", {"name": "second"}))
            second_session = value(await client.call_tool("session_get", {"session_id": second_id}))
            assert second_session["name"] == "Second workspace"

    asyncio.run(exercise())


def test_managed_launcher_rejects_fixed_mode_creation_flag(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspaces-root",
            str(root),
            "--create-workspace",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "--create-workspace requires --workspace-root" in result.stderr
    assert not root.exists()


@pytest.mark.parametrize("path_kind", ["relative", "missing", "file", "unwritable"])
def test_invalid_log_directory_does_not_create_workspace(tmp_path: Path, path_kind: str) -> None:
    root = tmp_path / "workspace"
    logs = tmp_path / "logs"
    if path_kind == "relative":
        logs = Path("relative-logs")
    elif path_kind == "file":
        logs.write_text("not a directory")
    elif path_kind == "unwritable":
        logs.mkdir(mode=0o500)
        if os.access(logs, os.W_OK):
            pytest.skip("The current user bypasses directory write permissions.")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "resinsight_mcp.mcp",
                "--workspace-root",
                str(root),
                "--create-workspace",
                "--resinsight-log-directory",
                str(logs),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 2
        assert "ResInsight log directory must" in result.stderr
        assert not root.exists()
    finally:
        if path_kind == "unwritable":
            logs.chmod(0o700)


@pytest.mark.parametrize("missing", ["rips", "lsof"])
def test_missing_native_requirement_does_not_create_workspace(tmp_path: Path, missing: str) -> None:
    root = tmp_path / "workspace"
    logs = tmp_path / "logs"
    logs.mkdir()
    env = (
        startup_environment(tmp_path, "missing-rips")
        if missing == "rips"
        else {**os.environ, "PATH": ""}
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspace-root",
            str(root),
            "--create-workspace",
            "--resinsight-log-directory",
            str(logs),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "Configuration failed" in result.stderr
    assert missing in result.stderr
    assert not root.exists()


def test_unknown_launcher_option_does_not_create_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspace-root",
            str(root),
            "--create-workspace",
            "--enable-everything",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --enable-everything" in result.stderr
    assert not root.exists()


def test_native_startup_output_uses_stderr_with_working_protocol(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    logs = tmp_path / "logs"
    logs.mkdir()
    env = startup_environment(tmp_path, "noisy")

    async def exercise() -> None:
        async with launcher(
            root, "--create-workspace", "--resinsight-log-directory", str(logs), env=env
        ) as client:
            await discovery(client, WORKSPACE_TOOLS | SESSION_TOOLS)
            assert (
                value(
                    await client.call_tool(
                        "session_create",
                        {"session_id": str(SessionId.new()), "name": "Noisy startup"},
                    )
                )["name"]
                == "Noisy startup"
            )

    asyncio.run(exercise())
    errors = (tmp_path / "launcher-stderr.log").read_text()
    assert "Launcher fixture native import" in errors
    assert "Launcher fixture native construction" in errors
    assert "Launcher fixture inherited output" in errors


@pytest.fixture
def protocol_executable(tmp_path: Path) -> Path:
    """Reuse the native client's supported gRPC fixture only for this test."""
    source = Path(__file__).parents[1] / "resinsight" / "sessions" / "test_rips_backend.py"
    executable = tmp_path / "protocol-server"
    executable.write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(source)!r})['_serve']()\n"
    )
    executable.chmod(0o700)
    return executable


def test_configured_launcher_launches_attaches_and_preserves_process_on_disconnect(
    tmp_path: Path, protocol_executable: Path
) -> None:
    root = tmp_path / "workspace"
    logs = tmp_path / "logs"
    logs.mkdir()
    project = tmp_path / "project.rsp"
    project.write_text("Protocol fixture project")
    session_id = str(SessionId.new())
    process: psutil.Process | None = None
    start_marker: str | None = None

    async def exercise() -> None:
        nonlocal process, start_marker
        async with launcher(
            root, "--create-workspace", "--resinsight-log-directory", str(logs)
        ) as client:
            await discovery(client, WORKSPACE_TOOLS | SESSION_TOOLS)
            value(
                await client.call_tool(
                    "session_create", {"session_id": session_id, "name": "Native protocol"}
                )
            )
            connection = value(
                await client.call_tool(
                    "application_launch",
                    {"session_id": session_id, "executable": str(protocol_executable)},
                )
            )
            assert connection["ownership"] == "owned"
            candidate = psutil.Process(connection["process"]["pid"])
            start_marker = connection["process"]["start_marker"]
            assert str(candidate.create_time()) == start_marker
            process = candidate
            inspected = value(await client.call_tool("project_inspect", {"session_id": session_id}))
            assert {item["ref"]["kind"] for item in inspected["objects"]} == {
                "case",
                "view",
                "well",
            }
            opened = value(
                await client.call_tool(
                    "project_open", {"context": inspected["context"], "path": str(project)}
                )
            )
            assert (
                opened["context"]["project_generation"]
                == inspected["context"]["project_generation"] + 1
            )
            stale = await client.call_tool("object_resolve", inspected["objects"][0]["ref"])
            assert stale.isError
            assert stale.structuredContent is not None
            assert stale.structuredContent["outcome"]["error"]["code"] == "stale_object"
            closed = value(await client.call_tool("project_close", {"context": opened["context"]}))
            assert (
                closed["context"]["project_generation"]
                == opened["context"]["project_generation"] + 1
            )
        assert process.is_running()
        async with launcher(root, "--resinsight-log-directory", str(logs)) as client:
            value(await client.call_tool("session_get", {"session_id": session_id}))
            attached = value(
                await client.call_tool(
                    "application_attach",
                    {"session_id": session_id, "endpoint": connection["endpoint"]},
                )
            )
            assert attached["ownership"] == "attached"
            assert attached["context"]["connection_id"] != connection["context"]["connection_id"]
            value(await client.call_tool("project_inspect", {"session_id": session_id}))
            value(
                await client.call_tool(
                    "application_close",
                    {
                        "session_id": session_id,
                        "connection_id": attached["context"]["connection_id"],
                        "action": "detach",
                    },
                )
            )
        assert process.is_running()

    try:
        asyncio.run(exercise())
    finally:
        if process is not None and process.is_running():
            with suppress(psutil.NoSuchProcess):
                current = psutil.Process(process.pid)
                assert str(current.create_time()) == start_marker
                current.terminate()
                current.wait(timeout=10)
