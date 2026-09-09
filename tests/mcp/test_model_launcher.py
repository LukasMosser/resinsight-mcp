"""Exercise model creation and import through the shipped MCP launcher."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_launcher import WORKSPACE_TOOLS, discovery, launcher, startup_environment, value

from resinsight_mcp.contracts.identifiers import RevisionId, SessionId
from resinsight_mcp.workspaces import SqliteWorkspaceStore

MODEL_TOOLS = {
    "model_import",
    "model_get",
    "model_inspect",
    "model_prepare",
    "model_clone",
    "model_template",
    "model_create",
}
SOURCE = Path(__file__).parents[1] / "models" / "imports" / "data" / "spe1"


def test_model_launcher_creates_clones_and_prepares_after_reconnect(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    session_id = str(SessionId.new())
    env = startup_environment(tmp_path, "missing-rips")

    async def exercise() -> None:
        async with launcher(root, "--create-workspace", "--enable-models", env=env) as client:
            await discovery(client, WORKSPACE_TOOLS | MODEL_TOOLS)
            value(await client.call_tool("session_create", {"session_id": session_id, "name": "A"}))
            specification = value(await client.call_tool("model_template", {}))
            created = value(
                await client.call_tool(
                    "model_create",
                    {
                        "session_id": session_id,
                        "datum": "Local FIELD datum",
                        "specification": specification,
                    },
                )
            )
            parent = created["imported"]["prepared"]["revision"]
            assert created["imported"]["summary"]["active_cells"] == 300
            assert set(created["imported"]["summary"]["wells"]) == {"PROD", "INJ"}
            child = value(
                await client.call_tool(
                    "model_clone",
                    {"source": parent["model"], "revision_id": str(RevisionId.new())},
                )
            )
            assert child["parent"] == parent["model"]
            assert child["inputs"] == parent["inputs"]
            assert child["model"] != parent["model"]
        async with launcher(root, "--enable-models", env=env) as client:
            assert value(await client.call_tool("model_get", parent["model"])) == parent
            assert value(await client.call_tool("model_get", child["model"])) == child
            prepared = value(
                await client.call_tool("model_prepare", {"revision": child, "backend": "opm_flow"})
            )
            assert prepared["revision"] == child
            inspected = value(await client.call_tool("model_inspect", child["model"]))
            assert inspected["summary"]["dimensions"] == [10, 10, 3]
            assert len(inspected["active_cells"]) == 300
            assert inspected["report_elapsed_days"] == [0.0, 1.0, 2.0]
            wrong = child | {"unit_system": "METRIC"}
            refused = await client.call_tool(
                "model_prepare", {"revision": wrong, "backend": "opm_flow"}
            )
            assert refused.isError
            assert refused.structuredContent is not None
            assert refused.structuredContent["outcome"]["error"]["code"] == "invalid_model"
            assert value(await client.call_tool("model_get", child["model"])) == child

    asyncio.run(exercise())


def test_model_launcher_imports_inputs_and_rejects_invalid_models(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    session_id = str(SessionId.new())
    invalid = tmp_path / "invalid"
    shutil.copytree(SOURCE, invalid)
    entrypoint = invalid / "SPE1.DATA"
    entrypoint.write_text(entrypoint.read_text().replace("FIELD", "METRIC"))

    async def exercise() -> None:
        async with launcher(root, "--create-workspace", "--enable-models") as client:
            value(
                await client.call_tool(
                    "session_create", {"session_id": session_id, "name": "Import"}
                )
            )
            imported = value(
                await client.call_tool(
                    "model_import",
                    {
                        "session_id": session_id,
                        "source_root": str(SOURCE.resolve()),
                        "entrypoint": "SPE1.DATA",
                        "datum": "SPE1 local datum",
                    },
                )
            )
            revision = imported["prepared"]["revision"]
            assert imported["summary"]["support_profile"] == "spe1-field-v2"
            assert imported["summary"]["unit_system"] == "FIELD"
            store = SqliteWorkspaceStore.open(root)
            before = store.list_artifacts(SessionId(session_id))
            for source, requested_session, expected in (
                (invalid, session_id, "invalid_model"),
                (SOURCE.resolve(), str(SessionId.new()), "not_found"),
            ):
                refused = await client.call_tool(
                    "model_import",
                    {
                        "session_id": requested_session,
                        "source_root": str(source),
                        "entrypoint": "SPE1.DATA",
                        "datum": "SPE1 local datum",
                    },
                )
                assert refused.isError
                assert refused.structuredContent is not None
                assert refused.structuredContent["outcome"]["error"]["code"] == expected
            assert store.list_artifacts(SessionId(session_id)) == before
            assert value(await client.call_tool("model_get", revision["model"])) == revision
        async with launcher(root) as client:
            await discovery(client, WORKSPACE_TOOLS)
            refused = await client.call_tool("model_get", revision["model"])
            assert refused.isError
            assert refused.structuredContent is not None
            assert refused.structuredContent["outcome"]["error"]["code"] == "unsupported_operation"

    asyncio.run(exercise())


def test_model_dependency_failure_does_not_create_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    environment = startup_environment(tmp_path, "missing-model-dependencies")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resinsight_mcp.mcp",
            "--workspace-root",
            str(root),
            "--create-workspace",
            "--enable-models",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "Configuration failed" in result.stderr
    assert "OPM import dependencies are unavailable" in result.stderr
    assert not root.exists()


@pytest.mark.parametrize("backend", ["julia", "unknown"])
def test_model_prepare_rejects_unsupported_backend(tmp_path: Path, backend: str) -> None:
    root = tmp_path / "workspace"
    session_id = str(SessionId.new())

    async def exercise() -> None:
        async with launcher(root, "--create-workspace", "--enable-models") as client:
            value(
                await client.call_tool(
                    "session_create", {"session_id": session_id, "name": "Backend"}
                )
            )
            imported = value(
                await client.call_tool(
                    "model_import",
                    {
                        "session_id": session_id,
                        "source_root": str(SOURCE.resolve()),
                        "entrypoint": "SPE1.DATA",
                        "datum": "SPE1 local datum",
                    },
                )
            )
            refused = await client.call_tool(
                "model_prepare",
                {"revision": imported["prepared"]["revision"], "backend": backend},
            )
            assert refused.isError
            assert refused.structuredContent is not None
            error = refused.structuredContent["outcome"]["error"]
            assert error["code"] == (
                "unsupported_operation" if backend == "julia" else "invalid_model"
            )
            assert error["effect"] == "not_applied"

    asyncio.run(exercise())
