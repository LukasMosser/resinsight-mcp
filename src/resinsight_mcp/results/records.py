"""Queries and comparisons retain their complete source identity."""

from datetime import timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, FiniteFloat, PositiveInt, model_validator

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import ActiveCellMap, ReportTime, Unit
from resinsight_mcp.contracts.identifiers import ObservationId, ResultId, SessionId
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import ImageArtifact, Legend
from resinsight_mcp.contracts.results import GridGeometry, ResultOutputRole
from resinsight_mcp.contracts.sessions import ApplicationContext


class ResultRef(Record):
    session_id: SessionId
    result_id: ResultId


class CellQuery(Record):
    result: ResultRef
    property: Text
    report_time: ReportTime


class CurveQuery(Record):
    result: ResultRef
    scope: Literal["field", "well"]
    keyword: Text
    well_name: Text | None = None

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if (self.scope == "well") != (self.well_name is not None):
            raise ValueError("Only a well curve requires a well name.")
        return self


class CellValues(Record):
    result: Result
    active_cells: ActiveCellMap
    geometry: GridGeometry
    property: Text
    unit: Unit
    report_time: ReportTime
    values: tuple[FiniteFloat, ...]


class CurveValues(Record):
    result: Result
    scope: Literal["field", "well"]
    keyword: Text
    well_name: Text | None
    unit: Unit
    reports: tuple[ReportTime, ...]
    values: tuple[FiniteFloat, ...]


class CellComparison(Record):
    baseline: CellValues
    scenario: CellValues
    differences: tuple[FiniteFloat, ...]
    legend: Legend


class CurveComparison(Record):
    baseline: CurveValues
    scenario: CurveValues
    differences: tuple[FiniteFloat, ...]


class SummaryPlotRequest(Record):
    context: ApplicationContext
    query: CurveQuery
    width: PositiveInt
    height: PositiveInt

    @model_validator(mode="after")
    def check_session(self) -> Self:
        if self.context.session_id != self.query.result.session_id:
            raise ValueError("The summary plot and result must belong to one session.")
        return self


class SummaryObservation(Record):
    observation_id: ObservationId
    context: ApplicationContext
    curve: CurveValues
    plot_address: Text
    source: ArtifactRef
    image: ImageArtifact
    captured_at: AwareDatetime
    provenance: ArtifactRef

    @model_validator(mode="after")
    def check_provenance(self) -> Self:
        session_id = self.curve.result.model.session_id
        if self.context.session_id != session_id or any(
            ref.session_id != session_id
            for ref in (self.source, self.image.artifact, self.provenance)
        ):
            raise ValueError("The summary observation must retain one session identity.")
        manifest = self.curve.result.manifest
        if manifest is None or not any(
            item.role == ResultOutputRole.SMSPEC and item.artifact == self.source
            for item in manifest.outputs
        ):
            raise ValueError("The summary source must identify this result's SMSPEC artifact.")
        if self.captured_at.utcoffset() != timedelta(0):
            raise ValueError("Summary capture timestamps must use UTC.")
        return self
