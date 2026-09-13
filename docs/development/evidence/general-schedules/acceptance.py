"""Exercise immutable schedules through a clean installed public MCP launcher."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class Acceptance:
    def __init__(self, output, source_commit):
        self.output = output
        self.source_commit = source_commit
        self.session = f"session_{uuid4().hex}"
        self.calls = 0
        self.failures = 0
        self.peak_rss = 0
        self.largest_response = 0
        self.saved_states = []

    async def sample(self, stop):
        while not stop.is_set():
            for child in psutil.Process().children():
                try:
                    self.peak_rss = max(self.peak_rss, child.memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
            await asyncio.sleep(0.05)

    async def call(self, client, tool, arguments, rejected=False):
        self.calls += 1
        start = time.monotonic()
        stop = asyncio.Event()
        sampler = asyncio.create_task(self.sample(stop))
        try:
            result = await client.call_tool(tool, arguments)
        finally:
            stop.set()
            await sampler
        record = {
            "tool": tool,
            "arguments": arguments,
            "seconds": time.monotonic() - start,
            "response": result.structuredContent,
            "is_error": result.isError,
        }
        (self.output / f"call-{self.calls:04d}-{tool}.json").write_text(
            json.dumps(record, indent=2)
        )
        self.largest_response = max(
            self.largest_response, len(json.dumps(result.structuredContent))
        )
        print(
            f"{self.calls:04d} {tool}: {record['seconds']:.3f}s error={result.isError}", flush=True
        )
        assert result.isError == rejected, record
        if rejected:
            self.failures += 1
            return record
        return result.structuredContent["outcome"]["value"]

    @asynccontextmanager
    async def client(self):
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "resinsight_mcp.mcp",
                "--workspaces-root",
                str(self.output / "workspaces"),
                "--enable-general-models",
                "--authoring-policy",
                str(self.output / "policy.json"),
            ],
            env={key: val for key, val in os.environ.items() if key != "PYTHONPATH"},
        )
        with (self.output / "mcp-stderr.log").open("a") as errors:
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=120)
                ) as client:
                    await client.initialize()
                    yield client

    async def array(self, client, values, unit):
        parts = []
        for offset in range(0, len(values), 1000):
            result = await self.call(
                client,
                "array_upload",
                {
                    "session_id": self.session,
                    "dtype": "float64",
                    "unit": unit,
                    "values": values[offset : offset + 1000],
                },
            )
            parts.append(result["artifact"])
        if len(parts) == 1:
            return parts[0]
        return (
            await self.call(client, "array_join", {"session_id": self.session, "parts": parts})
        )["artifact"]

    @staticmethod
    def control(role, rate):
        return {
            "kind": "control",
            "role": role,
            "injection_phase": "WATER" if role == "injector" else None,
            "status": "OPEN",
            "mode": "RATE" if role == "injector" else "ORAT",
            "rate": {"value": rate, "unit": "sm3/day"},
            "bhp": {"value": 200, "unit": "bar"},
        }

    async def inputs(self, client):
        model = await self.call(
            client,
            "geological_generate",
            {
                "session_id": self.session,
                "name": "Million-cell schedule target",
                "shape": {"nx": 100, "ny": 200, "nz": 50},
                "extent_x": 6000,
                "extent_y": 10000,
                "top_depth": 2000,
                "thickness": 500,
                "length_unit": "m",
                "datum": "Local positive-down depth",
                "bands": [
                    {"bottom_fraction": 0.5, "porosity": 0.2, "permeability_md": 1000},
                    {"bottom_fraction": 0.7, "porosity": 0.15, "permeability_md": 10},
                    {"bottom_fraction": 1, "porosity": 0.25, "permeability_md": 500},
                ],
            },
        )
        assert model["active_cells"] == 1_000_000
        intervals = await self.array(client, [100, 600, 0.2], "m")
        skins = await self.array(client, [0], "1")
        plans = []
        for index, name in enumerate(
            ["PROD_A", "PROD_B", "INJ_C"] + [f"EXTRA_{i:02d}" for i in range(33)]
        ):
            i, j = ((0, 0), (99, 199), (50, 100))[min(index, 2)]
            targets = await self.array(
                client,
                [(i + 0.5) * 60, (j + 0.5) * 50, 1900, (i + 0.5) * 60, (j + 0.5) * 50, 2600],
                "m",
            )
            plans.append(
                await self.call(
                    client,
                    "general_well_define",
                    {
                        "model": model["model"],
                        "name": name,
                        "role": "injector" if index == 2 else "producer",
                        "injection_phase": "WATER" if index == 2 else None,
                        "targets": targets,
                        "intervals": intervals,
                        "skins": skins,
                        "sampling_distance": 5,
                    },
                )
            )
        timeline = await self.array(client, list(range(4001)), "day")
        initial = await self.call(
            client,
            "general_schedule_create",
            {
                "model": model["model"],
                "start_date": "2026-09-13",
                "report_days": timeline,
            },
        )
        return model, plans, initial

    async def author(self, client, plans, initial):
        current = initial
        for plan in plans:
            role = plan["role"]
            events = [{"elapsed_days": 0, "action": self.control(role, 100)}]
            if plan["name"] in ("PROD_A", "PROD_B", "INJ_C"):
                events += [
                    {"elapsed_days": 1, "action": {"kind": "status", "status": "SHUT"}},
                    {"elapsed_days": 2, "action": {"kind": "status", "status": "OPEN"}},
                    {"elapsed_days": 3, "action": self.control(role, 200)},
                ]
            current = await self.call(
                client,
                "general_schedule_edit",
                {
                    "parent": current["artifact"],
                    "wells": [{"plan": plan["artifact"], "events": events}],
                },
            )
        for start in range(0, 600, 60):
            current = await self.call(
                client,
                "general_schedule_edit",
                {
                    "parent": current["artifact"],
                    "wells": [
                        {
                            "plan": plans[3]["artifact"],
                            "events": [
                                {"elapsed_days": day, "action": self.control("producer", day + 1)}
                                for day in range(start, start + 60)
                            ],
                        }
                    ],
                },
            )
        assert current["well_count"] == 36 and current["event_count"] == 644
        return current

    async def verify(self, client, schedule, plans, restart=False):
        states = []
        for plan in plans[:3]:
            for index in (0, 1, 2, 3, 4, 4000):
                state = await self.call(
                    client,
                    "general_schedule_state",
                    {
                        "schedule": schedule["artifact"],
                        "well": plan["name"],
                        "report_index": index,
                    },
                )
                assert state["control"]["status"] == ("SHUT" if index == 1 else "OPEN")
                assert state["control"]["rate"]["value"] == (100 if index < 3 else 200)
                states.append(state)
        days = []
        for offset in range(0, 600, 16):
            page = await self.call(
                client,
                "general_schedule_history",
                {
                    "schedule": schedule["artifact"],
                    "well": plans[3]["name"],
                    "offset": offset,
                    "count": 16,
                },
            )
            for event in page["events"]:
                days.append(event["elapsed_days"])
                assert event["action"]["rate"]["value"] == event["elapsed_days"] + 1
        assert days == list(range(600))
        if restart:
            assert states == self.saved_states
        else:
            self.saved_states = states
        return states

    async def edits(self, client, parent, plans):
        replacement = await self.array(client, [0, 0.5] + list(range(1, 4001)), "day")
        child = await self.call(
            client,
            "general_schedule_edit",
            {
                "parent": parent["artifact"],
                "report_days": replacement,
                "wells": [
                    {
                        "plan": plans[0]["artifact"],
                        "events": [{"elapsed_days": 3, "action": self.control("producer", 300)}],
                    }
                ],
            },
        )
        for report, rate, status in ((1, 100, "OPEN"), (2, 100, "SHUT"), (4, 300, "OPEN")):
            state = await self.call(
                client,
                "general_schedule_state",
                {
                    "schedule": child["artifact"],
                    "well": "PROD_A",
                    "report_index": report,
                },
            )
            assert (
                state["control"]["rate"]["value"] == rate and state["control"]["status"] == status
            )
        differences = []
        for offset in range(0, 36, 16):
            diff = await self.call(
                client,
                "general_schedule_diff",
                {
                    "before": parent["artifact"],
                    "after": child["artifact"],
                    "offset": offset,
                    "count": 16,
                },
            )
            assert diff["report_times_changed"]
            differences.extend(diff["wells"])
        assert len(differences) == 1 and differences[0]["name"] == "PROD_A"
        assert differences[0]["changed_events"] == 1
        invalid = await self.array(client, [0] + list(range(2, 4001)), "day")
        await self.call(
            client,
            "general_schedule_edit",
            {"parent": child["artifact"], "report_days": invalid},
            rejected=True,
        )
        await self.call(
            client,
            "general_schedule_history",
            {"schedule": child["artifact"], "well": "PROD_A", "count": 17},
            rejected=True,
        )
        assert await self.call(client, "general_schedule_inspect", parent["artifact"]) == parent
        return child

    async def run(self):
        (self.output / "policy.json").write_text(
            json.dumps({"request_records": 64, "response_records": 16})
        )
        async with self.client() as client:
            tools = (await client.list_tools()).model_dump(mode="json")
            (self.output / "tools.json").write_text(json.dumps(tools, indent=2))
            for name in ("authored", "foreign"):
                await self.call(client, "workspace_create", {"name": name})
            await self.call(client, "workspace_select", {"name": "authored"})
            await self.call(
                client,
                "session_create",
                {"session_id": self.session, "name": "Schedule acceptance"},
            )
            capabilities = await self.call(client, "general_capabilities", {})
            assert (
                capabilities["schedule_report_ceiling"] is None
                and capabilities["schedule_event_ceiling"] is None
            )
            model, plans, initial = await self.inputs(client)
            parent = await self.author(client, plans, initial)
            await self.verify(client, parent, plans)
            child = await self.edits(client, parent, plans)
            await self.call(client, "workspace_select", {"name": "foreign"})
            await self.call(client, "general_schedule_inspect", parent["artifact"], rejected=True)
            await self.call(
                client,
                "general_schedule_edit",
                {"parent": parent["artifact"], "remove_wells": ["PROD_A"]},
                rejected=True,
            )
        async with self.client() as client:
            await self.call(client, "workspace_select", {"name": "authored"})
            assert await self.call(client, "general_schedule_inspect", child["artifact"]) == child
            await self.verify(client, parent, plans, restart=True)
            names = []
            for offset in range(0, 36, 16):
                page = await self.call(
                    client,
                    "general_schedule_wells",
                    {"schedule": parent["artifact"], "offset": offset, "count": 16},
                )
                names.extend(well["name"] for well in page["wells"])
            assert names == sorted(plan["name"] for plan in plans)
        (self.output / "summary.json").write_text(
            json.dumps(
                {
                    "implementation_commit": self.source_commit,
                    "python": sys.executable,
                    "python_version": platform.python_version(),
                    "platform": platform.platform(),
                    "packages": {
                        name: importlib.metadata.version(name)
                        for name in ("resinsight-mcp", "mcp", "numpy", "pydantic")
                    },
                    "model": model,
                    "parent": parent,
                    "child": child,
                    "states": self.saved_states,
                    "public_calls": self.calls,
                    "expected_failures": self.failures,
                    "peak_mcp_rss_bytes": self.peak_rss,
                    "largest_structured_response_characters": self.largest_response,
                    "complete_mcp_restart_verified": True,
                    "native_application_launched": False,
                    "simulation_executed": False,
                },
                indent=2,
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(Acceptance(args.output, args.source_commit).run())


if __name__ == "__main__":
    main()
