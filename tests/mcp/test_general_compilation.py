"""Compile public MCP inputs and recover the receipt in a fresh managed server."""

import asyncio

from test_general_launcher import create_model
from test_launcher import managed_launcher, value

from resinsight_mcp.contracts.identifiers import SessionId
from tests.general_physics_data import ROWS


def test_public_compilation_preserves_sources_across_restart(tmp_path):
    async def exercise():
        root = tmp_path / "workspaces"
        async with managed_launcher(root, "--enable-general-models") as client:

            async def call(name, arguments):
                return value(await client.call_tool(name, arguments))

            for name in ("authored", "foreign"):
                await call("workspace_create", {"name": name})
            await call("workspace_select", {"name": "authored"})
            model = (await create_model(client, str(SessionId.new())))["model"]
            schema = await call("general_physics_schema", {"unit_system": "METRIC"})
            physics = await call(
                "general_physics_create",
                {
                    "model": model,
                    "profile": schema["profile"],
                    "regions": [
                        {"keyword": key, "values": {"kind": "uniform", "value": 1}}
                        for key in ("PVTNUM", "SATNUM", "EQLNUM")
                    ],
                },
            )
            tables = []
            for table in schema["tables"]:
                numbers = list(ROWS[table["keyword"]])
                if table["keyword"] == "PVTO":
                    numbers.append([150, 500, 1.28, 1.1])
                columns = []
                for column, data in zip(table["columns"], zip(*numbers, strict=True), strict=True):
                    stored = await call(
                        "array_upload",
                        {
                            "session_id": model["session_id"],
                            "dtype": column["dtype"],
                            "unit": column["unit"],
                            "values": list(data),
                        },
                    )
                    columns.append({"name": column["name"], "array": stored["artifact"]})
                tables.append({"keyword": table["keyword"], "region": 1, "columns": columns})
            physics = await call(
                "general_physics_edit", {"parent": physics["artifact"], "tables": tables}
            )
            days = await call(
                "array_upload",
                {
                    "session_id": model["session_id"],
                    "dtype": "float64",
                    "unit": "day",
                    "values": [0, 0.5, 1, 2],
                },
            )
            schedule = await call(
                "general_schedule_create",
                {"model": model, "start_date": "2026-09-13", "report_days": days["artifact"]},
            )
            assembly = await call(
                "general_simulation_define",
                {
                    "schedule": schedule["artifact"],
                    "physics": physics["artifact"],
                    "group": "GENERAL",
                    "dissolution_limit": {"value": 0, "unit": "sm3/sm3/day"},
                    "write_restart": False,
                },
            )
            receipt = await call("general_simulation_prepare", assembly["artifact"])
            assert receipt["validation"]["global_cells"] == 12600
            assert receipt["validation"]["wells"] == 0
            assert receipt["validation"]["reports"] == 4
            assert receipt["validation"]["verified_table_rows"] == 19
            assert receipt["validation"]["clock"] == "UTC"
            assert not receipt["simulation_executed"]
            assert receipt["model"] == model
            assert receipt["physics"] == physics["artifact"]
            assert receipt["schedule"] == schedule["artifact"]
            await call("workspace_select", {"name": "foreign"})
            for tool, reference in (
                ("general_simulation_prepared", receipt["artifact"]),
                ("general_simulation_prepare", assembly["artifact"]),
            ):
                assert (await client.call_tool(tool, reference)).isError
        async with managed_launcher(root, "--enable-general-models") as client:
            value(await client.call_tool("workspace_select", {"name": "authored"}))
            assert (
                value(await client.call_tool("general_simulation_prepared", receipt["artifact"]))
                == receipt
            )
            assert (
                value(await client.call_tool("general_simulation_inspect", assembly["artifact"]))
                == assembly
            )

    asyncio.run(exercise())
