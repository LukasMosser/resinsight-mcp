"""Import fixed source files after successful OPM model validation."""

import io
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO

from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId, SessionId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import (
    ArtifactRef,
    Backend,
    ModelInputs,
    ModelRevision,
    PreparationRequest,
    PreparedModel,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind

from ._sources import collect, invalid
from .records import ImportReceipt, ImportRecord, ImportRequest, ModelSummary


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
        except (OSError, UnicodeError, ValidationError) as error:
            return OperationResult(
                outcome=Failure(error=Error(code=ErrorCode.INVALID_MODEL, message=str(error)))
            )

    return run


def _validate(entrypoint: Path, output: Path) -> ModelSummary:
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "resinsight_mcp.models.imports._worker",
                str(entrypoint),
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            cwd=entrypoint.parent,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise invalid("OPM model validation exceeded 30 seconds.") from error
    if process.returncode != 0 or not output.is_file():
        detail = process.stdout[-4000:].strip()
        raise invalid(f"OPM parser process failed with status {process.returncode}: {detail}")
    payload: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    if "error" in payload:
        raise invalid(f"OPM validation failed: {payload['error']}")
    return ModelSummary.model_validate(payload["summary"])


class OpmImportService:
    """Validate the published FIELD profile without submitting simulator jobs."""

    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    def _write(
        self, session_id: SessionId, name: str, stream: BinaryIO, kind: ArtifactKind
    ) -> ArtifactRef:
        artifact = Artifact(
            ref=ArtifactRef(session_id=session_id, artifact_id=ArtifactId.new()),
            relative_path=name,
            kind=kind,
        )
        return _value(self._store.write_artifact(artifact, stream)).ref

    @_operation
    def import_model(self, request: ImportRequest) -> ImportReceipt:
        _value(self._store.get_session(request.session_id))
        coordinates = CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum=request.datum,
        )
        with TemporaryDirectory(prefix="opm-import-") as directory:
            root = Path(directory).resolve()
            snapshot = root / "inputs"
            names, edges = collect(request.source_root, request.entrypoint, snapshot)
            summary = _validate(snapshot / request.entrypoint, root / "validation.json")
            sources = {}
            for name in names:
                with (snapshot / name).open("rb") as stream:
                    sources[name] = self._write(
                        request.session_id, name, stream, ArtifactKind.INPUT
                    )
            revision = ModelRevision(
                model=ModelRef(session_id=request.session_id, revision_id=RevisionId.new()),
                inputs=ModelInputs(
                    artifacts=tuple(ref.artifact_id for ref in sources.values()),
                    entrypoint=sources[request.entrypoint].artifact_id,
                ),
                unit_system=UnitSystem.FIELD,
                coordinates=coordinates,
            )
            record = ImportRecord(
                model=revision.model,
                source_entrypoint=request.entrypoint,
                sources=sources,
                includes=edges,
                summary=summary,
            )
            record_ref = self._write(
                request.session_id,
                f"imports/{revision.model.revision_id}.json",
                io.BytesIO(record.model_dump_json(indent=2).encode("utf-8")),
                ArtifactKind.LOG,
            )
            _value(self._store.save_revision(revision))
        return ImportReceipt(
            prepared=PreparedModel(revision=revision, backend=Backend.OPM_FLOW),
            record=record_ref,
            summary=summary,
        )

    @_operation
    def prepare(self, request: PreparationRequest) -> PreparedModel:
        if request.backend != Backend.OPM_FLOW:
            raise ContractError(
                Error(
                    code=ErrorCode.UNSUPPORTED_OPERATION,
                    message="The import service requires OPM Flow.",
                )
            )
        revision = _value(self._store.get_revision(request.revision.model))
        if revision != request.revision:
            raise invalid("The supplied revision differs from the stored revision.")
        if (
            revision.unit_system != UnitSystem.FIELD
            or revision.coordinates.length_unit != Unit.FOOT
            or revision.coordinates.depth_direction != DepthDirection.POSITIVE_DOWN
        ):
            raise invalid("FIELD inputs require feet and positive-down depth coordinates.")
        with TemporaryDirectory(prefix="opm-prepare-") as directory:
            root = Path(directory).resolve()
            materialized = root / "stored"
            names = []
            entrypoint = ""
            for artifact_id in revision.inputs.artifacts:
                ref = ArtifactRef(session_id=revision.model.session_id, artifact_id=artifact_id)
                artifact = _value(self._store.get_artifact(ref))
                path = materialized / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                with self._store.open_artifact(ref) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                names.append(artifact.relative_path)
                if artifact_id == revision.inputs.entrypoint:
                    entrypoint = artifact.relative_path
            collected, _ = collect(materialized, entrypoint, root / "inputs")
            if set(collected) != set(names):
                raise invalid("Every revision input must belong to the entrypoint include graph.")
            _validate(root / "inputs" / entrypoint, root / "validation.json")
        return PreparedModel(revision=revision, backend=Backend.OPM_FLOW)
