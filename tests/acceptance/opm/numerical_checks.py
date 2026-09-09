"""Check complete public numerical responses against their explicit source records."""

import math
from itertools import product

from public_client import Evidence, PublicClient, Record, write


def reference(result: Record) -> Record:
    return {"session_id": result["model"]["session_id"], "result_id": result["result_id"]}


def definitions(
    specification: Record, inspection: Record, coordinates: Record
) -> dict[str, Record]:
    grid = specification["grid"]
    nx, ny, _ = inspection["summary"]["dimensions"]
    result = {}
    for well in specification["wells"]:
        cell = well["cell"]
        index = cell["k"] * nx * ny + cell["j"] * nx + cell["i"]
        center = inspection["cell_depths_ft"][index]
        thickness = inspection["properties"]["dz_ft"][index]
        top, bottom = center - thickness / 2, center + thickness / 2
        margin = min(1.0, thickness / 10)
        x, y = (cell["i"] + 0.5) * grid["dx_ft"], (cell["j"] + 0.5) * grid["dy_ft"]
        result[well["name"]] = {
            "name": well["name"],
            "coordinates": coordinates,
            "targets": [
                {"x_ft": x, "y_ft": y, "depth_ft": depth} for depth in (0, top, bottom + margin)
            ],
            "perforations": [
                {
                    "start_md_ft": top + margin,
                    "end_md_ft": bottom - margin,
                    "diameter_ft": well["diameter_ft"],
                    "skin": 0,
                }
            ],
        }
    return result


def check_converted_values(
    evidence: Evidence, label: str, actual: list[float], expected: list[float]
) -> None:
    evidence.check(
        f"{label}-finite-count",
        len(actual) == len(expected) and all(math.isfinite(value) for value in actual),
        actual_count=len(actual),
        expected_count=len(expected),
    )
    absolute = [abs(a - b) for a, b in zip(actual, expected, strict=True)]
    relative = [
        delta / max(abs(a), abs(b)) if a or b else 0.0
        for a, b, delta in zip(actual, expected, absolute, strict=True)
    ]
    evidence.check(
        f"{label}-conversion",
        all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(actual, expected, strict=True)),
        maximum_absolute_difference=max(absolute, default=0.0),
        maximum_relative_difference=max(relative, default=0.0),
        relative_tolerance=1e-12,
        absolute_tolerance=0.0,
    )


def check_definition(evidence: Evidence, label: str, actual: Record, expected: Record) -> None:
    fields = {"name", "coordinates", "targets", "perforations"}
    evidence.check(
        f"{label}-identity",
        set(actual) == fields
        and set(expected) == fields
        and actual["name"] == expected["name"]
        and actual["coordinates"] == expected["coordinates"],
    )
    for group, names in (
        ("targets", ("x_ft", "y_ft", "depth_ft")),
        ("perforations", ("start_md_ft", "end_md_ft", "diameter_ft", "skin")),
    ):
        observed, saved = actual[group], expected[group]
        evidence.check(
            f"{label}-{group}-shape",
            isinstance(observed, list)
            and isinstance(saved, list)
            and len(observed) == len(saved)
            and all(
                isinstance(item, dict)
                and set(item) == set(names)
                and all(
                    type(item[name]) in (int, float) and math.isfinite(item[name]) for name in names
                )
                for item in [*observed, *saved]
            ),
        )
        for name in names:
            check_converted_values(
                evidence,
                f"{label}-{group}-{name}",
                [item[name] for item in observed],
                [item[name] for item in saved],
            )


def check_inspection(evidence: Evidence, specification: Record, inspection: Record) -> None:
    grid = specification["grid"]
    nx, ny = grid["nx"], grid["ny"]
    layers = grid["layers"]
    evidence.check(
        "layered-grid-dimensions", inspection["summary"]["dimensions"] == [nx, ny, len(layers)]
    )
    expected_cells = [
        {"i": i, "j": j, "k": k} for k in range(len(layers)) for j in range(ny) for i in range(nx)
    ]
    evidence.check(
        "full-active-cell-order",
        inspection["active_cells"] == expected_cells
        and inspection["summary"]["active_cells"] == len(expected_cells),
    )
    evidence.check("field-units", inspection["summary"]["unit_system"] == "FIELD")
    expected: dict[str, list[float]] = {}
    top = grid["top_depth_ft"]
    for layer in layers:
        for name, value in (
            ("cell_depths_ft", top + layer["thickness_ft"] / 2),
            ("cell_volumes_ft3", grid["dx_ft"] * grid["dy_ft"] * layer["thickness_ft"]),
            ("dx_ft", grid["dx_ft"]),
            ("dy_ft", grid["dy_ft"]),
            ("dz_ft", layer["thickness_ft"]),
            ("porosity", layer["porosity"]),
            ("permx_millidarcy", layer["permeability_x_md"]),
            ("permy_millidarcy", layer["permeability_y_md"]),
            ("permz_millidarcy", layer["permeability_z_md"]),
        ):
            expected.setdefault(name, []).extend([value] * (nx * ny))
        top += layer["thickness_ft"]
    observed = {
        "cell_depths_ft": inspection["cell_depths_ft"],
        "cell_volumes_ft3": inspection["cell_volumes_ft3"],
        **inspection["properties"],
    }
    for name, values in expected.items():
        check_converted_values(evidence, f"inspection-{name}", observed[name], values)


def check_geometry(
    evidence: Evidence, label: str, values: Record, specification: Record, inspection: Record
) -> None:
    corners = values["geometry"]["cell_corners"]
    cells = values["active_cells"]["cells"]
    evidence.check(
        f"{label}-cell-layout", cells == inspection["active_cells"] and len(corners) == len(cells)
    )
    grid = specification["grid"]
    maximum = 0.0
    for index, (cell, actual) in enumerate(zip(cells, corners, strict=True)):
        thickness = inspection["properties"]["dz_ft"][index]
        center = inspection["cell_depths_ft"][index]
        expected = sorted(
            product(
                (cell["i"] * grid["dx_ft"], (cell["i"] + 1) * grid["dx_ft"]),
                (cell["j"] * grid["dy_ft"], (cell["j"] + 1) * grid["dy_ft"]),
                (center - thickness / 2, center + thickness / 2),
            )
        )
        for point, wanted in zip(sorted(actual), expected, strict=True):
            maximum = max(maximum, *(abs(a - b) for a, b in zip(point, wanted, strict=True)))
    evidence.check(
        f"{label}-all-corners",
        maximum <= 0.001,
        maximum_absolute_difference_ft=maximum,
        tolerance_ft=0.001,
    )


async def queries(
    api: PublicClient, label: str, result: Record, specification: Record, inspection: Record
) -> Record:
    reports = result["report_series"]["reports"]
    cells: dict[str, list[Record]] = {name: [] for name in ("PRESSURE", "SWAT", "SGAS")}
    for name in cells:
        for report in reports:
            values = await api.call(
                "result_cell_property",
                {"result": reference(result), "property": name, "report_time": report},
            )
            api.evidence.check(
                f"{label}-{name}-{report['index']}-source",
                values["result"] == result
                and values["property"] == name
                and values["report_time"] == report
                and values["unit"] == ("psi" if name == "PRESSURE" else "1")
                and len(values["values"]) == inspection["summary"]["active_cells"]
                and all(math.isfinite(v) for v in values["values"]),
            )
            cells[name].append(values)
    check_geometry(api.evidence, label, cells["PRESSURE"][0], specification, inspection)
    tolerance = 2.384185791015625e-7
    for pressure, water, gas in zip(*cells.values(), strict=True):
        api.evidence.check(
            f"{label}-physical-bounds-{pressure['report_time']['index']}",
            all(
                p > 0
                and -tolerance <= w <= 1 + tolerance
                and -tolerance <= g <= 1 + tolerance
                and w + g <= 1 + tolerance
                for p, w, g in zip(pressure["values"], water["values"], gas["values"], strict=True)
            ),
        )
    curves = {}
    requests = {
        well["name"]: {"scope": "well", "keyword": "WBHP", "well_name": well["name"]}
        for well in specification["wells"]
    }
    requests["FOPR"] = {"scope": "field", "keyword": "FOPR"}
    for name, request in requests.items():
        curve = await api.call("result_curve", {"result": reference(result), **request})
        check_curve(api.evidence, f"{label}-{name}", curve, result, request)
        curves[name] = curve
    record = {"cells": cells, "curves": curves}
    write(api.evidence.output / f"{label}-numerical.json", record)
    return record


def check_curve(
    evidence: Evidence, label: str, curve: Record, result: Record, request: Record
) -> None:
    reports = result["report_series"]["reports"]
    evidence.check(
        f"{label}-curve-source",
        curve["result"] == result
        and all(curve.get(key) == request.get(key) for key in ("scope", "keyword", "well_name"))
        and curve["unit"] == ("psi" if request["keyword"] == "WBHP" else "stb/day")
        and curve["reports"] == reports
        and len(curve["values"]) == len(reports)
        and all(math.isfinite(value) for value in curve["values"])
        and (request["keyword"] != "WBHP" or all(value > 0 for value in curve["values"])),
    )


def check_curve_comparison(
    evidence: Evidence, label: str, comparison: Record, baseline: Record, scenario: Record
) -> None:
    expected = [b - a for a, b in zip(baseline["values"], scenario["values"], strict=True)]
    evidence.check(
        f"{label}-signed-curve",
        comparison["differences"] == expected
        and comparison["baseline"] == baseline
        and comparison["scenario"] == scenario,
    )


def check_fresh_connections(
    evidence: Evidence, label: str, actual: list[Record], expected: list[Record]
) -> None:
    endpoints = ("start_md_ft", "end_md_ft")
    numeric = (
        *endpoints,
        "compdat_factor_field",
        "permeability_length_md_ft",
        "diameter_ft",
        "skin",
    )
    fields = {"cell", "status", "direction", *numeric}
    evidence.check(
        f"{label}-connection-shape",
        len(actual) == len(expected)
        and all(
            isinstance(item, dict)
            and set(item) == fields
            and all(
                type(item[name]) in (int, float) and math.isfinite(item[name]) for name in numeric
            )
            for item in [*actual, *expected]
        ),
    )
    evidence.check(
        f"{label}-connection-fields",
        all(
            {key: value for key, value in observed.items() if key not in endpoints}
            == {key: value for key, value in saved.items() if key not in endpoints}
            for observed, saved in zip(actual, expected, strict=True)
        ),
    )
    for name in endpoints:
        check_converted_values(
            evidence,
            f"{label}-{name}",
            [item[name] for item in actual],
            [item[name] for item in expected],
        )


def connection_table(
    evidence: Evidence, label: str, exported: Record, expected_cell: Record
) -> None:
    connections = exported["connections"]
    evidence.check(
        f"{label}-completion-cell",
        len(connections) == 1 and connections[0]["cell"] == expected_cell,
    )
    rows = [
        "# Native completion records",
        "",
        "Indices start at zero. Factors use the native FIELD COMPDAT convention.",
        "",
        "| Well | I | J | K | Start MD (ft) | End MD (ft) | Factor | kh (mD ft) | Diameter (ft) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in connections:
        rows.append(
            "| "
            + " | ".join(
                str(value)
                for value in (
                    exported["modeled_well"]["definition"]["name"],
                    *item["cell"].values(),
                    item["start_md_ft"],
                    item["end_md_ft"],
                    item["compdat_factor_field"],
                    item["permeability_length_md_ft"],
                    item["diameter_ft"],
                )
            )
            + " |"
        )
    (evidence.output / f"{label}-connections.md").write_text("\n".join(rows) + "\n")
