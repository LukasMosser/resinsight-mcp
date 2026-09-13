"""Create original regional inputs through a clean installed public MCP launcher."""

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
from typing import Any
from uuid import uuid4

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROWS = {
    "PVTW": [[200, 1.01, 0.00004, 0.5, 0]],
    "ROCK": [[200, 0.00004]],
    "DENSITY": [[800, 1000, 1.2]],
    "PVDG": [[1, 1, 0.01], [100, 0.01, 0.02], [300, 0.0035, 0.03]],
    "PVTO": [
        [0, 1, 1, 2],
        [0, 300, 0.99, 2.2],
        [100, 200, 1.2, 1.2],
        [100, 400, 1.18, 1.3],
        [150, 300, 1.3, 1],
    ],
    "SWOF": [[0, 0, 1, 0], [1, 1, 0, 0]],
    "SGOF": [[0, 0, 1, 0], [1, 1, 0, 0]],
    "EQUIL": [[2250, 200, 2700, 0, 1900, 0, 1, 0, 0]],
    "RSVD": [[1900, 100], [2700, 100]],
}


class Acceptance:
    def __init__(self, output, source_commit):
        self.output, self.source_commit = output, source_commit
        self.session = f"session_{uuid4().hex}"
        self.calls, self.failures, self.largest_response, self.peak_rss = 0, 0, 0, 0

    async def sample(self, stop):
        while not stop.is_set():
            for child in psutil.Process().children():
                try:
                    self.peak_rss = max(self.peak_rss, child.memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
            await asyncio.sleep(0.05)

    async def call(self, client, name, arguments, rejected=False):
        self.calls += 1
        start, stop = time.monotonic(), asyncio.Event()
        sampler = asyncio.create_task(self.sample(stop))
        try:
            result = await client.call_tool(name, arguments)
        finally:
            stop.set()
            await sampler
        record = {
            "tool": name,
            "arguments": arguments,
            "response": result.structuredContent,
            "is_error": result.isError,
            "seconds": time.monotonic() - start,
        }
        (self.output / f"call-{self.calls:04d}-{name}.json").write_text(
            json.dumps(record, indent=2)
        )
        self.largest_response = max(
            self.largest_response, len(json.dumps(result.structuredContent))
        )
        print(
            f"{self.calls:04d} {name}: {record['seconds']:.3f}s error={result.isError}", flush=True
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
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        )
        with (self.output / "mcp-stderr.log").open("a") as errors:
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=120)
                ) as client:
                    await client.initialize()
                    yield client

    async def array(self, client, values, unit, dtype="float64"):
        parts = []
        for offset in range(0, len(values), 32768):
            stored = await self.call(
                client,
                "array_upload",
                {
                    "session_id": self.session,
                    "dtype": dtype,
                    "unit": unit,
                    "values": values[offset : offset + 32768],
                },
            )
            parts.append(stored["artifact"])
        if len(parts) == 1:
            return parts[0]
        return (
            await self.call(client, "array_join", {"session_id": self.session, "parts": parts})
        )["artifact"]

    async def model(self, client, unit):
        large = unit == "m"
        return await self.call(
            client,
            "geological_generate",
            {
                "session_id": self.session,
                "name": f"Original physics acceptance {unit}",
                "shape": {"nx": 100, "ny": 200, "nz": 50} if large else {"nx": 2, "ny": 2, "nz": 2},
                "extent_x": 6000,
                "extent_y": 10000,
                "top_depth": 2000,
                "thickness": 500,
                "length_unit": unit,
                "datum": "Original synthetic depth",
                "folds": [{"amplitude": 40, "wavelength_x": 4000, "wavelength_y": 6000}],
                "faults": [{"intercept": 3200, "throw": 50}],
                "bands": [
                    {"bottom_fraction": 0.5, "porosity": 0.2, "permeability_md": 1000},
                    {"bottom_fraction": 0.7, "porosity": 0.15, "permeability_md": 10},
                    {"bottom_fraction": 1, "porosity": 0.25, "permeability_md": 500},
                ],
            },
        )

    async def physics(self, client, model, unit):
        metric = unit == "METRIC"
        schema = await self.call(client, "general_physics_schema", {"unit_system": unit})
        if metric:
            region_map = await self.array(
                client, [1] * 500000 + [2] * 200000 + [3] * 300000, "1", "int64"
            )
            mapping = {"kind": "array", "array": region_map}
        else:
            mapping = {"kind": "uniform", "value": 1}
        current = await self.call(
            client,
            "general_physics_create",
            {
                "model": model["model"],
                "profile": schema["profile"],
                "regions": [
                    {"keyword": key, "values": mapping} for key in ("PVTNUM", "SATNUM", "EQLNUM")
                ],
            },
        )
        tables: list[dict[str, Any]] = []
        for definition in schema["tables"]:
            rows = ROWS[definition["keyword"]]
            columns = []
            for column, numbers in zip(definition["columns"], zip(*rows, strict=True), strict=True):
                columns.append(
                    {
                        "name": column["name"],
                        "array": await self.array(
                            client, list(numbers), column["unit"], column["dtype"]
                        ),
                    }
                )
            tables.append({"keyword": definition["keyword"], "region": 1, "columns": columns})
        all_tables = [
            dict(table, region=region)
            for region in range(1, 4 if metric else 2)
            for table in tables
        ]
        for offset in range(0, len(all_tables), 4):
            current = await self.call(
                client,
                "general_physics_edit",
                {"parent": current["artifact"], "tables": all_tables[offset : offset + 4]},
            )
        assert current["complete"] and not current["simulation_ready"]
        if not metric:
            return current
        parent = current
        definition = next(table for table in schema["tables"] if table["keyword"] == "PVDG")
        numbers = (
            [1 + i / 100 for i in range(70001)],
            [1 / (1 + i / 100) for i in range(70001)],
            [0.01] * 70001,
        )
        columns = [
            {"name": column["name"], "array": await self.array(client, values, column["unit"])}
            for column, values in zip(definition["columns"], numbers, strict=True)
        ]
        child = await self.call(
            client,
            "general_physics_edit",
            {
                "parent": parent["artifact"],
                "tables": [{"keyword": "PVDG", "region": 1, "columns": columns}],
            },
        )
        assert child["complete"] and child["table_count"] == 27 and child["row_count"] == 70052
        found = []
        for offset in range(0, 27, 2):
            page = await self.call(
                client,
                "general_physics_tables",
                {"physics": child["artifact"], "offset": offset, "count": 2},
            )
            found.extend(page["tables"])
        assert (
            next(t for t in found if t["keyword"] == "PVDG" and t["region"] == 1)["rows"] == 70001
        )
        tail = await self.call(
            client, "array_range", {"array": columns[0]["array"], "offset": 69999, "count": 2}
        )
        assert tail["values"] == [700.99, 701.0]
        await self.call(
            client,
            "general_physics_edit",
            {"parent": child["artifact"], "tables": all_tables[:5]},
            rejected=True,
        )
        await self.call(
            client,
            "general_physics_tables",
            {"physics": child["artifact"], "count": 3},
            rejected=True,
        )
        invalid = await self.array(client, [200], "psia")
        rock = next(table for table in tables if table["keyword"] == "ROCK")
        await self.call(
            client,
            "general_physics_edit",
            {
                "parent": child["artifact"],
                "tables": [
                    dict(rock, columns=[{"name": "pressure", "array": invalid}, rock["columns"][1]])
                ],
            },
            rejected=True,
        )
        assert await self.call(client, "general_physics_inspect", parent["artifact"]) == parent
        self.parent = parent
        return child

    async def run(self):
        started = time.monotonic()
        (self.output / "policy.json").write_text(
            json.dumps({"request_records": 4, "response_records": 2})
        )
        async with self.client() as client:
            (self.output / "tools.json").write_text(
                (await client.list_tools()).model_dump_json(indent=2)
            )
            for name in ("authored", "foreign"):
                await self.call(client, "workspace_create", {"name": name})
            await self.call(client, "workspace_select", {"name": "authored"})
            await self.call(
                client,
                "session_create",
                {"session_id": self.session, "name": "Original physics acceptance"},
            )
            metric_model = await self.model(client, "m")
            metric = await self.physics(client, metric_model, "METRIC")
            field = await self.physics(client, await self.model(client, "ft"), "FIELD")
            await self.call(client, "workspace_select", {"name": "foreign"})
            await self.call(client, "general_physics_inspect", metric["artifact"], rejected=True)
        async with self.client() as client:
            await self.call(client, "workspace_select", {"name": "authored"})
            for info in (metric, self.parent, field):
                assert await self.call(client, "general_physics_inspect", info["artifact"]) == info
        summary = {
            "source_commit": self.source_commit,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("resinsight-mcp", "mcp", "numpy", "pydantic")
            },
            "model": metric_model,
            "metric": metric,
            "field": field,
            "calls": self.calls,
            "expected_rejections": self.failures,
            "seconds": time.monotonic() - started,
            "peak_mcp_rss_mib": self.peak_rss / 1024**2,
            "largest_structured_response_characters": self.largest_response,
            "workspace_mib": sum(
                p.stat().st_size for p in (self.output / "workspaces").rglob("*") if p.is_file()
            )
            / 1024**2,
            "restart_verified": True,
            "native_application_tested": False,
            "parser_validation_tested": False,
            "simulation_tested": False,
        }
        (self.output / "summary.json").write_text(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(Acceptance(args.output, args.source_commit).run())


if __name__ == "__main__":
    main()
