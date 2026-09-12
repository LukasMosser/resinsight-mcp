"""Verify arbitrary array inputs with nonuniform spacing and inclined pillars."""

import argparse
import asyncio
from pathlib import Path

import numpy as np
from acceptance import Acceptance


class ExplicitAcceptance(Acceptance):
    async def generate(self, client):
        nx, ny, nz = self.shape.values()
        x = 6000 * np.linspace(0, 1, nx + 1) ** 1.3
        y = 10000 * np.linspace(0, 1, ny + 1)
        px, py = np.meshgrid(x, y)
        coord = np.empty((ny + 1, nx + 1, 2, 3))
        coord[:, :, 0] = np.stack((px, py, np.full_like(px, 1500)), axis=-1)
        coord[:, :, 1] = np.stack((px + 300, py + 200, np.full_like(px, 3500)), axis=-1)
        xx, yy = np.meshgrid(
            np.stack((x[:-1], x[1:]), axis=1).ravel(), np.stack((y[:-1], y[1:]), axis=1).ravel()
        )
        top = 2100 + 200 * np.sin(2 * np.pi * xx / 7000) * np.cos(2 * np.pi * yy / 11000)
        top[:, nx:] += 150
        top[:, 2 * (2 * nx // 3) :] -= 95
        levels = np.linspace(0, 1, nz + 1)
        levels = np.stack((levels[:-1], levels[1:]), axis=1).ravel()
        zcorn = top[None] + levels[:, None, None] * 450
        u, v = np.meshgrid((np.arange(nx) + 0.5) / nx, (np.arange(ny) + 0.5) / ny)
        active = np.broadcast_to(
            (((u - 0.5) / 0.5) ** 2 + ((v - 0.5) / 0.5) ** 2 < 1), (nz, ny, nx)
        ).astype(np.int64)
        layer = np.arange(nz)[:, None, None] / nz
        permeability = np.broadcast_to(
            np.where(layer < 0.5, 1000.0, np.where(layer < 0.7, 10.0, 500.0)), active.shape
        ).copy()
        permeability *= 1 + 4 * np.exp(-(((v - 0.5 - 0.2 * np.sin(2 * np.pi * u)) / 0.07) ** 2))
        porosity = np.broadcast_to(np.where(layer < 0.5, 0.22, 0.12), active.shape).copy()
        arrays = {
            "COORD": coord.ravel(),
            "ZCORN": zcorn.ravel(),
            "ACTNUM": active.ravel(),
            "PORO": porosity.ravel(),
            "PERMX": permeability.ravel(),
        }
        refs = {}
        for name, array in arrays.items():
            unit = "m" if name in {"COORD", "ZCORN"} else "mD" if name == "PERMX" else "1"
            parts = []
            for offset in range(0, len(array), 65536):
                part = await self.call(
                    client,
                    "array_upload",
                    {
                        "session_id": self.session_id,
                        "dtype": "int64" if name == "ACTNUM" else "float64",
                        "unit": unit,
                        "values": array[offset : offset + 65536].tolist(),
                    },
                )
                parts.append(part["artifact"])
            joined = await self.call(
                client, "array_join", {"session_id": self.session_id, "parts": parts}
            )
            refs[name] = joined["artifact"]
        return await self.call(
            client,
            "geological_create",
            {
                "session_id": self.session_id,
                "name": "Explicit nonuniform inclined-pillar model",
                "shape": self.shape,
                "coord": refs["COORD"],
                "zcorn": refs["ZCORN"],
                "actnum": refs["ACTNUM"],
                "fields": [{"name": name, "array": refs[name]} for name in ("PORO", "PERMX")],
                "length_unit": "m",
                "datum": "Original array-defined local model",
            },
        )

    async def verify_faults(self, client, loaded):
        nx, ny, nz = self.shape.values()
        left = (ny // 2) * nx + nx // 2 - 1
        indices = [left, left + 1, (nz - 1) * nx * ny + left + 1]
        result = await self.call(
            client, "geological_verify", {"loaded": loaded, "global_indices": indices}
        )
        first, second, last = result["cells"]
        assert abs(second["corners"][0][2] - first["corners"][1][2] - 150) < 0.001
        # Inclined pillars move cell bottoms horizontally with increasing depth.
        assert second["corners"][4][0] > second["corners"][0][0]
        assert second["corners"][4][1] > second["corners"][0][1]
        assert last["corners"][4][2] > second["corners"][0][2]
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resinsight", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(ExplicitAcceptance(args.output.resolve(), args.resinsight, 40, 60, 15).run())


if __name__ == "__main__":
    main()
