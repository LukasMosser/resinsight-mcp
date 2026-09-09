"""Validated simulator output identities and report-aligned numerical data."""

from enum import StrEnum
from itertools import pairwise
from typing import Literal, Self

from pydantic import FiniteFloat, NonNegativeInt, model_validator

from ._base import Record, Text
from .engineering import ActiveCellMap, CoordinateFrame, ModelRef, ReportSeries, Unit
from .identifiers import JobId
from .models import ArtifactRef


class ResultOutputRole(StrEnum):
    EGRID = "EGRID"
    INIT = "INIT"
    UNRST = "UNRST"
    SMSPEC = "SMSPEC"
    UNSMRY = "UNSMRY"


class ResultOutput(Record):
    role: ResultOutputRole
    artifact: ArtifactRef


class ResultManifest(Record):
    """Artifact names remain in the workspace artifact records."""

    outputs: tuple[ResultOutput, ...]
    active_cells: ActiveCellMap
    restart_report_steps: tuple[NonNegativeInt, ...]
    numerical_data: ArtifactRef
    assessment_evidence: ArtifactRef

    @model_validator(mode="after")
    def check_manifest(self) -> Self:
        roles = [item.role for item in self.outputs]
        if len(roles) != len(ResultOutputRole) or set(roles) != set(ResultOutputRole):
            raise ValueError("A result requires each supported output role exactly once.")
        refs = [item.artifact for item in self.outputs]
        refs.extend((self.numerical_data, self.assessment_evidence))
        if len(set(refs)) != len(refs):
            raise ValueError("Result artifacts must have distinct identities.")
        if any(ref.session_id != self.active_cells.model.session_id for ref in refs):
            raise ValueError("Result artifacts must belong to the model session.")
        if not self.restart_report_steps or any(
            right <= left for left, right in pairwise(self.restart_report_steps)
        ):
            raise ValueError("Restart report steps must be nonempty and increase.")
        return self


class CellPropertySeries(Record):
    """Each row contains one report in active-cell order."""

    name: Text
    unit: Unit
    values: tuple[tuple[FiniteFloat, ...], ...]


class SummaryCurve(Record):
    scope: Literal["field", "well"]
    keyword: Text
    well_name: Text | None = None
    unit: Unit
    values: tuple[FiniteFloat, ...]

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if (self.scope == "well") != (self.well_name is not None):
            raise ValueError("Only a well curve requires a well name.")
        return self


type Point3D = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
type CellCorners = tuple[Point3D, Point3D, Point3D, Point3D, Point3D, Point3D, Point3D, Point3D]


class GridGeometry(Record):
    """Rows follow active-cell order, with eight corners in OPM EGRID order."""

    coordinates: CoordinateFrame
    cell_corners: tuple[CellCorners, ...]


class ResultDataset(Record):
    """A metadata artifact contains this record as JSON."""

    job_id: JobId
    model: ModelRef
    active_cells: ActiveCellMap
    geometry: GridGeometry
    report_series: ReportSeries
    cell_properties: tuple[CellPropertySeries, ...]
    curves: tuple[SummaryCurve, ...]

    @model_validator(mode="after")
    def check_data(self) -> Self:
        if self.active_cells.model != self.model:
            raise ValueError("The active-cell map must identify the dataset model.")
        names = [item.name for item in self.cell_properties]
        if len(set(names)) != len(names):
            raise ValueError("Cell property names must be unique.")
        keys = [(item.scope, item.keyword, item.well_name) for item in self.curves]
        if len(set(keys)) != len(keys):
            raise ValueError("Summary curve identities must be unique.")
        reports = len(self.report_series.reports)
        cells = len(self.active_cells.cells)
        if len(self.geometry.cell_corners) != cells:
            raise ValueError("Grid geometry must contain one corner row for each active cell.")
        for item in self.cell_properties:
            if len(item.values) != reports or any(len(row) != cells for row in item.values):
                raise ValueError("Cell property arrays must match reports and active cells.")
        if any(len(item.values) != reports for item in self.curves):
            raise ValueError("Summary curves must match the report series.")
        return self
