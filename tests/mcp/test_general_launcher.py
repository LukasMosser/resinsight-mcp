"""Use the shipped MCP launcher for general geological authoring and recovery."""

import asyncio
import json
from pathlib import Path

from test_launcher import launcher, managed_launcher, value

from resinsight_mcp.contracts.identifiers import SessionId


async def create_model(client, session_id: str):
    value(await client.call_tool("session_create", {"session_id": session_id, "name": "Geology"}))
    capabilities = value(await client.call_tool("general_capabilities", {}))
    assert capabilities["model_cell_ceiling"] is None
    return value(
        await client.call_tool(
            "geological_generate",
            {
                "session_id": session_id,
                "name": "MCP geological model",
                "shape": {"nx": 21, "ny": 30, "nz": 20},
                "extent_x": 2000,
                "extent_y": 3000,
                "top_depth": 1500,
                "thickness": 200,
                "length_unit": "m",
                "datum": "Local depth",
                "faults": [{"intercept": 1000, "throw": 75}],
                "bands": [{"bottom_fraction": 1, "porosity": 0.2, "permeability_md": 1000}],
            },
        )
    )


def test_general_launcher_reopens_artifacts_and_models(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "workspace"
        async with launcher(root, "--create-workspace", "--enable-general-models") as client:
            model = await create_model(client, str(SessionId.new()))
            assert model["shape"] == {"nx": 21, "ny": 30, "nz": 20}
            assert len(json.dumps(model)) < 6000
            arrays = {item["name"]: item["array"] for item in model["arrays"]}
        async with launcher(root, "--enable-general-models") as client:
            assert value(await client.call_tool("geological_inspect", model["model"])) == model
            result = value(
                await client.call_tool(
                    "array_range",
                    {"array": arrays["PERMX"]["artifact"], "offset": 12000, "count": 4},
                )
            )
            assert result["values"] == [1000] * 4

    asyncio.run(exercise())


def test_managed_general_models_follow_selection(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with managed_launcher(tmp_path / "workspaces", "--enable-general-models") as client:
            for name in ("one", "two"):
                value(await client.call_tool("workspace_create", {"name": name}))
            value(await client.call_tool("workspace_select", {"name": "one"}))
            model = await create_model(client, str(SessionId.new()))
            value(await client.call_tool("workspace_select", {"name": "two"}))
            assert (await client.call_tool("geological_inspect", model["model"])).isError
            value(await client.call_tool("workspace_select", {"name": "one"}))
            assert value(await client.call_tool("geological_inspect", model["model"])) == model

    asyncio.run(exercise())


def test_invalid_authoring_configuration_leaves_no_workspace(tmp_path: Path) -> None:
    import pytest

    from resinsight_mcp.mcp.launcher import LauncherConfiguration

    root = tmp_path / "workspace"
    policy = tmp_path / "policy.json"
    policy.write_text('{"working_memory_mib": 0}')
    with pytest.raises(ValueError):
        LauncherConfiguration(
            workspace_root=root,
            create_workspace=True,
            enable_general_models=True,
            authoring_policy=policy,
        ).bindings()
    assert not root.exists()


def test_authoring_policy_reaches_native_client_configuration(tmp_path: Path, monkeypatch) -> None:
    from resinsight_mcp.mcp.launcher import _native_factory
    from resinsight_mcp.models.general.arrays import AuthoringPolicy
    from resinsight_mcp.resinsight.sessions import rips as native

    configured = {}

    def factory(directory, **options):
        configured.update(directory=directory, **options)
        return object()

    monkeypatch.setattr(native, "RipsApplicationFactory", factory)
    monkeypatch.setattr("resinsight_mcp.mcp.launcher.shutil.which", lambda _: "/usr/bin/lsof")
    _native_factory(
        tmp_path,
        AuthoringPolicy(native_rpc_timeout_seconds=180.0, native_launch_timeout_seconds=300.0),
    )
    assert configured == {"directory": tmp_path, "rpc_timeout": 180.0, "launch_timeout": 300.0}


def test_general_well_plans_survive_restart_and_workspace_selection(tmp_path: Path) -> None:
    async def exercise() -> None:
        root = tmp_path / "workspaces"
        async with managed_launcher(root, "--enable-general-models") as client:
            for name in ("geological", "foreign"):
                value(await client.call_tool("workspace_create", {"name": name}))
            value(await client.call_tool("workspace_select", {"name": "geological"}))
            session = str(SessionId.new())
            model = await create_model(client, session)
            targets = [number for depth in range(1500, 1631) for number in (10, 10, depth)]
            refs = []
            for numbers, unit in ((targets, "m"), ([0, 130, 0.2], "m"), ([0], "1")):
                array = value(
                    await client.call_tool(
                        "array_upload",
                        {
                            "session_id": session,
                            "dtype": "float64",
                            "unit": unit,
                            "values": numbers,
                        },
                    )
                )
                refs.append(array["artifact"])
            plan = value(
                await client.call_tool(
                    "general_well_define",
                    {
                        "model": model["model"],
                        "name": "GENERAL_INJECTOR",
                        "role": "injector",
                        "injection_phase": "WATER",
                        "targets": refs[0],
                        "intervals": refs[1],
                        "skins": refs[2],
                        "sampling_distance": 1,
                    },
                )
            )
            assert plan["length_unit"] == "m" and plan["model"] == model["model"]
            value(await client.call_tool("workspace_select", {"name": "foreign"}))
            assert (await client.call_tool("general_well_inspect", plan["artifact"])).isError
        async with managed_launcher(root, "--enable-general-models") as client:
            value(await client.call_tool("workspace_select", {"name": "geological"}))
            assert value(await client.call_tool("general_well_inspect", plan["artifact"])) == plan

    asyncio.run(exercise())
