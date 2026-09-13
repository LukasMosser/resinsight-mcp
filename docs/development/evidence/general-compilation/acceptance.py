"""Compile original complex geological inputs through MCP and native ResInsight."""

import argparse
import asyncio
import importlib.metadata
import json
import platform
import runpy
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[1]
WellAcceptance = runpy.run_path(str(BASE / "general-wells" / "well_acceptance.py"))[
    "WellAcceptance"
]
geology = runpy.run_path(str(BASE / "general-models" / "acceptance.py"))["Acceptance"]
physics = runpy.run_path(str(BASE / "general-physics" / "acceptance.py"))


class CompilationAcceptance(WellAcceptance):
    async def array(self, client, values, unit, dtype="float64"):
        return await physics["Acceptance"].array(
            self, client, np.asarray(values).ravel().tolist(), unit, dtype
        )

    def __init__(self, output, executable, source_commit, million):
        super().__init__(output, executable, *(100, 200, 50) if million else (10, 20, 10), "m")
        self.session = self.session_id
        self.source_commit = source_commit

    async def fluid(self, client, model):
        schema = await self.call(client, "general_physics_schema", {"unit_system": "METRIC"})
        nx, ny, nz = self.shape.values()
        regions = await self.array(
            client,
            [1] * (nx * ny * (nz // 2))
            + [2] * (nx * ny * (nz // 5))
            + [3] * (nx * ny * (nz - nz // 2 - nz // 5)),
            "1",
            "int64",
        )
        fluid = await self.call(
            client,
            "general_physics_create",
            {
                "model": model["model"],
                "profile": schema["profile"],
                "regions": [
                    {"keyword": key, "values": {"kind": "array", "array": regions}}
                    for key in ("PVTNUM", "SATNUM", "EQLNUM")
                ],
            },
        )
        tables = []
        for definition in schema["tables"]:
            data = list(physics["ROWS"][definition["keyword"]])
            if definition["keyword"] == "PVTO":
                data.append([150, 500, 1.28, 1.1])
            columns = []
            for column, numbers in zip(definition["columns"], zip(*data, strict=True), strict=True):
                columns.append(
                    {
                        "name": column["name"],
                        "array": await self.array(
                            client, list(numbers), column["unit"], column["dtype"]
                        ),
                    }
                )
            for region in range(1, 4):
                tables.append(
                    {"keyword": definition["keyword"], "region": region, "columns": columns}
                )
        return await self.call(
            client, "general_physics_edit", {"parent": fluid["artifact"], "tables": tables}
        )

    def events(self, role, rate):
        control = {
            "kind": "control",
            "role": role,
            "status": "OPEN",
            "mode": "ORAT" if role == "producer" else "RATE",
            "rate": {"value": rate, "unit": "sm3/day"},
            "bhp": {"value": 200, "unit": "bar"},
        }
        if role == "injector":
            control["injection_phase"] = "WATER"
        return [
            {"elapsed_days": 0, "action": control},
            {"elapsed_days": 0.5, "action": {"kind": "status", "status": "SHUT"}},
            {"elapsed_days": 1, "action": {"kind": "status", "status": "OPEN"}},
            {
                "elapsed_days": 2,
                "action": dict(control, rate={"value": rate * 2, "unit": "sm3/day"}),
            },
        ]

    async def run(self):
        started = time.monotonic()
        nx, ny, nz = self.shape.values()
        async with self.client(True) as client:
            await self.call(
                client,
                "session_create",
                {"session_id": self.session_id, "name": "Original compilation acceptance"},
            )
            await self.call(client, "general_capabilities", {})
            model = await geology.generate(self, client)
            connection = await self.call(
                client,
                "application_launch",
                {"session_id": self.session_id, "executable": str(self.executable)},
            )
            try:
                loaded = await self.call(
                    client,
                    "geological_load",
                    {"model": model["model"], "context": connection["context"]},
                )
                faults = await geology.verify_faults(self, client, loaded)
                for name, role, i in (
                    ("WEST", "producer", nx // 5),
                    ("EAST", "producer", nx * 4 // 5),
                    ("INJECT", "injector", nx // 2),
                ):
                    j = ny // 2
                    x, y = (i + 0.37) * 6000 / nx, (j + 0.43) * 10000 / ny
                    loaded = await self.make_well(
                        client,
                        loaded,
                        name,
                        role,
                        [[x, y, 1000], [x, y, 3500]],
                        [[0, 2500, 0.2, 0]],
                        [(i, j, k) for k in range(nz)],
                    )
                await geology.render(self, client, loaded)
                fluid = await self.fluid(client, model)
                days = await self.array(client, [0, 0.5, 1, 2], "day")
                schedule = await self.call(
                    client,
                    "general_schedule_create",
                    {"model": model["model"], "start_date": "2026-09-13", "report_days": days},
                )
                schedule = await self.call(
                    client,
                    "general_schedule_edit",
                    {
                        "parent": schedule["artifact"],
                        "wells": [
                            {
                                "plan": entry["state"]["plan"]["artifact"],
                                "events": self.events(entry["state"]["plan"]["role"], 100),
                            }
                            for entry in self.exports
                        ],
                    },
                )
                request = {
                    "schedule": schedule["artifact"],
                    "physics": fluid["artifact"],
                    "group": "GENERAL",
                    "dissolution_limit": {"value": 0, "unit": "sm3/sm3/day"},
                    "write_restart": True,
                    "exports": [entry["export"]["artifact"] for entry in self.exports],
                }
                assembly = await self.call(client, "general_simulation_define", request)
                receipt = await self.call(
                    client, "general_simulation_prepare", assembly["artifact"]
                )
                assert receipt["validation"]["global_cells"] == nx * ny * nz
                assert receipt["validation"]["active_cells"] == model["active_cells"]
                assert receipt["validation"]["connections"] == nz * 3
                assert receipt["validation"]["verified_table_rows"] == 57
                assert receipt["validation"]["control_events"] == 12
                changed = await self.call(
                    client,
                    "general_schedule_edit",
                    {
                        "parent": schedule["artifact"],
                        "wells": [
                            {
                                "plan": self.exports[0]["state"]["plan"]["artifact"],
                                "events": [self.events("producer", 175)[-1]],
                            }
                        ],
                    },
                )
                child = await self.call(
                    client,
                    "general_simulation_define",
                    dict(
                        request,
                        parent=assembly["artifact"],
                        schedule=changed["artifact"],
                        exports=[],
                    ),
                )
                revised = await self.call(client, "general_simulation_prepare", child["artifact"])
                assert receipt["validation"] == revised["validation"]
                assert revised["schedule"] != receipt["schedule"]
                assert not receipt["simulation_executed"] and not revised["simulation_executed"]
            finally:
                await self.call(
                    client,
                    "application_close",
                    {
                        "session_id": self.session_id,
                        "connection_id": connection["context"]["connection_id"],
                        "action": "terminate",
                    },
                )
        async with self.client(False) as client:
            for item in (receipt, revised):
                assert (
                    await self.call(client, "general_simulation_prepared", item["artifact"]) == item
                )
        summary = {
            "source_commit": self.source_commit,
            "native_source_commit": "7c3635788a8b4f4fad5fcd92220ba88252d161b3",
            "platform": platform.platform(),
            "versions": {
                name: importlib.metadata.version(name)
                for name in ("resinsight-mcp", "mcp", "rips", "opm", "numpy")
            },
            "model": model,
            "wells": self.exports,
            "fault_verification": faults,
            "prepared": receipt,
            "revised": revised,
            "calls": self.calls,
            "images": self.images,
            "peak_rss_bytes": self.peak_rss,
            "seconds": time.monotonic() - started,
            "restart_verified": True,
            "simulation_executed": False,
        }
        (self.output / "summary.json").write_text(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--million", action="store_true")
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(
        CompilationAcceptance(args.output, args.executable, args.source_commit, args.million).run()
    )


if __name__ == "__main__":
    main()
