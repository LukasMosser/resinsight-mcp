"""Read supported OPM outputs in an isolated process through official interfaces."""

import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from resinsight_mcp.contracts.engineering import (
    ActiveCellMap,
    CellIndex,
    ReportSeries,
    ReportTime,
    Unit,
)
from resinsight_mcp.contracts.identifiers import JobId
from resinsight_mcp.contracts.results import (
    CellPropertySeries,
    GridGeometry,
    ResultDataset,
    SummaryCurve,
)

from .records import SATURATION_BOUND_TOLERANCE, FlowAssessment, FlowRunRecord, SemanticArray

type FloatValues = Sequence[float] | npt.NDArray[np.float32] | npt.NDArray[np.float64]


class _Grid(Protocol):
    dimension: Sequence[int]
    active_cells: int

    def ijk_from_active_index(self, index: int) -> tuple[int, int, int]: ...

    def xyz_from_active_index(
        self, index: int
    ) -> tuple[Sequence[float], Sequence[float], Sequence[float]]: ...


class _Initial(Protocol):
    def __getitem__(self, keyword: str) -> FloatValues: ...


class _Restart(Protocol):
    report_steps: Sequence[int]

    def __getitem__(self, key: tuple[str, int]) -> FloatValues: ...


class _Summary(Protocol):
    start_date: datetime

    def units(self, keyword: str) -> str: ...

    def keys(self, pattern: str) -> list[str]: ...

    def __getitem__(self, key: tuple[str, bool]) -> FloatValues: ...


def _same_values(actual: FloatValues, expected: tuple[float, ...], name: str) -> None:
    values = np.asarray(actual)
    if len(values) != len(expected) or not np.all(np.isfinite(values)):
        raise ValueError(f"{name} has missing or nonfinite values.")
    magnitude = np.asarray(max(abs(value) for value in expected), dtype=values.dtype)
    tolerance = 2 * abs(float(np.spacing(magnitude)))
    if not np.allclose(values, expected, rtol=0, atol=tolerance):
        raise ValueError(f"{name} differs from the submitted model beyond output precision.")


def _verify_inputs(run: FlowRunRecord, grid: _Grid, initial: _Initial) -> ActiveCellMap:
    inspection = run.inspection
    cells = tuple(
        CellIndex(i=int(i), j=int(j), k=int(k))
        for i, j, k in (grid.ijk_from_active_index(index) for index in range(grid.active_cells))
    )
    if tuple(grid.dimension) != inspection.summary.dimensions or cells != inspection.active_cells:
        raise ValueError("Output grid dimensions or active-cell order differ from the model.")
    for keyword, values in inspection.properties.keyword_arrays():
        _same_values(initial[keyword], values, keyword)
    _same_values(initial["DEPTH"], inspection.cell_depths_ft, "DEPTH")
    porosity = dict(inspection.properties.keyword_arrays())["PORO"]
    _same_values(
        initial["PORV"],
        tuple(
            volume * fraction * 96 / 539
            for volume, fraction in zip(inspection.cell_volumes_ft3, porosity, strict=True)
        ),
        "PORV",
    )
    if int(initial["INTEHEAD"][2]) != 2:
        raise ValueError("Initial output must use FIELD units.")
    return ActiveCellMap(
        model=run.model, grid_id=run.grid_id, dimensions=inspection.summary.dimensions, cells=cells
    )


def _reports(
    run: FlowRunRecord, restart: _Restart, summary: _Summary
) -> tuple[ReportSeries, tuple[int, ...]]:
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import Parser
    from opm.io.schedule import Schedule

    expected = run.inspection.report_elapsed_days
    steps = tuple(int(step) for step in restart.report_steps)
    if steps != tuple(range(len(expected))):
        raise ValueError("Restart reports differ from the complete submitted schedule.")
    if summary.units("TIME").strip() != "DAYS":
        raise ValueError("Summary report times must use days.")
    times = summary["TIME", True]
    _same_values(times, expected[1:], "Report times")
    deck = Parser().parse(str(run.directory / "inputs" / run.entrypoint))
    dates = Schedule(deck, EclipseState(deck)).reportsteps
    if len(dates) != len(expected) or summary.start_date.date() != dates[0].date():
        raise ValueError("Output calendar dates differ from the submitted schedule.")
    reports = []
    for step in steps:
        header = restart["INTEHEAD", step]
        if int(header[2]) != 2 or int(header[68]) != step:
            raise ValueError("Restart units or report identity differ from the submitted schedule.")
        date = datetime(int(header[66]), int(header[65]), int(header[64])).date()
        days = restart["DOUBHEAD", step][:1]
        _same_values(days, (expected[step],), "Restart elapsed days")
        if date != dates[step].date():
            raise ValueError("Restart calendar dates differ from the submitted schedule.")
        if step:
            reports.append(ReportTime(index=step, elapsed_days=float(days[0]), calendar_date=date))
    return ReportSeries(reports=tuple(reports)), steps[1:]


def _properties(restart: _Restart, steps: tuple[int, ...]) -> tuple[CellPropertySeries, ...]:
    properties = []
    for name, unit in (("PRESSURE", Unit.PSI), ("SWAT", Unit.ONE), ("SGAS", Unit.ONE)):
        rows = tuple(tuple(float(value) for value in restart[name, step]) for step in steps)
        if name == "PRESSURE" and any(value <= 0 for row in rows for value in row):
            raise ValueError("Absolute cell pressures must be positive.")
        if name != "PRESSURE" and any(
            value < -SATURATION_BOUND_TOLERANCE or value > 1 + SATURATION_BOUND_TOLERANCE
            for row in rows
            for value in row
        ):
            raise ValueError(f"{name} lies outside the saturation range.")
        properties.append(CellPropertySeries(name=name, unit=unit, values=rows))
    water, gas = properties[1:]
    tolerance = SATURATION_BOUND_TOLERANCE
    for water_row, gas_row in zip(water.values, gas.values, strict=True):
        if any(
            water_value + gas_value < -tolerance or water_value + gas_value > 1 + tolerance
            for water_value, gas_value in zip(water_row, gas_row, strict=True)
        ):
            raise ValueError("Combined phase saturations leave oil outside its physical bounds.")
    return tuple(properties)


def _curves(run: FlowRunRecord, summary: _Summary) -> tuple[SummaryCurve, ...]:
    if summary.units("FOPR").strip() != "STB/DAY":
        raise ValueError("Field oil rate requires STB/DAY output units.")
    curves = [
        SummaryCurve(
            scope="field",
            keyword="FOPR",
            unit=Unit.STOCK_TANK_BARREL_PER_DAY,
            values=tuple(float(value) for value in summary["FOPR", True]),
        )
    ]
    keys = set(summary.keys("WBHP:*"))
    expected = {f"WBHP:{well}" for well in run.inspection.summary.wells}
    if keys != expected:
        raise ValueError("Output well identities differ from the submitted model.")
    for well in run.inspection.summary.wells:
        key = f"WBHP:{well}"
        if summary.units(key).strip() != "PSIA":
            raise ValueError("Well pressures require PSIA output units.")
        if any(value <= 0 for value in summary[key, True]):
            raise ValueError("Absolute well pressures must be positive.")
        curves.append(
            SummaryCurve(
                scope="well",
                keyword="WBHP",
                well_name=well,
                unit=Unit.PSI,
                values=tuple(float(value) for value in summary[key, True]),
            )
        )
    return tuple(curves)


def read(run: FlowRunRecord, job_id: JobId, log: str) -> tuple[ResultDataset, FlowAssessment]:
    from opm.io.ecl import EclFile, EGrid, ERst, ESmry

    basename = run.directory / "outputs" / Path(run.entrypoint).stem
    grid = EGrid(str(basename.with_suffix(".EGRID")))
    if EclFile(str(basename.with_suffix(".EGRID")))["GRIDUNIT"][0].strip() != "FEET":
        raise ValueError("Output grid coordinates must use feet.")
    initial = EclFile(str(basename.with_suffix(".INIT")))
    restart = ERst(str(basename.with_suffix(".UNRST")))
    summary = ESmry(str(basename.with_suffix(".SMSPEC")))
    cells = _verify_inputs(run, grid, initial)
    reports, steps = _reports(run, restart, summary)
    lines = (line.strip().strip("*").strip() for line in log.splitlines())
    versions = {line.removeprefix("This is ") for line in lines if line.startswith("This is ")}
    if versions != {run.expected_program_version}:
        raise ValueError("The observed Flow version differs from the pinned expected version.")
    dataset = ResultDataset(
        job_id=job_id,
        model=run.model,
        active_cells=cells,
        geometry=GridGeometry.model_validate(
            {
                "coordinates": run.coordinates,
                "cell_corners": tuple(
                    tuple(
                        (float(x), float(y), float(z))
                        for x, y, z in zip(*grid.xyz_from_active_index(index), strict=True)
                    )
                    for index in range(grid.active_cells)
                ),
            }
        ),
        report_series=reports,
        cell_properties=_properties(restart, steps),
        curves=_curves(run, summary),
    )
    assessment = FlowAssessment(
        expected_program_version=run.expected_program_version,
        observed_program_version=versions.pop(),
        final_simulated_days=reports.reports[-1].elapsed_days,
        expected_simulated_days=run.inspection.summary.elapsed_days,
        warnings=tuple(line.strip() for line in log.splitlines() if "warning" in line.lower()),
        input_and_output_identity_verified=True,
        initial_arrays=tuple(
            SemanticArray(name=name, unit=str(kind), values=tuple(initial[index]))
            for index, (name, kind, _) in enumerate(initial.arrays)
        ),
        summary_arrays=tuple(
            SemanticArray(name=key, unit=summary.units(key), values=tuple(summary[key, True]))
            for key in sorted(summary.keys("*"))
        ),
    )
    return dataset, assessment


def main() -> None:
    run = FlowRunRecord.model_validate_json(Path(sys.argv[1]).read_text())
    dataset, assessment = read(run, JobId(sys.argv[2]), Path(sys.argv[3]).read_text())
    Path(sys.argv[4]).write_text(
        json.dumps(
            {
                "dataset": dataset.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
