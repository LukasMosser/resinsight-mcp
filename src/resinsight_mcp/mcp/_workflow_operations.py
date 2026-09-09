"""Bind the reviewed well, simulator, and result interfaces to explicit session tools."""

from typing import Any

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.identifiers import ResultId
from resinsight_mcp.contracts.jobs import JobRef, LoadedResult, Result, ResultImportRequest
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectRef
from resinsight_mcp.models.imports import ImportReceipt
from resinsight_mcp.models.wells.records import (
    CompletionExport,
    ModeledWell,
    PreparedCase,
    PreparedCaseRequest,
    PreparedCaseRestoreRequest,
    WellAdoptRequest,
    WellCreateRequest,
    WellExportRequest,
    WellScheduleRequest,
    WellUpdateRequest,
)
from resinsight_mcp.results.records import (
    CellComparison,
    CellQuery,
    CellValues,
    CurveComparison,
    CurveQuery,
    CurveValues,
    EditedSummaryPlot,
    ResultRef,
    SummaryPlotRequest,
)

from .catalog import Bindings, Operation


class ResultBindingsRequest(Record):
    context: ApplicationContext
    result_ids: tuple[ResultId, ...]


class CellComparisonRequest(Record):
    baseline: CellQuery
    scenario: CellQuery


class CurveComparisonRequest(Record):
    baseline: CurveQuery
    scenario: CurveQuery


def workflow_operations(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    operations: list[Operation[Any, Any]] = []
    wells = bindings.wells
    if wells is not None:
        operations.extend(
            (
                Operation(
                    "model_load_case",
                    "Load a fixed FIELD model into a persistent native case for modeled wells.",
                    PreparedCaseRequest,
                    OperationResult[PreparedCase],
                    wells.load,
                    session_id=lambda request: request.model.session_id,
                ),
                Operation(
                    "model_restore_case",
                    "Verify a current native case against its fixed model and saved receipt.",
                    PreparedCaseRestoreRequest,
                    OperationResult[PreparedCase],
                    wells.restore_case,
                    session_id=lambda request: request.model.session_id,
                ),
                Operation(
                    "well_create",
                    "Create a modeled well with explicit FIELD targets and perforation intervals.",
                    WellCreateRequest,
                    OperationResult[ModeledWell],
                    wells.create,
                    session_id=lambda request: request.binding.model.session_id,
                ),
                Operation(
                    "well_update",
                    "Update a current modeled well after checking its exact expected version.",
                    WellUpdateRequest,
                    OperationResult[ModeledWell],
                    wells.update,
                    session_id=lambda request: request.well.context.session_id,
                ),
                Operation(
                    "well_inspect",
                    "Verify a service-owned well and read its definition, trajectory, and version.",
                    ObjectRef,
                    OperationResult[ModeledWell],
                    wells.inspect,
                    session_id=lambda request: request.context.session_id,
                    read_only=True,
                ),
                Operation(
                    "well_adopt",
                    "Verify an existing modeled well before issuing a fresh native lifetime.",
                    WellAdoptRequest,
                    OperationResult[ModeledWell],
                    wells.adopt_well,
                    session_id=lambda request: request.binding.model.session_id,
                ),
                Operation(
                    "well_export",
                    "Export native completions with active cells, FIELD values, and provenance.",
                    WellExportRequest,
                    OperationResult[CompletionExport],
                    wells.export,
                    session_id=lambda request: request.well.context.session_id,
                ),
                Operation(
                    "well_export_get",
                    "Read and verify an immutable native completion export after reconnection.",
                    ArtifactRef,
                    OperationResult[CompletionExport],
                    wells.get_export,
                    session_id=lambda request: request.session_id,
                    read_only=True,
                ),
            )
        )
    schedules = bindings.schedules
    if schedules is not None:
        operations.append(
            Operation(
                "model_publish_schedule",
                "Publish a child revision from native completions and explicit supported controls.",
                WellScheduleRequest,
                OperationResult[ImportReceipt],
                schedules.publish,
                session_id=lambda request: request.parent.session_id,
            )
        )
    flow = bindings.flow
    if flow is not None:
        operations.append(
            Operation(
                "opm_collect",
                "Validate completed Flow outputs and publish their immutable accepted result.",
                JobRef,
                OperationResult[Result],
                flow.collect,
                session_id=lambda request: request.session_id,
            )
        )
    results = bindings.results
    if results is not None:
        operations.extend(
            (
                Operation(
                    "result_get",
                    "Read a stored result with exact model, grid, reports, and output references.",
                    ResultRef,
                    OperationResult[Result],
                    lambda request: bindings.workspaces.get_result(
                        request.session_id, request.result_id
                    ),
                    session_id=lambda request: request.session_id,
                    read_only=True,
                ),
                Operation(
                    "result_load",
                    "Load verified grid and summary files from an accepted stored Flow result.",
                    ResultImportRequest,
                    OperationResult[LoadedResult],
                    results.load,
                    session_id=lambda request: request.context.session_id,
                ),
                Operation(
                    "result_rebind",
                    "Verify native result cases and bind them to the current project.",
                    ResultBindingsRequest,
                    OperationResult[tuple[LoadedResult, ...]],
                    lambda request: results.rebind(request.context, request.result_ids),
                    session_id=lambda request: request.context.session_id,
                ),
                Operation(
                    "result_cell_property",
                    "Read accepted PRESSURE, SWAT, or SGAS with units, geometry, and report time.",
                    CellQuery,
                    OperationResult[CellValues],
                    results.cell_property,
                    session_id=lambda request: request.result.session_id,
                    read_only=True,
                ),
                Operation(
                    "result_curve",
                    "Read accepted FOPR or well WBHP values with units and report times.",
                    CurveQuery,
                    OperationResult[CurveValues],
                    results.curve,
                    session_id=lambda request: request.result.session_id,
                    read_only=True,
                ),
                Operation(
                    "result_compare_cells",
                    "Subtract baseline cells from aligned scenario cells and return one legend.",
                    CellComparisonRequest,
                    OperationResult[CellComparison],
                    lambda request: results.compare_cells(request.baseline, request.scenario),
                    session_id=lambda request: request.baseline.result.session_id,
                    read_only=True,
                ),
                Operation(
                    "result_compare_curves",
                    "Compare matching summary curves on aligned calendar dates and elapsed times.",
                    CurveComparisonRequest,
                    OperationResult[CurveComparison],
                    lambda request: results.compare_curves(request.baseline, request.scenario),
                    session_id=lambda request: request.baseline.result.session_id,
                    read_only=True,
                ),
                Operation(
                    "result_show_curve",
                    "Create a native summary plot with an applied receipt and fresh image outcome.",
                    SummaryPlotRequest,
                    OperationResult[EditedSummaryPlot],
                    results.show_curve,
                    session_id=lambda request: request.context.session_id,
                ),
            )
        )
    return tuple(operations)
