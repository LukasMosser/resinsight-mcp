"""Expose existing model services without owning input validation or publication."""

from typing import Any

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.errors import OperationResult, Success
from resinsight_mcp.contracts.identifiers import RevisionId
from resinsight_mcp.contracts.models import ModelRevision, PreparationRequest, PreparedModel
from resinsight_mcp.models.imports import (
    ImportReceipt,
    ImportRequest,
    ModelInspection,
    OpmImportService,
)
from resinsight_mcp.models.synthetic import (
    SyntheticModelReceipt,
    SyntheticModelRequest,
    SyntheticModelSpec,
    reference_specification,
)

from .catalog import Bindings, EmptyRequest, Operation


class CloneModelRequest(Record):
    source: ModelRef
    revision_id: RevisionId


def _inspect(service: OpmImportService, model: ModelRef) -> OperationResult[ModelInspection]:
    with service.materialize(model) as materialized:
        inspection = materialized.inspection
    return OperationResult(outcome=Success(value=inspection))


def model_operations(bindings: Bindings) -> tuple[Operation[Any, Any], ...]:
    operations: list[Operation[Any, Any]] = []
    imports = bindings.imports
    if imports is not None:
        operations.extend(
            (
                Operation(
                    "model_import",
                    "Import supported FIELD inputs from an explicit local directory.",
                    ImportRequest,
                    OperationResult[ImportReceipt],
                    imports.import_model,
                    session_id=lambda request: request.session_id,
                ),
                Operation(
                    "model_get",
                    "Read a fixed model revision and its input artifact identities.",
                    ModelRef,
                    OperationResult[ModelRevision],
                    bindings.workspaces.get_revision,
                    session_id=lambda request: request.session_id,
                    read_only=True,
                ),
                Operation(
                    "model_inspect",
                    "Validate FIELD inputs and return geometry, properties, and report times.",
                    ModelRef,
                    OperationResult[ModelInspection],
                    lambda request: _inspect(imports, request),
                    session_id=lambda request: request.session_id,
                    read_only=True,
                ),
                Operation(
                    "model_prepare",
                    "Validate an exact stored revision for the requested simulator backend.",
                    PreparationRequest,
                    OperationResult[PreparedModel],
                    imports.prepare,
                    session_id=lambda request: request.revision.model.session_id,
                    read_only=True,
                ),
                Operation(
                    "model_clone",
                    "Create a child revision that retains every input from its exact parent.",
                    CloneModelRequest,
                    OperationResult[ModelRevision],
                    lambda request: bindings.workspaces.clone_revision(
                        request.source, request.revision_id
                    ),
                    session_id=lambda request: request.source.session_id,
                ),
            )
        )
    synthetic = bindings.synthetic_models
    if synthetic is not None:
        operations.extend(
            (
                Operation(
                    "model_template",
                    "Read the tested layered FIELD specification before requesting model creation.",
                    EmptyRequest,
                    OperationResult[SyntheticModelSpec],
                    lambda _: OperationResult(outcome=Success(value=reference_specification())),
                    read_only=True,
                ),
                Operation(
                    "model_create",
                    "Create a constrained layered FIELD model with explicit wells and controls.",
                    SyntheticModelRequest,
                    OperationResult[SyntheticModelReceipt],
                    synthetic.create_model,
                    session_id=lambda request: request.session_id,
                ),
            )
        )
    return tuple(operations)
