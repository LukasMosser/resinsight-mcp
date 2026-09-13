"""Exercise physics tools through managed production MCP and process restart."""

import asyncio

from test_general_launcher import create_model
from test_launcher import managed_launcher, value

from resinsight_mcp.contracts.identifiers import SessionId


def test_physics_ownership_units_pages_and_parent_survive_mcp_restart(tmp_path):
    async def exercise():
        root = tmp_path / "workspaces"
        async with managed_launcher(root, "--enable-general-models") as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {
                "general_physics_create",
                "general_physics_edit",
                "general_physics_tables",
            } <= tools
            for name in ("authored", "foreign"):
                value(await client.call_tool("workspace_create", {"name": name}))
            value(await client.call_tool("workspace_select", {"name": "authored"}))
            model = (await create_model(client, str(SessionId.new())))["model"]
            metric = value(
                await client.call_tool("general_physics_schema", {"unit_system": "METRIC"})
            )
            field = value(
                await client.call_tool("general_physics_schema", {"unit_system": "FIELD"})
            )
            definition = next(table for table in metric["tables"] if table["keyword"] == "PVDG")
            gas = next(table for table in field["tables"] if table["keyword"] == "PVDG")
            assert gas["columns"][1]["unit"] == "rb/Mscf"
            parent = value(
                await client.call_tool(
                    "general_physics_create",
                    {
                        "model": model,
                        "profile": "black_oil_disgas_rsvd",
                        "regions": [
                            {"keyword": key, "values": {"kind": "uniform", "value": 1}}
                            for key in ("PVTNUM", "SATNUM", "EQLNUM")
                        ],
                    },
                )
            )
            columns = []
            for column, numbers in zip(
                definition["columns"],
                ([1, 100, 300], [1, 0.01, 0.0035], [0.01, 0.02, 0.03]),
                strict=True,
            ):
                stored = value(
                    await client.call_tool(
                        "array_upload",
                        {
                            "session_id": model["session_id"],
                            "dtype": column["dtype"],
                            "unit": column["unit"],
                            "values": numbers,
                        },
                    )
                )
                columns.append({"name": column["name"], "array": stored["artifact"]})
            child = value(
                await client.call_tool(
                    "general_physics_edit",
                    {
                        "parent": parent["artifact"],
                        "tables": [{"keyword": "PVDG", "region": 1, "columns": columns}],
                    },
                )
            )
            assert child["table_count"] == 1 and child["row_count"] == 3
            assert not child["complete"] and not child["simulation_ready"]
            page = value(
                await client.call_tool(
                    "general_physics_tables", {"physics": child["artifact"], "count": 1}
                )
            )
            assert page["tables"][0]["columns"][1]["array"]["unit"] == "rm3/sm3"
            assert (
                await client.call_tool(
                    "general_physics_tables", {"physics": child["artifact"], "count": 129}
                )
            ).isError
            value(await client.call_tool("workspace_select", {"name": "foreign"}))
            assert (await client.call_tool("general_physics_inspect", child["artifact"])).isError
            assert (
                await client.call_tool("general_physics_edit", {"parent": child["artifact"]})
            ).isError
        async with managed_launcher(root, "--enable-general-models") as client:
            value(await client.call_tool("workspace_select", {"name": "authored"}))
            assert (
                value(await client.call_tool("general_physics_inspect", child["artifact"])) == child
            )
            assert (
                value(await client.call_tool("general_physics_inspect", parent["artifact"]))
                == parent
            )
            assert (
                value(
                    await client.call_tool(
                        "general_physics_tables", {"physics": child["artifact"], "count": 1}
                    )
                )
                == page
            )
            numbers = value(
                await client.call_tool(
                    "array_range", {"array": columns[1]["array"], "offset": 1, "count": 2}
                )
            )
            assert numbers["values"] == [0.01, 0.0035]

    asyncio.run(exercise())
