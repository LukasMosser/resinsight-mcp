"""Create and inspect geological grids through the installed public MCP launcher."""

import argparse
import asyncio
import base64
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

import numpy as np
import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ImageContent


class Acceptance:
    def __init__(self, output: Path, executable: Path, nx: int, ny: int, nz: int) -> None:
        self.output = output
        self.executable = executable
        self.shape = {"nx": nx, "ny": ny, "nz": nz}
        self.calls = 0
        self.images = 0
        self.native_pid = None
        self.peak_rss = {"mcp_server": 0, "resinsight": 0}
        self.session_id = f"session_{uuid4().hex}"

    async def call(self, client, name: str, arguments: dict):
        self.calls += 1
        start = time.monotonic()
        stop = asyncio.Event()
        monitor = asyncio.create_task(self.sample_memory(stop))
        try:
            response = await client.call_tool(name, arguments)
        finally:
            stop.set()
            await monitor
        elapsed = time.monotonic() - start
        record = {
            "tool": name,
            "arguments": arguments,
            "seconds": elapsed,
            "response": response.structuredContent,
            "is_error": response.isError,
        }
        (self.output / f"call-{self.calls:03}-{name}.json").write_text(json.dumps(record, indent=2))
        print(f"{self.calls:03} {name}: {elapsed:.2f}s error={response.isError}", flush=True)
        assert not response.isError, response.structuredContent
        assert response.structuredContent is not None
        for content in response.content:
            if isinstance(content, ImageContent):
                self.images += 1
                (self.output / f"native-{self.images:02}.png").write_bytes(
                    base64.b64decode(content.data)
                )
        result = response.structuredContent["outcome"]["value"]
        if name == "application_launch":
            self.native_pid = result["process"]["pid"]
        return result

    async def sample_memory(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            for child in psutil.Process().children():
                try:
                    self.peak_rss["mcp_server"] = max(
                        self.peak_rss["mcp_server"], child.memory_info().rss
                    )
                except psutil.NoSuchProcess:
                    pass
            if self.native_pid is not None:
                try:
                    native_rss = psutil.Process(self.native_pid).memory_info().rss
                    self.peak_rss["resinsight"] = max(self.peak_rss["resinsight"], native_rss)
                except psutil.NoSuchProcess:
                    pass
            await asyncio.sleep(0.05)

    @asynccontextmanager
    async def client(self, create: bool):
        options = ["--create-workspace"] if create else []
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "resinsight_mcp.mcp",
                "--workspace-root",
                str(self.output / "workspace"),
                "--enable-general-models",
                "--resinsight-log-directory",
                str(self.output),
                *options,
            ],
            env={key: val for key, val in os.environ.items() if key != "PYTHONPATH"},
        )
        with (self.output / "mcp-stderr.log").open("a") as errors:
            async with stdio_client(parameters, errlog=errors) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=600)
                ) as client:
                    await client.initialize()
                    yield client

    async def generate(self, client):
        return await self.call(
            client,
            "geological_generate",
            {
                "session_id": self.session_id,
                "name": "Folded and faulted channel reservoir",
                "shape": self.shape,
                "extent_x": 6000,
                "extent_y": 10000,
                "top_depth": 2100,
                "thickness": 450,
                "length_unit": "m",
                "datum": "Original local model, depth positive down",
                "folds": [
                    {"amplitude": 220, "wavelength_x": 7000, "wavelength_y": 11000},
                    {"amplitude": 65, "wavelength_x": 2700, "wavelength_y": 5000, "phase": 0.5},
                ],
                "faults": [
                    {"intercept": 1700, "slope": 0.12, "throw": 150},
                    {"intercept": 4100, "slope": -0.06, "throw": -95},
                ],
                "bands": [
                    {"bottom_fraction": 0.5, "porosity": 0.22, "permeability_md": 1000},
                    {"bottom_fraction": 0.7, "porosity": 0.1, "permeability_md": 10},
                    {"bottom_fraction": 1, "porosity": 0.18, "permeability_md": 500},
                ],
                "channel": {
                    "center_y": 4800,
                    "amplitude": 1700,
                    "wavelength": 6000,
                    "width": 450,
                    "permeability_multiplier": 5,
                    "porosity_increment": 0.04,
                },
                "active_ellipse": True,
                "thickness_variation": 0.22,
            },
        )

    async def verify_faults(self, client, loaded):
        nx, ny, nz = self.shape.values()
        j = ny // 2
        y = (j + 0.5) * 10000 / ny
        fault_x = 1700 + 0.12 * y
        right = next(i for i in range(nx) if (i + 0.5) * 6000 / nx > fault_x)
        indices = [j * nx + right - 1, j * nx + right, (nz - 1) * nx * ny + j * nx + right]
        verification = await self.call(
            client, "geological_verify", {"loaded": loaded, "global_indices": indices}
        )
        cells = verification["cells"]
        assert abs(cells[1]["corners"][0][2] - cells[0]["corners"][1][2] - 150) < 0.001
        assert cells[2]["corners"][4][2] > cells[1]["corners"][0][2]
        assert max(c["maximum_coordinate_error"] for c in cells) < 0.001
        return verification

    async def render(self, client, loaded):
        cameras = [
            {
                "position": [7000, -16000, 15000],
                "target": [0, 0, 0],
                "up": [0, 0, 1],
                "projection": "orthographic",
                "parallel_scale": 6500,
            },
            {
                "position": [0, -15000, 0],
                "target": [0, 0, 0],
                "up": [0, 0, 1],
                "projection": "orthographic",
                "parallel_scale": 2200,
            },
            {
                "position": [0, 0, 18000],
                "target": [0, 0, 0],
                "up": [0, 1, 0],
                "projection": "orthographic",
                "parallel_scale": 5500,
            },
        ]
        for number, camera in enumerate(cameras):
            result = await self.call(
                client,
                "geological_render",
                {
                    "loaded": loaded,
                    "property": "PERMX",
                    "camera": camera,
                    "vertical_exaggeration": 3,
                    "slice_j": self.shape["ny"] // 2 if number == 1 else None,
                    "width": 1440,
                    "height": 1000,
                },
            )
            assert result["observation"]["outcome"]["status"] == "success", result

    async def run(self):
        connection = None
        async with self.client(True) as client:
            await self.call(
                client,
                "session_create",
                {"session_id": self.session_id, "name": "Geological acceptance"},
            )
            await self.call(client, "general_capabilities", {})
            generated = await self.generate(client)
            nx, ny, nz = self.shape.values()
            x, y = np.meshgrid((np.arange(nx) + 0.5) / nx, (np.arange(ny) + 0.5) / ny)
            expected_active = (
                int(np.count_nonzero(((x - 0.5) / 0.5) ** 2 + ((y - 0.5) / 0.5) ** 2 < 1)) * nz
            )
            assert generated["active_cells"] == expected_active
            assert generated["shape"] == self.shape
            connection = await self.call(
                client,
                "application_launch",
                {"session_id": self.session_id, "executable": str(self.executable)},
            )
            try:
                loaded = await self.call(
                    client,
                    "geological_load",
                    {"model": generated["model"], "context": connection["context"]},
                )
                assert loaded["global_cells"] == nx * ny * nz
                verification = await self.verify_faults(client, loaded)
                await self.render(client, loaded)
                state = await self.call(client, "project_inspect", {"session_id": self.session_id})
                saved = await self.call(
                    client,
                    "project_save",
                    {"context": state["context"], "path": str(self.output / "geology.rsp")},
                )
                closed = await self.call(client, "project_close", {"context": saved["context"]})
                reopened = await self.call(
                    client,
                    "project_open",
                    {"context": closed["context"], "path": str(self.output / "geology.rsp")},
                )
                assert len([o for o in reopened["objects"] if o["ref"]["kind"] == "case"]) == 1
                restored = await self.call(
                    client,
                    "geological_restore",
                    {
                        "receipt": loaded["receipt"],
                        "case": next(
                            o["ref"] for o in reopened["objects"] if o["ref"]["kind"] == "case"
                        ),
                        "view": next(
                            o["ref"] for o in reopened["objects"] if o["ref"]["kind"] == "view"
                        ),
                    },
                )
                await self.verify_faults(client, restored)
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
            restored = await self.call(client, "geological_inspect", generated["model"])
            assert restored == generated
        (self.output / "summary.json").write_text(
            json.dumps(
                {
                    "global_cells": nx * ny * nz,
                    "active_cells": expected_active,
                    "model": generated,
                    "verification": verification,
                    "calls": self.calls,
                    "images": self.images,
                    "sampled_peak_rss_bytes": self.peak_rss,
                    "memory_sample_interval_seconds": 0.05,
                    "host": {
                        "platform": platform.platform(),
                        "physical_memory_bytes": psutil.virtual_memory().total,
                        "logical_cpus": psutil.cpu_count(),
                    },
                    "versions": {
                        name: importlib.metadata.version(name)
                        for name in (
                            "resinsight-mcp",
                            "mcp",
                            "rips",
                            "numpy",
                            "pydantic",
                            "grpcio",
                            "protobuf",
                        )
                    },
                    "installed_python": sys.executable,
                    "native_executable": str(self.executable),
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resinsight", type=Path, required=True)
    parser.add_argument("--nx", type=int, default=100)
    parser.add_argument("--ny", type=int, default=200)
    parser.add_argument("--nz", type=int, default=50)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(Acceptance(args.output.resolve(), args.resinsight, args.nx, args.ny, args.nz).run())


if __name__ == "__main__":
    main()
