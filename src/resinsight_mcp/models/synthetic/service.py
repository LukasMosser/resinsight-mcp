"""Publish generated inputs through the existing OPM import boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory

from resinsight_mcp.contracts.errors import (
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import GridId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.imports import ImportReceipt, ImportRequest, OpmImportService

from .deck import render_deck
from .records import SyntheticModelReceipt, SyntheticModelRequest


class SyntheticModelService:
    """Create one fixed revision without starting a simulator or application."""

    def __init__(self, store: WorkspaceStore) -> None:
        self._imports = OpmImportService(store)

    def create_model(
        self, request: SyntheticModelRequest
    ) -> OperationResult[SyntheticModelReceipt]:
        imported: ImportReceipt | None = None
        import_failure: Failure | None = None
        grid_id = GridId.new()
        try:
            with TemporaryDirectory(prefix="synthetic-model-") as directory:
                root = Path(directory).resolve()
                (root / "SYNTHETIC.DATA").write_text(
                    render_deck(request.specification, grid_id), encoding="utf-8"
                )
                result = self._imports.import_model(
                    ImportRequest(
                        session_id=request.session_id,
                        source_root=root,
                        entrypoint="SYNTHETIC.DATA",
                        datum=request.datum,
                    )
                )
                if isinstance(result.outcome, Failure):
                    import_failure = result.outcome
                    return OperationResult(outcome=result.outcome)
                imported = result.outcome.value
        except OSError as error:
            if import_failure is not None:
                return OperationResult(
                    outcome=Failure(
                        error=import_failure.error.model_copy(
                            update={
                                "message": (
                                    f"{import_failure.error.message} "
                                    f"Source cleanup also failed: {error}."
                                )
                            }
                        )
                    )
                )
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED,
                        effect=MutationEffect.NOT_APPLIED
                        if imported is None
                        else MutationEffect.UNKNOWN,
                        message=(
                            f"Generated source storage failed: {error}."
                            if imported is None
                            else (
                                "Source cleanup failed after revision "
                                f"{imported.prepared.revision.model}: {error}."
                            )
                        ),
                    )
                )
            )
        revision = imported.prepared.revision
        return OperationResult(
            outcome=Success(
                value=SyntheticModelReceipt(
                    imported=imported,
                    specification_source=ArtifactRef(
                        session_id=revision.model.session_id,
                        artifact_id=revision.inputs.entrypoint,
                    ),
                    active_cells=request.specification.grid.active_cells(revision.model, grid_id),
                )
            )
        )
