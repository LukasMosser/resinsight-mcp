"""Check acceptance failures without starting MCP, ResInsight, Docker, or Flow."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent
from numerical_checks import (
    check_definition,
    check_geometry,
    check_inspection,
    connection_table,
    definitions,
)
from public_client import Evidence, PublicClient, Record, TrialFailure


@pytest.fixture
def converted_inspection() -> tuple[Record, Record]:
    specification = {
        "grid": {
            "nx": 1,
            "ny": 1,
            "dx_ft": 1000,
            "dy_ft": 1000,
            "top_depth_ft": 8325,
            "layers": [
                {
                    "thickness_ft": 20,
                    "porosity": 0.3,
                    "permeability_x_md": 500,
                    "permeability_y_md": 500,
                    "permeability_z_md": 500,
                }
            ],
        }
    }
    # Values come from the recorded P09 trial-04 parent inspection.
    inspection = {
        "summary": {"dimensions": [1, 1, 1], "active_cells": 1, "unit_system": "FIELD"},
        "active_cells": [{"i": 0, "j": 0, "k": 0}],
        "cell_depths_ft": [8334.999999999998],
        "cell_volumes_ft3": [19999999.999996956],
        "properties": {
            "dx_ft": [1000.0],
            "dy_ft": [1000.0],
            "dz_ft": [20.0],
            "porosity": [0.3],
            "permx_millidarcy": [500.00000000000006],
            "permy_millidarcy": [500.00000000000006],
            "permz_millidarcy": [500.00000000000006],
        },
    }
    return specification, inspection


def test_inspection_accepts_recorded_conversion_rounding(
    tmp_path: Path, converted_inspection: tuple[Record, Record]
) -> None:
    check_inspection(Evidence(tmp_path), *converted_inspection)
    checks = json.loads((tmp_path / "checks.json").read_text())
    conversions = {item["name"]: item for item in checks if item["name"].endswith("-conversion")}
    assert len(conversions) == 9
    volume = conversions["inspection-cell_volumes_ft3-conversion"]
    assert volume["maximum_absolute_difference"] == abs(19999999.999996956 - 20000000)
    assert volume["maximum_relative_difference"] == volume["maximum_absolute_difference"] / 20000000
    assert volume["relative_tolerance"] == 1e-12
    assert volume["absolute_tolerance"] == 0


@pytest.mark.parametrize("name", ["cell_depths_ft", "cell_volumes_ft3", "permx_millidarcy"])
@pytest.mark.parametrize("change", ["material", "missing", "extra", "nan", "infinity"])
def test_inspection_rejects_changed_or_invalid_arrays(
    tmp_path: Path, converted_inspection: tuple[Record, Record], name: str, change: str
) -> None:
    specification, inspection = converted_inspection
    container = inspection["properties"] if name == "permx_millidarcy" else inspection
    original = container[name][0]
    container[name] = {
        "material": [original * 1.000001],
        "missing": [],
        "extra": [original, original],
        "nan": [float("nan")],
        "infinity": [float("inf")],
    }[change]
    with pytest.raises(TrialFailure, match=f"inspection-{name}"):
        check_inspection(Evidence(tmp_path), specification, inspection)
    checks = json.loads((tmp_path / "checks.json").read_text())
    assert checks[-1]["passed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"summary": {"dimensions": [2, 1, 1]}},
        {"summary": {"active_cells": 2}},
        {"summary": {"unit_system": "METRIC"}},
        {"active_cells": [{"i": 1, "j": 0, "k": 0}]},
    ],
)
def test_inspection_keeps_grid_identity_exact(
    tmp_path: Path, converted_inspection: tuple[Record, Record], change: Record
) -> None:
    specification, inspection = converted_inspection
    if "summary" in change:
        inspection["summary"].update(change["summary"])
    else:
        inspection.update(change)
    with pytest.raises(TrialFailure):
        check_inspection(Evidence(tmp_path), specification, inspection)


def test_well_targets_follow_the_inspected_completion_layer() -> None:
    specification = {
        "grid": {"dx_ft": 10, "dy_ft": 20},
        "wells": [{"name": "PROD", "cell": {"i": 1, "j": 0, "k": 1}, "diameter_ft": 0.5}],
    }
    inspection = {
        "summary": {"dimensions": [2, 1, 2]},
        "cell_depths_ft": [101, 101, 104, 104],
        "properties": {"dz_ft": [2, 2, 4, 4]},
    }
    result = definitions(specification, inspection, {"datum": "local"})["PROD"]
    assert all(target["x_ft"] == 15 and target["y_ft"] == 10 for target in result["targets"])
    assert result["targets"][0]["depth_ft"] == 0
    assert result["targets"][1]["depth_ft"] == 102
    assert result["targets"][-1]["depth_ft"] > 106
    interval = result["perforations"][0]
    assert 102 < interval["start_md_ft"] < interval["end_md_ft"] < 106


def test_corner_check_rejects_geometry_that_keeps_the_same_cell_count(tmp_path: Path) -> None:
    cell = {"i": 0, "j": 0, "k": 0}
    corners = [[x, y, z] for x in (0, 10) for y in (0, 20) for z in (100, 102)]
    corners[-1][-1] = 103
    values = {"active_cells": {"cells": [cell]}, "geometry": {"cell_corners": [corners]}}
    inspection = {
        "active_cells": [cell],
        "properties": {"dz_ft": [2]},
        "cell_depths_ft": [101],
    }
    with pytest.raises(TrialFailure, match="all-corners"):
        check_geometry(
            Evidence(tmp_path), "changed", values, {"grid": {"dx_ft": 10, "dy_ft": 20}}, inspection
        )
    checks = json.loads((tmp_path / "checks.json").read_text())
    assert checks[-1]["maximum_absolute_difference_ft"] == 1
    assert checks[-1]["passed"] is False


def test_completion_table_rejects_a_connection_in_another_cell(tmp_path: Path) -> None:
    exported = {"connections": [{"cell": {"i": 1, "j": 0, "k": 0}}]}
    with pytest.raises(TrialFailure, match="completion-cell"):
        connection_table(Evidence(tmp_path), "PROD", exported, {"i": 0, "j": 0, "k": 0})
    assert not (tmp_path / "PROD-connections.md").exists()


class ResponseClient:
    def __init__(self, payload: Record, *, is_error: bool = False) -> None:
        self.response = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload))],
            structuredContent=payload,
            isError=is_error,
        )

    async def call_tool(self, name: str, request: Record) -> CallToolResult:
        return self.response


def test_applied_edit_without_image_does_not_pass_visual_acceptance(tmp_path: Path) -> None:
    payload = {
        "outcome": {
            "status": "success",
            "value": {
                "edit": {"effect": "applied", "plot_address": "known-plot"},
                "observation": {
                    "outcome": {"status": "failure", "error": {"code": "render_failed"}}
                },
            },
        },
    }
    (tmp_path / "calls").mkdir()
    client = PublicClient(cast(ClientSession, ResponseClient(payload)), Evidence(tmp_path))
    with pytest.raises(TrialFailure, match="fresh-image"):
        asyncio.run(client.call("result_show_curve", {"query": "recorded"}, image=True))
    saved = json.loads(next((tmp_path / "calls").glob("*-response.json")).read_text())
    assert saved["structuredContent"] == payload
    assert saved["structuredContent"]["outcome"]["value"]["edit"]["effect"] == "applied"


def test_failure_acceptance_requires_the_expected_public_error(tmp_path: Path) -> None:
    payload = {"outcome": {"status": "failure", "error": {"code": "lost_connection"}}}
    (tmp_path / "calls").mkdir()
    client = PublicClient(
        cast(ClientSession, ResponseClient(payload, is_error=True)), Evidence(tmp_path)
    )
    with pytest.raises(TrialFailure, match="expected-failure"):
        asyncio.run(client.call("well_inspect", {}, failure="stale_object"))


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "field"},
        {"keyword": "WOPR"},
        {"well_name": "OTHER"},
        {"unit": "bar"},
        {"values": [float("nan")]},
        {"values": [0]},
    ],
)
def test_curve_check_rejects_wrong_source_or_pressure(tmp_path: Path, change: Record) -> None:
    from numerical_checks import check_curve

    result = {"report_series": {"reports": [{"index": 0}]}}
    request = {"scope": "well", "keyword": "WBHP", "well_name": "PROD"}
    curve = {"result": result, **request, "unit": "psi", "reports": [{"index": 0}], "values": [100]}
    check_curve(Evidence(tmp_path), "valid", curve, result, request)
    with pytest.raises(TrialFailure, match="curve-source"):
        check_curve(Evidence(tmp_path), "changed", curve | change, result, request)


def test_cleanup_continues_after_failed_poll_and_unknown_job(tmp_path: Path) -> None:
    from job_steps import Jobs

    jobs = {
        name: {"job_id": name, "model": {"session_id": "owned"}, "state": "running"}
        for name in ("unreachable", "uncertain", "remaining")
    }
    canceled = []

    class CleanupClient:
        evidence = Evidence(tmp_path)

        async def call(self, name: str, request: Record) -> Record:
            identity = request["job_id"]
            if identity == "unreachable":
                raise TrialFailure("lost connection")
            if name == "job_cancel":
                canceled.append(identity)
            state = (
                "unknown"
                if identity == "uncertain"
                else ("canceled" if identity in canceled else "running")
            )
            return jobs[identity] | {
                "state": state,
                "exit_code": 137 if state == "canceled" else None,
            }

    with pytest.raises(TrialFailure, match="unreachable, uncertain"):
        asyncio.run(Jobs(jobs).cleanup(cast(PublicClient, CleanupClient())))
    assert canceled == ["uncertain", "remaining"]
    saved = json.loads((tmp_path / "normal-job-cleanup.json").read_text())
    assert [item["reference"]["job_id"] for item in saved["unresolved"]] == [
        "unreachable",
        "uncertain",
    ]
    assert saved["jobs"][-1]["state"] == "canceled"


@pytest.mark.parametrize(
    ("change", "failure"),
    [
        ({"camera": {"parallel_scale": 6}}, "requested-camera"),
        ({"legend": {"minimum": 0.119528092443943, "maximum": 0.12026096880436}}, None),
        ({"legend": {"minimum": 0.1195}}, "requested-legend"),
        ({"legend": {"maximum": 0.1203}}, "requested-legend"),
        ({"property": {"unit": "psi"}}, "observed-scene"),
    ],
)
def test_capture_checks_requested_scene(
    tmp_path: Path, change: Record, failure: str | None
) -> None:
    from image_steps import Images
    from native_steps import Native

    camera = {
        "position": [0, 0, 10],
        "target": [0, 0, 0],
        "up": [0, 1, 0],
        "projection": "orthographic",
        "parallel_scale": 5,
    }
    loaded = {"result": {"model": {}, "result_id": "result", "grid_id": "grid"}, "case": {}}

    class NativeClient:
        wells: dict[str, Record] = {}

        async def project(self, api: PublicClient) -> Record:
            return {"objects": []}

    class CaptureClient:
        evidence = Evidence(tmp_path)

        async def call(
            self, name: str, request: Record, *, image: bool = False
        ) -> Record | list[Record]:
            if name == "view_list":
                return [
                    {
                        "loaded": loaded,
                        "camera": camera,
                        "vertical_exaggeration": 1,
                        "view": {},
                        "scene_version": 1,
                    }
                ]
            if name == "model_get":
                return {"coordinates": {}}
            context = dict(request["context"])
            for key, fields in change.items():
                context[key] = context[key] | fields
            return {"observation": {"outcome": {"value": {"context": context}}}}

    images = Images(cast(Native, NativeClient()))
    for side in ("baseline", "scenario"):
        capture = images.capture(
            cast(PublicClient, CaptureClient()),
            side,
            loaded,
            {"property": "SWAT", "unit": "fraction", "report_time": {}},
            {"minimum": 0.11952809244394302, "maximum": 0.12026096880435944},
        )
        if failure is not None:
            with pytest.raises(TrialFailure, match=failure):
                asyncio.run(capture)
        else:
            observation = asyncio.run(capture)
            assert observation["context"]["legend"] == change["legend"]
            assert (tmp_path / f"{side}-observation.json").is_file()


@pytest.mark.parametrize("side", ["baseline", "scenario"])
def test_curve_comparison_rejects_wrong_source_with_correct_delta(
    tmp_path: Path, side: str
) -> None:
    from numerical_checks import check_curve_comparison

    baseline = {"well_name": "PROD", "values": [100]}
    scenario = {"well_name": "PROD", "values": [110]}
    comparison = {"baseline": baseline, "scenario": scenario, "differences": [10]}
    check_curve_comparison(Evidence(tmp_path), "valid", comparison, baseline, scenario)
    comparison[side] = comparison[side] | {"well_name": "OTHER"}
    with pytest.raises(TrialFailure, match="signed-curve"):
        check_curve_comparison(Evidence(tmp_path), "changed", comparison, baseline, scenario)


@pytest.fixture
def rounded_definition() -> tuple[Record, Record]:
    # P13 trial-02 call 0156 returned these rounded definition values.
    expected: Record = {
        "name": "PROD",
        "coordinates": {
            "length_unit": "ft",
            "depth_direction": "positive_down",
            "datum": "P13 local FIELD depth datum",
        },
        "targets": [
            {"x_ft": 9500.0, "y_ft": 9500.0, "depth_ft": depth}
            for depth in (0.0, 8374.999999999998, 8425.999999999998)
        ],
        "perforations": [
            {
                "start_md_ft": 8375.999999999998,
                "end_md_ft": 8423.999999999998,
                "diameter_ft": 0.5,
                "skin": 0.0,
            }
        ],
    }
    actual = deepcopy(expected)
    actual["targets"][1]["depth_ft"] = 8375.0
    actual["targets"][2]["depth_ft"] = 8426.0
    actual["perforations"][0].update(start_md_ft=8376.0, end_md_ft=8424.0)
    return actual, expected


def test_definition_accepts_recorded_project_rounding(
    tmp_path: Path, rounded_definition: tuple[Record, Record]
) -> None:
    check_definition(Evidence(tmp_path), "PROD", *rounded_definition)
    checks = json.loads((tmp_path / "checks.json").read_text())
    conversions = {item["name"]: item for item in checks if item["name"].endswith("-conversion")}
    assert len(conversions) == 7
    depth = conversions["PROD-targets-depth_ft-conversion"]
    assert depth["maximum_absolute_difference"] == abs(8375.0 - 8374.999999999998)
    assert depth["relative_tolerance"] == 1e-12
    assert depth["absolute_tolerance"] == 0


@pytest.mark.parametrize(
    "group,field",
    [
        ("targets", "x_ft"),
        ("targets", "y_ft"),
        ("targets", "depth_ft"),
        ("perforations", "start_md_ft"),
        ("perforations", "end_md_ft"),
        ("perforations", "diameter_ft"),
        ("perforations", "skin"),
    ],
)
@pytest.mark.parametrize("change", ["material", "nan", "infinity", "boolean"])
def test_definition_rejects_changed_numeric_fields(
    tmp_path: Path, rounded_definition: tuple[Record, Record], group: str, field: str, change: str
) -> None:
    actual, expected = rounded_definition
    value = actual[group][0][field]
    actual[group][0][field] = {
        "material": value + 0.001,
        "nan": float("nan"),
        "infinity": float("inf"),
        "boolean": True,
    }[change]
    with pytest.raises(TrialFailure, match="PROD"):
        check_definition(Evidence(tmp_path), "PROD", actual, expected)


@pytest.mark.parametrize(
    "change",
    [
        "name",
        "unit",
        "datum",
        "direction",
        "top_shape",
        "target_count",
        "perforation_count",
        "target_field",
        "perforation_field",
        "missing_field",
    ],
)
def test_definition_keeps_identity_and_shape_exact(
    tmp_path: Path, rounded_definition: tuple[Record, Record], change: str
) -> None:
    actual, expected = rounded_definition
    if change == "name":
        actual["name"] = "OTHER"
    elif change in {"unit", "datum", "direction"}:
        field = {"unit": "length_unit", "datum": "datum", "direction": "depth_direction"}[change]
        actual["coordinates"][field] = "different"
    elif change == "top_shape":
        actual["extra"] = 0
    elif change == "target_count":
        actual["targets"].pop()
    elif change == "perforation_count":
        actual["perforations"].append(deepcopy(actual["perforations"][0]))
    elif change == "missing_field":
        del actual["targets"][0]["x_ft"]
    else:
        group = "targets" if change == "target_field" else "perforations"
        actual[group][0]["extra"] = 0
    with pytest.raises(TrialFailure, match="PROD"):
        check_definition(Evidence(tmp_path), "PROD", actual, expected)


@pytest.fixture
def rounded_connections() -> tuple[list[Record], list[Record]]:
    # P13 trial-03 regenerated these PROD completion interval endpoints.
    expected: list[Record] = [
        {
            "cell": {"i": 9, "j": 9, "k": 2},
            "status": "OPEN",
            "direction": "Z",
            "compdat_factor_field": 10.184872697201985,
            "permeability_length_md_ft": 9600.0,
            "diameter_ft": 0.5,
            "skin": 0.0,
            "start_md_ft": 8375.999999999998,
            "end_md_ft": 8423.999999999998,
        }
    ]
    actual = deepcopy(expected)
    actual[0].update(start_md_ft=8376.0, end_md_ft=8424.0)
    return actual, expected


def test_fresh_connections_accept_only_recorded_endpoint_rounding(
    tmp_path: Path, rounded_connections: tuple[list[Record], list[Record]]
) -> None:
    from numerical_checks import check_fresh_connections

    actual, expected = rounded_connections
    evidence = Evidence(tmp_path)
    check_fresh_connections(evidence, "PROD", actual, expected)
    for record in (actual[0], expected[0]):
        record.update(
            cell={"i": 0, "j": 0, "k": 0},
            compdat_factor_field=9.54831815362686,
            permeability_length_md_ft=9000.0,
        )
    actual[0].update(start_md_ft=8326.0, end_md_ft=8344.0)
    expected[0].update(start_md_ft=8325.999999999998, end_md_ft=8343.999999999998)
    check_fresh_connections(evidence, "INJ", actual, expected)
    checks = json.loads((tmp_path / "checks.json").read_text())
    conversions = [item for item in checks if item["name"].endswith("-conversion")]
    assert len(conversions) == 4
    assert all(
        item["maximum_absolute_difference"] == 1.8189894035458565e-12 for item in conversions
    )
    assert all(
        item["relative_tolerance"] == 1e-12 and item["absolute_tolerance"] == 0
        for item in conversions
    )


@pytest.mark.parametrize(
    "field",
    [
        "start_md_ft",
        "end_md_ft",
        "compdat_factor_field",
        "permeability_length_md_ft",
        "diameter_ft",
        "skin",
    ],
)
@pytest.mark.parametrize("change", ["material", "nan", "infinity"])
def test_fresh_connections_reject_numeric_changes(
    tmp_path: Path, rounded_connections: tuple[list[Record], list[Record]], field: str, change: str
) -> None:
    from numerical_checks import check_fresh_connections

    actual, expected = rounded_connections
    actual[0][field] = {
        "material": actual[0][field] + 0.001,
        "nan": float("nan"),
        "infinity": float("inf"),
    }[change]
    with pytest.raises(TrialFailure, match="PROD"):
        check_fresh_connections(Evidence(tmp_path), "PROD", actual, expected)


@pytest.mark.parametrize(
    "field",
    [
        "compdat_factor_field",
        "permeability_length_md_ft",
        "diameter_ft",
        "skin",
    ],
)
def test_fresh_connections_reject_even_tiny_non_endpoint_changes(
    tmp_path: Path, rounded_connections: tuple[list[Record], list[Record]], field: str
) -> None:
    from numerical_checks import check_fresh_connections

    actual, expected = rounded_connections
    actual[0][field] += 1e-12
    with pytest.raises(TrialFailure, match="connection-fields"):
        check_fresh_connections(Evidence(tmp_path), "PROD", actual, expected)


@pytest.mark.parametrize(
    "change", ["cell", "status", "direction", "extra", "missing", "count", "order"]
)
def test_fresh_connections_keep_identity_shape_and_order_exact(
    tmp_path: Path, rounded_connections: tuple[list[Record], list[Record]], change: str
) -> None:
    from numerical_checks import check_fresh_connections

    actual, expected = rounded_connections
    if change == "cell":
        actual[0]["cell"]["i"] = 8
    elif change in {"status", "direction"}:
        actual[0][change] = "different"
    elif change == "extra":
        actual[0]["extra"] = 0
    elif change == "missing":
        del actual[0]["start_md_ft"]
    elif change == "count":
        actual.append(deepcopy(actual[0]))
    else:
        second = deepcopy(expected[0])
        second["cell"]["i"] = 8
        expected.append(second)
        actual = list(reversed(deepcopy(expected)))
    with pytest.raises(TrialFailure, match="PROD"):
        check_fresh_connections(Evidence(tmp_path), "PROD", actual, expected)
