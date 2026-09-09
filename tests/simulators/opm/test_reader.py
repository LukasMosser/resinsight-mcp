"""Verify acceptance and failures using preserved Flow outputs and official OPM readers."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from resinsight_mcp.contracts.identifiers import JobId
from resinsight_mcp.simulators.opm._reader import read
from resinsight_mcp.simulators.opm.records import FlowRunRecord

from ._support import rewrite


def test_reader_preserves_reference_values_and_geometry(run_record: FlowRunRecord) -> None:
    log = (run_record.directory / "outputs/flow.log").read_text() + "\nWarning: example"
    dataset, assessment = read(run_record, JobId.new(), log)
    reference = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "docs/development/evidence/p08/numerical-values.json"
        ).read_text()
    )["p07-1"]
    assert [report.index for report in dataset.report_series.reports] == [1, 2]
    assert dataset.active_cells.cells == run_record.inspection.active_cells
    assert dataset.geometry.cell_corners[0][0] == (0.0, 0.0, 8325.0)
    assert dataset.geometry.cell_corners[0][7] == (1000.0, 1000.0, 8345.0)
    assert assessment.warnings == ("Warning: example",)
    assert assessment.policy == "opm-field-validity-v1"
    assert assessment.observed_program_version == "flow 2026.04"
    assert not assessment.numerical_reference_assessed
    assert len(assessment.initial_arrays) > 20
    assert len(assessment.summary_arrays) >= len(dataset.curves)
    for item in dataset.cell_properties:
        if item.name != "PRESSURE":
            continue
        for report, row in zip(dataset.report_series.reports, item.values, strict=True):
            assert list(row) == reference["quantities"][f"{item.name}:{report.index}"]["values"]
    for curve in dataset.curves:
        key = curve.keyword if curve.well_name is None else f"{curve.keyword}:{curve.well_name}"
        assert list(curve.values) == reference["quantities"][key]["values"]
    gas = next(item for item in dataset.cell_properties if item.name == "SGAS")
    assert min(gas.values[0]) < 0


@pytest.mark.parametrize(
    ("extension", "keyword", "replacement", "message"),
    [
        ("INIT", "PORO", 0.4, "PORO differs"),
        ("INIT", "PORV", 1.0, "PORV differs"),
        ("UNRST", "SGAS", -0.001, "saturation range"),
        ("UNRST", "SGAS", 0.99, "Combined phase saturations"),
        ("UNRST", "PRESSURE", 0.0, "Absolute cell pressures"),
    ],
)
def test_reader_rejects_wrong_values(
    run_record: FlowRunRecord, extension: str, keyword: str, replacement: float, message: str
) -> None:
    def change(name: str, values: Any) -> Any:
        if name == keyword:
            values = np.full_like(values, replacement)
        return values

    rewrite(run_record.directory / "outputs" / f"SPE1.{extension}", change)
    with pytest.raises(ValueError, match=message):
        read(run_record, JobId.new(), "This is flow 2026.04")


def test_reader_rejects_missing_final_report(run_record: FlowRunRecord) -> None:
    rewrite(
        run_record.directory / "outputs/SPE1.UNRST",
        lambda name, values: None if name == "SEQNUM" and values[0] == 2 else values,
    )
    with pytest.raises(ValueError, match="complete submitted schedule"):
        read(run_record, JobId.new(), "This is flow 2026.04")


@pytest.mark.parametrize(
    ("keyword", "old", "new", "message"),
    [
        ("WGNAMES", "INJ", "OTHER", "well identities"),
        ("UNITS", "STB/DAY", "SM3/DAY", "STB/DAY"),
    ],
)
def test_reader_rejects_summary_identity(
    run_record: FlowRunRecord, keyword: str, old: str, new: str, message: str
) -> None:
    rewrite(
        run_record.directory / "outputs/SPE1.SMSPEC",
        lambda name, values: (
            [new if value == old else value for value in values] if name == keyword else values
        ),
    )
    with pytest.raises(ValueError, match=message):
        read(run_record, JobId.new(), "This is flow 2026.04")


@pytest.mark.parametrize("version", ["flow another-version", "flow 2026.04-extra"])
def test_reader_rejects_wrong_program_version(run_record: FlowRunRecord, version: str) -> None:
    with pytest.raises(ValueError, match="observed Flow version"):
        read(run_record, JobId.new(), f"This is {version}")


def test_reader_rejects_nonpositive_absolute_well_pressure(run_record: FlowRunRecord) -> None:
    from opm.io.ecl import EclFile

    specification = EclFile(str(run_record.directory / "outputs/SPE1.SMSPEC"))
    pressure_index = specification["KEYWORDS"].index("WBHP")

    def zero_pressure(name: str, values: Any) -> Any:
        if name == "PARAMS":
            values = values.copy()
            values[pressure_index] = 0
        return values

    rewrite(run_record.directory / "outputs/SPE1.UNSMRY", zero_pressure)
    with pytest.raises(ValueError, match="Absolute well pressures"):
        read(run_record, JobId.new(), "This is flow 2026.04")
