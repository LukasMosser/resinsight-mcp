"""Capture public result views with observed cameras and full source identity."""

import json
from dataclasses import dataclass
from math import isclose

from native_steps import Native
from numerical_checks import check_curve_comparison, reference
from public_client import PublicClient, Record, TrialFailure, write

from resinsight_mcp.contracts.observations import Camera
from resinsight_mcp.resinsight.views._camera import camera_matches


@dataclass
class Images:
    native: Native
    camera: Record | None = None
    vertical_exaggeration: float | None = None

    async def rebind(self, api: PublicClient, results: list[Record]) -> list[Record]:
        state = await self.native.project(api)
        loaded = await api.call(
            "result_rebind",
            {"context": state["context"], "result_ids": [item["result_id"] for item in results]},
        )
        api.evidence.check(
            "result-bindings-retain-identities", [item["result"] for item in loaded] == results
        )
        return loaded

    async def load(self, api: PublicClient, result: Record, job: Record) -> Record:
        state = await self.native.project(api)
        loaded = await api.call(
            "result_load", {"context": state["context"], "result": result, "job": job}
        )
        api.evidence.check("native-result-loaded", loaded["result"] == result)
        return loaded

    async def capture(
        self, api: PublicClient, label: str, loaded: Record, values: Record, legend: Record
    ) -> Record:
        states = await api.call("view_list", loaded)
        if len(states) != 1:
            raise TrialFailure("The loaded result must expose exactly one associated view.")
        state = states[0]
        api.evidence.check(f"{label}-view-owner", state["loaded"] == loaded)
        if self.camera is None:
            self.camera = state["camera"]
            self.vertical_exaggeration = state["vertical_exaggeration"]
        revision = await api.call("model_get", loaded["result"]["model"])
        project = await self.native.project(api)
        selected = [
            item["ref"]
            for item in project["objects"]
            if item["ref"]["kind"] == "well" and item["name"] in self.native.wells
        ]
        api.evidence.check(
            f"{label}-selected-well-identities", len(selected) == len(self.native.wells)
        )
        context = {
            "model": loaded["result"]["model"],
            "result_id": loaded["result"]["result_id"],
            "grid_id": loaded["result"]["grid_id"],
            "case": loaded["case"],
            "view": state["view"],
            "scene_version": state["scene_version"],
            "property": {"name": values["property"], "unit": values["unit"]},
            "report_time": values["report_time"],
            "coordinates": revision["coordinates"],
            "camera": self.camera,
            "vertical_exaggeration": self.vertical_exaggeration,
            "legend": legend,
            "filters": [],
            "selected_wells": selected,
        }
        edited = await api.call(
            "view_apply", {"context": context, "width": 1200, "height": 800}, image=True
        )
        observation = edited["observation"]["outcome"]["value"]
        actual = observation["context"]
        api.evidence.check(
            f"{label}-observed-scene",
            all(
                actual[key] == context[key]
                for key in (
                    "model",
                    "result_id",
                    "grid_id",
                    "case",
                    "view",
                    "property",
                    "report_time",
                    "coordinates",
                    "filters",
                    "selected_wells",
                    "vertical_exaggeration",
                )
            ),
        )
        api.evidence.check(
            f"{label}-requested-legend",
            all(
                isclose(context["legend"][key], actual["legend"][key], rel_tol=1e-14)
                for key in ("minimum", "maximum")
            ),
        )
        api.evidence.check(
            f"{label}-requested-camera",
            camera_matches(
                Camera.model_validate_json(json.dumps(self.camera)),
                Camera.model_validate_json(json.dumps(actual["camera"])),
            ),
        )
        write(api.evidence.output / f"{label}-observation.json", observation)
        return observation

    async def baseline(self, api: PublicClient, loaded: Record, numerical: Record) -> None:
        for name in ("PRESSURE", "SWAT"):
            values = numerical["cells"][name][-1]
            low, high = min(values["values"]), max(values["values"])
            if high == low:
                high += max(1, abs(low) * 0.01)
            await self.capture(
                api,
                f"baseline-initial-{name.lower()}",
                loaded,
                values,
                {"minimum": low, "maximum": high},
            )

    async def compare(
        self, api: PublicClient, results: list[Record], numerical: list[Record], label: str
    ) -> None:
        loaded = await self.rebind(api, results)
        changed = False
        for name in ("PRESSURE", "SWAT"):
            for index, report in enumerate(results[0]["report_series"]["reports"]):
                requests = [
                    {
                        "result": reference(result),
                        "property": name,
                        "report_time": result["report_series"]["reports"][index],
                    }
                    for result in results
                ]
                comparison = await api.call(
                    "result_compare_cells", {"baseline": requests[0], "scenario": requests[1]}
                )
                expected = [
                    b - a
                    for a, b in zip(
                        numerical[0]["cells"][name][index]["values"],
                        numerical[1]["cells"][name][index]["values"],
                        strict=True,
                    )
                ]
                changed |= any(value != 0 for value in expected)
                api.evidence.check(
                    f"{label}-{name}-{report['index']}-signed-comparison",
                    comparison["differences"] == expected
                    and comparison["baseline"] == numerical[0]["cells"][name][index]
                    and comparison["scenario"] == numerical[1]["cells"][name][index],
                )
                observations = []
                for side, binding in zip(("baseline", "scenario"), loaded, strict=True):
                    observations.append(
                        await self.capture(
                            api,
                            f"{label}-{side}-{name.lower()}-{index}",
                            binding,
                            comparison[side],
                            comparison["legend"],
                        )
                    )
                api.evidence.check(
                    f"{label}-{name}-{index}-common-scene",
                    all(
                        observations[0]["context"][key] == observations[1]["context"][key]
                        for key in ("camera", "legend", "vertical_exaggeration", "filters")
                    ),
                )
        api.evidence.check(f"{label}-scenario-changes-cell-values", changed)
        for well in self.native.wells:
            requests = [
                {"result": reference(result), "scope": "well", "keyword": "WBHP", "well_name": well}
                for result in results
            ]
            comparison = await api.call(
                "result_compare_curves", {"baseline": requests[0], "scenario": requests[1]}
            )
            check_curve_comparison(
                api.evidence,
                f"{label}-{well}",
                comparison,
                numerical[0]["curves"][well],
                numerical[1]["curves"][well],
            )
        state = await self.native.project(api)
        edited = await api.call(
            "result_show_curve",
            {
                "context": state["context"],
                "query": {
                    "result": reference(results[1]),
                    "scope": "well",
                    "keyword": "WBHP",
                    "well_name": "PROD",
                },
                "width": 1200,
                "height": 800,
            },
            image=True,
        )
        api.evidence.check(
            f"{label}-summary-applied-receipt",
            edited["edit"]["effect"] == "applied"
            and edited["edit"]["curve"] == numerical[1]["curves"]["PROD"],
        )
        await self.rebind(api, results)
