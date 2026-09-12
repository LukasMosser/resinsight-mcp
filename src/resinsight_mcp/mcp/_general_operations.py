"""Expose compact geological authoring and native display operations."""

from typing import Any

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import (
    ArrayInfo,
    ArrayJoinRequest,
    ArrayRange,
    ArrayRangeRequest,
    ArrayWriteRequest,
)
from resinsight_mcp.models.general.records import (
    CornerPointRequest,
    GeneralCapabilities,
    GeologicalModel,
    GeologicalRequest,
)
from resinsight_mcp.models.general.wells import WellPlan, WellPlanRequest
from resinsight_mcp.resinsight.general.records import (
    EditedGrid,
    GridLoadRequest,
    GridRenderRequest,
    GridRestoreRequest,
    GridVerification,
    GridVerifyRequest,
    LoadedGrid,
)
from resinsight_mcp.resinsight.general.well_records import (
    GeneralWellBinding,
    GeneralWellConnections,
    GeneralWellLoad,
    GeneralWellState,
)

from .catalog import Bindings, EmptyRequest, Operation


def general_operations(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    operations: list[Operation[Any, Any]] = []
    if bindings.general_models is not None and bindings.arrays is not None:
        models, arrays = bindings.general_models, bindings.arrays
        operations.extend(
            (
                Operation(
                    "general_capabilities",
                    "Read geometry capabilities and explicit operator resource configuration.",
                    EmptyRequest,
                    OperationResult[GeneralCapabilities],
                    lambda _: models.capabilities(),
                    read_only=True,
                ),
                Operation(
                    "array_upload",
                    "Store one numeric array part with explicit units.",
                    ArrayWriteRequest,
                    OperationResult[ArrayInfo],
                    arrays.upload,
                ),
                Operation(
                    "array_join",
                    "Join compatible array references without copying their numeric values.",
                    ArrayJoinRequest,
                    OperationResult[ArrayInfo],
                    arrays.join,
                ),
                Operation(
                    "array_inspect",
                    "Read a compact stored array description.",
                    ArtifactRef,
                    OperationResult[ArrayInfo],
                    arrays.inspect,
                    read_only=True,
                ),
                Operation(
                    "array_range",
                    "Read a bounded numeric range without reading unrelated chunks.",
                    ArrayRangeRequest,
                    OperationResult[ArrayRange],
                    arrays.query,
                    read_only=True,
                ),
                Operation(
                    "geological_create",
                    "Create an immutable corner-point model from explicit array artifacts.",
                    CornerPointRequest,
                    OperationResult[GeologicalModel],
                    models.create,
                ),
                Operation(
                    "geological_generate",
                    "Generate folded, faulted layers with rock bands and channel properties.",
                    GeologicalRequest,
                    OperationResult[GeologicalModel],
                    models.generate,
                ),
                Operation(
                    "geological_inspect",
                    "Read the model description and compact array references.",
                    ModelRef,
                    OperationResult[GeologicalModel],
                    models.inspect,
                    read_only=True,
                ),
            )
        )
    if bindings.general_grids is not None:
        native = bindings.general_grids
        operations.extend(
            (
                Operation(
                    "geological_restore",
                    "Verify and restore saved geological sources after project reopening.",
                    GridRestoreRequest,
                    OperationResult[LoadedGrid],
                    native.restore,
                ),
                Operation(
                    "geological_verify",
                    "Read selected native corners and verify authored active properties.",
                    GridVerifyRequest,
                    OperationResult[GridVerification],
                    native.inspect_native,
                    read_only=True,
                ),
                Operation(
                    "geological_load",
                    "Load authored geometry in ResInsight and verify active properties.",
                    GridLoadRequest,
                    OperationResult[LoadedGrid],
                    native.load,
                ),
                Operation(
                    "geological_render",
                    "Render authored geology with an explicit camera and optional J section.",
                    GridRenderRequest,
                    OperationResult[EditedGrid],
                    native.render,
                ),
            )
        )
    if bindings.general_well_models is not None:
        plans = bindings.general_well_models
        operations.extend(
            (
                Operation(
                    "general_well_define",
                    "Publish a well plan from target and interval arrays in model units.",
                    WellPlanRequest,
                    OperationResult[WellPlan],
                    plans.define,
                ),
                Operation(
                    "general_well_inspect",
                    "Read a stored well plan and its array references.",
                    ArtifactRef,
                    OperationResult[WellPlan],
                    plans.inspect,
                    read_only=True,
                ),
            )
        )
    if bindings.general_native_wells is not None:
        wells = bindings.general_native_wells
        operations.extend(
            (
                Operation(
                    "general_well_load",
                    "Create a native well on an authored grid and record its sampled trajectory.",
                    GeneralWellLoad,
                    OperationResult[GeneralWellState],
                    wells.load,
                ),
                Operation(
                    "general_well_restore",
                    "Verify a native well against its saved plan and trajectory.",
                    GeneralWellBinding,
                    OperationResult[GeneralWellState],
                    wells.restore,
                    read_only=True,
                ),
                Operation(
                    "general_well_export",
                    "Verify and store native active-cell connections as bounded-query arrays.",
                    GeneralWellBinding,
                    OperationResult[GeneralWellConnections],
                    wells.export,
                ),
                Operation(
                    "general_well_connections",
                    "Read a stored connection export and its array references.",
                    ArtifactRef,
                    OperationResult[GeneralWellConnections],
                    wells.connections,
                    read_only=True,
                ),
            )
        )
    return tuple(operations)
