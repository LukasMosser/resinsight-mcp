"""Verify schedule publication through the production managed MCP launcher."""

import asyncio

from test_general_launcher import create_model
from test_launcher import managed_launcher, value

from resinsight_mcp.contracts.identifiers import SessionId


def producer_event(day, rate):
    return {
        "elapsed_days": day,
        "action": {
            "kind": "control",
            "role": "producer",
            "status": "OPEN",
            "mode": "ORAT",
            "rate": {"value": rate, "unit": "sm3/day"},
            "bhp": {"value": 200, "unit": "bar"},
        },
    }


async def public_plan(client, model):
    refs = []
    for values, unit in (([10, 10, 1500, 10, 10, 1600], "m"), ([0, 100, 0.2], "m"), ([0], "1")):
        refs.append(
            value(
                await client.call_tool(
                    "array_upload",
                    {
                        "session_id": model["session_id"],
                        "dtype": "float64",
                        "values": values,
                        "unit": unit,
                    },
                )
            )["artifact"]
        )
    return value(
        await client.call_tool(
            "general_well_define",
            {
                "model": model,
                "name": "PROD",
                "role": "producer",
                "targets": refs[0],
                "intervals": refs[1],
                "skins": refs[2],
                "sampling_distance": 1,
            },
        )
    )


def test_schedule_queries_and_differences_survive_managed_restart(tmp_path):
    async def exercise():
        root = tmp_path / "workspaces"
        async with managed_launcher(root, "--enable-general-models") as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {
                "general_schedule_edit",
                "general_schedule_state",
                "general_schedule_diff",
            } <= tools
            for name in ("authored", "foreign"):
                value(await client.call_tool("workspace_create", {"name": name}))
            value(await client.call_tool("workspace_select", {"name": "authored"}))
            model = (await create_model(client, str(SessionId.new())))["model"]
            plan = await public_plan(client, model)
            timeline = value(
                await client.call_tool(
                    "array_upload",
                    {
                        "session_id": model["session_id"],
                        "dtype": "float64",
                        "unit": "day",
                        "values": [0, 1, 2, 4000],
                    },
                )
            )
            initial = value(
                await client.call_tool(
                    "general_schedule_create",
                    {
                        "model": model,
                        "start_date": "2026-09-13",
                        "report_days": timeline["artifact"],
                    },
                )
            )
            parent = value(
                await client.call_tool(
                    "general_schedule_edit",
                    {
                        "parent": initial["artifact"],
                        "wells": [
                            {
                                "plan": plan["artifact"],
                                "events": [
                                    producer_event(0, 100),
                                    {
                                        "elapsed_days": 1,
                                        "action": {"kind": "status", "status": "SHUT"},
                                    },
                                    {
                                        "elapsed_days": 2,
                                        "action": {"kind": "status", "status": "OPEN"},
                                    },
                                ],
                            }
                        ],
                    },
                )
            )
            child = value(
                await client.call_tool(
                    "general_schedule_edit",
                    {
                        "parent": parent["artifact"],
                        "wells": [{"plan": plan["artifact"], "events": [producer_event(2, 300)]}],
                    },
                )
            )
            query = {"schedule": child["artifact"], "well": "PROD", "report_index": 3}
            expected = value(await client.call_tool("general_schedule_state", query))
            assert expected["control"]["rate"]["value"] == 300
            diff = value(
                await client.call_tool(
                    "general_schedule_diff",
                    {
                        "before": parent["artifact"],
                        "after": child["artifact"],
                        "count": 1,
                    },
                )
            )
            assert diff["wells"][0]["changed_events"] == 1
            value(await client.call_tool("workspace_select", {"name": "foreign"}))
            assert (await client.call_tool("general_schedule_state", query)).isError
            assert (
                await client.call_tool(
                    "general_schedule_edit",
                    {"parent": parent["artifact"], "remove_wells": ["PROD"]},
                )
            ).isError
        async with managed_launcher(root, "--enable-general-models") as client:
            value(await client.call_tool("workspace_select", {"name": "authored"}))
            assert (
                value(await client.call_tool("general_schedule_inspect", child["artifact"]))
                == child
            )
            assert value(await client.call_tool("general_schedule_state", query)) == expected
            old = value(
                await client.call_tool(
                    "general_schedule_state",
                    {
                        "schedule": parent["artifact"],
                        "well": "PROD",
                        "report_index": 3,
                    },
                )
            )
            assert old["control"]["rate"]["value"] == 100
            history = value(
                await client.call_tool(
                    "general_schedule_history",
                    {
                        "schedule": child["artifact"],
                        "well": "PROD",
                        "offset": 1,
                        "count": 1,
                    },
                )
            )
            assert history["events"][0]["action"]["status"] == "SHUT"
            assert history["next_offset"] == 2

    asyncio.run(exercise())
