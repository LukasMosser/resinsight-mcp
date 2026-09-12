"""Prove general wells through an installed public MCP server and native ResInsight."""

import argparse
import asyncio
import importlib.metadata
import json
import platform
import runpy
import sys
from pathlib import Path

import numpy as np
import psutil

# Reuse the public SDK client, original call recorder, and memory sampler.
Acceptance = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "general-models" / "acceptance.py")
)["Acceptance"]


class WellAcceptance(Acceptance):
    def __init__(self, output, executable, nx, ny, nz, unit, inactive=False, dense=False):
        super().__init__(output, executable, nx, ny, nz)
        self.unit = unit
        self.inactive = inactive
        self.dense = dense
        self.exports = []

    async def render(self, client, loaded):
        nx, ny, nz = self.shape.values()
        scale = max(nx * 60, ny * 50, (nz * 10 + 200) * 3)
        for section in (False, True):
            result = await self.call(
                client,
                "geological_render",
                {
                    "loaded": loaded,
                    "property": "PERMX",
                    "vertical_exaggeration": 3,
                    "slice_j": ny // 2 if section else None,
                    "width": 1440,
                    "height": 1000,
                    "camera": {
                        "position": [0, -scale * 3, 0]
                        if section
                        else [scale, -scale * 2, scale * 1.5],
                        "target": [0, 0, 0],
                        "up": [0, 0, 1],
                        "projection": "orthographic",
                        "parallel_scale": max(nx * 60 * 0.5, (nz * 10 + 200) * 1.8)
                        if section
                        else scale * 0.7,
                    },
                },
            )
            assert result["observation"]["outcome"]["status"] == "success"

    async def array(self, client, values, unit, dtype="float64"):
        flat = np.asarray(values).ravel().tolist()
        parts = []
        for offset in range(0, len(flat), 128):
            part = await self.call(
                client,
                "array_upload",
                {
                    "session_id": self.session_id,
                    "dtype": dtype,
                    "unit": unit,
                    "values": flat[offset : offset + 128],
                },
            )
            parts.append(part["artifact"])
        if len(parts) == 1:
            return parts[0]
        joined = await self.call(
            client, "array_join", {"session_id": self.session_id, "parts": parts}
        )
        return joined["artifact"]

    async def column(self, client, exported, name):
        column = next(c["array"] for c in exported["columns"] if c["name"] == name)
        values = []
        for offset in range(0, column["count"], 1024):
            page = await self.call(
                client,
                "array_range",
                {
                    "array": column["artifact"],
                    "offset": offset,
                    "count": min(1024, column["count"] - offset),
                },
            )
            values.extend(page["values"])
        return np.asarray(values)

    async def make_well(self, client, loaded, name, role, points, intervals, expected_cells):
        if self.inactive:
            expected_cells = [c for c in expected_cells if c[2] != 2]
        targets = await self.array(client, points, self.unit)
        perforations = await self.array(client, [row[:3] for row in intervals], self.unit)
        skins = await self.array(client, [row[3] for row in intervals], "1")
        plan = await self.call(
            client,
            "general_well_define",
            {
                "model": loaded["model"],
                "name": name,
                "role": role,
                "injection_phase": "WATER" if role == "injector" else None,
                "targets": targets,
                "intervals": perforations,
                "skins": skins,
                "sampling_distance": 5,
            },
        )
        state = await self.call(
            client, "general_well_load", {"loaded": loaded, "plan": plan["artifact"]}
        )
        exported = await self.call(client, "general_well_export", state["binding"])
        cells = await self.column(client, exported, "cells")
        actual = {tuple(map(int, row)) for row in cells.reshape(-1, 3)}
        assert actual == set(expected_cells), (name, actual, set(expected_cells))
        assert exported["count"] == len(expected_cells), exported
        factors = await self.column(client, exported, "factor")
        assert (factors > 0).all() and np.isfinite(factors).all()
        if name in {"PROD_A", "PROD_B", "INJ_C"}:
            kh = await self.column(client, exported, "kh")
            k = cells.reshape(-1, 3)[:, 2]
            fraction = (k + 0.5) / self.shape["nz"]
            expected_kh = np.where(fraction < 0.5, 1000, np.where(fraction < 0.7, 10, 500)) * 10
            darcy = 0.008527 if self.unit == "m" else 0.001127
            expected_factor = (
                2 * np.pi * darcy * expected_kh / np.log(0.14 * np.hypot(60, 50) / 0.1)
            )
            assert np.allclose(factors, expected_factor, rtol=1e-6, atol=1e-6), (
                factors,
                expected_factor,
            )
            assert np.allclose(kh, expected_kh, rtol=1e-6, atol=1e-6), (name, kh, expected_kh)
            assert (await self.column(client, exported, "direction") == 3).all()
            assert np.allclose(await self.column(client, exported, "diameter"), 0.2)
        self.exports.append({"state": state, "export": exported, "expected_cells": expected_cells})
        return state["binding"]["loaded"]

    async def recover_wells(self, client, loaded, project):
        for old in self.exports:
            state = old["state"]
            well = next(
                o["ref"]
                for o in project["objects"]
                if o["ref"]["kind"] == "well" and o["name"] == state["plan"]["name"]
            )
            binding = {"loaded": loaded, "well": well, "receipt": state["binding"]["receipt"]}
            await self.call(client, "general_well_restore", binding)
            exported = await self.call(client, "general_well_export", binding)
            assert exported["count"] == old["export"]["count"]
            for name in (
                "cells",
                "factor",
                "kh",
                "diameter",
                "skin",
                "direction",
                "status",
                "measured_depth",
            ):
                before = await self.column(client, old["export"], name)
                after = await self.column(client, exported, name)
                assert np.allclose(before, after, rtol=1e-7, atol=1e-6), name

    async def run(self):
        nx, ny, nz = self.shape.values()
        async with self.client(True) as client:
            await self.call(
                client, "session_create", {"session_id": self.session_id, "name": "General wells"}
            )
            await self.call(client, "general_capabilities", {})
            model = await self.call(
                client,
                "geological_generate",
                {
                    "session_id": self.session_id,
                    "name": "Issue 57 well acceptance",
                    "shape": self.shape,
                    "extent_x": nx * 60,
                    "extent_y": ny * 50,
                    "top_depth": 2000,
                    "thickness": nz * 10,
                    "length_unit": self.unit,
                    "datum": "Original synthetic local datum, positive-down depth",
                    "faults": [{"intercept": nx * 30, "throw": 50}] if self.inactive else [],
                    "bands": [
                        {"bottom_fraction": 0.5, "porosity": 0.2, "permeability_md": 1000},
                        {"bottom_fraction": 0.7, "porosity": 0.15, "permeability_md": 10},
                        {"bottom_fraction": 1, "porosity": 0.25, "permeability_md": 500},
                    ],
                },
            )
            if self.inactive:
                arrays = {a["name"]: a["array"]["artifact"] for a in model["arrays"]}
                mask = np.ones((nz, ny, nx), dtype=np.int64)
                mask[2] = 0
                active = await self.array(client, mask, "1", "int64")
                model = await self.call(
                    client,
                    "geological_create",
                    {
                        "session_id": self.session_id,
                        "name": "Faulted grid with an inactive layer",
                        "shape": self.shape,
                        "coord": arrays["COORD"],
                        "zcorn": arrays["ZCORN"],
                        "actnum": active,
                        "fields": [
                            {"name": name, "array": ref}
                            for name, ref in arrays.items()
                            if name not in {"COORD", "ZCORN", "ACTNUM"}
                        ],
                        "length_unit": self.unit,
                        "datum": "Original synthetic local datum, positive-down depth",
                        "parent": model["model"],
                    },
                )
            assert model["active_cells"] == nx * ny * (nz - 1 if self.inactive else nz)
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
                for name, role, i, j in (
                    ("PROD_A", "producer", 0, 0),
                    ("PROD_B", "producer", nx - 1, ny - 1),
                    ("INJ_C", "injector", nx // 2, ny // 2),
                ):
                    x, y = (i + 0.5) * 60, (j + 0.5) * 50
                    loaded = await self.make_well(
                        client,
                        loaded,
                        name,
                        role,
                        [[x, y, 1900], [x, y, 2100 + nz * 10]],
                        [[0, 200 + nz * 10, 0.2, 0]],
                        [(i, j, k) for k in range(nz)],
                    )
                if nx * ny * nz < 1_000_000:
                    # A straight horizontal path crosses ten cells without a boundary ambiguity.
                    loaded = await self.make_well(
                        client,
                        loaded,
                        "HORIZONTAL",
                        "producer",
                        [
                            [15, 75, 2035 if self.inactive else 2025],
                            [nx * 60 - 15, 75, 2035 if self.inactive else 2025],
                        ],
                        [[0, nx * 60 - 30, 0.2, 0]],
                        [
                            (i, 1, 3 if self.inactive else 2)
                            for i in range(nx // 2 if self.inactive else nx)
                        ],
                    )
                    # Parallel cell planes give one analytically known slanted path per layer.
                    loaded = await self.make_well(
                        client,
                        loaded,
                        "SLANTED",
                        "producer",
                        [[15, 125, 2001], [45, 125, 2000 + nz * 10 - 1]],
                        [[0, float(np.hypot(30, nz * 10 - 2)), 0.2, 0]],
                        [(0, 2, k) for k in range(nz)],
                    )
                    loaded = await self.make_well(
                        client,
                        loaded,
                        "SEPARATED",
                        "producer",
                        [[90, 175, 2000], [90, 175, 2000 + nz * 10]],
                        [[1, 19, 0.2, 0], [31, 49, 0.2, 0]],
                        [(1, 3, k) for k in (0, 1, 3, 4)],
                    )
                if self.dense:
                    spacing = nz * 10 / 120
                    points = [[150, 225, float(z)] for z in np.linspace(2000, 2000 + nz * 10, 121)]
                    intervals = [[i * spacing + 0.1, i * spacing + 0.6, 0.2, 0] for i in range(120)]
                    loaded = await self.make_well(
                        client,
                        loaded,
                        "DENSE",
                        "producer",
                        points,
                        intervals,
                        [(2, 4, k) for k in range(nz)],
                    )
                await self.render(client, loaded)
                project = await self.call(
                    client, "project_inspect", {"session_id": self.session_id}
                )
                saved = await self.call(
                    client,
                    "project_save",
                    {"context": project["context"], "path": str(self.output / "wells.rsp")},
                )
                closed = await self.call(client, "project_close", {"context": saved["context"]})
                opened = await self.call(
                    client,
                    "project_open",
                    {"context": closed["context"], "path": str(self.output / "wells.rsp")},
                )
                loaded = await self.restore(client, loaded, opened)
                await self.recover_wells(client, loaded, opened)
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
            connection = await self.call(
                client,
                "application_launch",
                {"session_id": self.session_id, "executable": str(self.executable)},
            )
            try:
                opened = await self.call(
                    client,
                    "project_open",
                    {"context": connection["context"], "path": str(self.output / "wells.rsp")},
                )
                loaded = await self.restore(client, loaded, opened)
                await self.recover_wells(client, loaded, opened)
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
        (self.output / "summary.json").write_text(
            json.dumps(
                {
                    "shape": self.shape,
                    "units": self.unit,
                    "model": model,
                    "wells": self.exports,
                    "calls": self.calls,
                    "images": self.images,
                    "sampled_peak_rss_bytes": self.peak_rss,
                    "memory_sample_interval_seconds": 0.05,
                    "python": sys.executable,
                    "host": platform.platform(),
                    "physical_memory_bytes": psutil.virtual_memory().total,
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
                },
                indent=2,
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--million", action="store_true")
    parser.add_argument("--inactive", action="store_true")
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--unit", choices=["m", "ft"], default="m")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shape = (100, 200, 50) if args.million else (10, 10, 10)
    run = WellAcceptance(
        args.output,
        Path(
            "/private/tmp/resinsight-p01-build/application-build/ResInsight.app/Contents/MacOS/ResInsight"
        ),
        *shape,
        args.unit,
        args.inactive,
        args.dense,
    )
    asyncio.run(run.run())


if __name__ == "__main__":
    main()
