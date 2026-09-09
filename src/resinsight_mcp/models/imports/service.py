"""Import fixed source files after successful OPM model validation."""

import io
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
    MutationEffect,
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
from .records import (
    DerivedModelRequest,
    ImportReceipt,
    ImportRecord,
    ImportRequest,
    MaterializedModel,
    ModelInspection,
)


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


def _validate(
    entrypoint: Path, output: Path, *, expected_source: Path | None = None
) -> ModelInspection:
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "resinsight_mcp.models.imports._worker",
                str(entrypoint),
                str(output),
                *([str(expected_source)] if expected_source is not None else []),
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
    return ModelInspection.model_validate(payload["inspection"])


class OpmImportService:
    """Validate the published FIELD profile without submitting simulator jobs."""

    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    @staticmethod
    def check_dependencies() -> None:
        """Raise ContractError when the isolated import worker cannot load its dependencies."""
        try:
            checked = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "resinsight_mcp.models.imports._worker",
                    "--check-dependencies",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise invalid(f"Cannot check OPM import dependencies: {error}") from error
        if checked.returncode != 0:
            raise invalid(
                f"OPM import dependencies are unavailable: {checked.stdout[-4000:].strip()}"
            )

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
        return self._publish(request, coordinates)

    @_operation
    def derive_model(self, request: DerivedModelRequest) -> ImportReceipt:
        parent = self._stored_revision(request.parent)
        return self._publish(
            ImportRequest(
                session_id=parent.model.session_id,
                source_root=request.source_root,
                entrypoint=request.entrypoint,
                datum=parent.coordinates.datum,
            ),
            parent.coordinates,
            parent=parent.model,
        )

    def _publish(
        self,
        request: ImportRequest,
        coordinates: CoordinateFrame,
        *,
        parent: ModelRef | None = None,
    ) -> ImportReceipt:
        model = ModelRef(session_id=request.session_id, revision_id=RevisionId.new())
        publication_started = False
        try:
            with TemporaryDirectory(prefix="opm-import-") as directory:
                root = Path(directory).resolve()
                snapshot = root / "inputs"
                names, edges = collect(request.source_root, request.entrypoint, snapshot)
                summary = _validate(snapshot / request.entrypoint, root / "validation.json").summary
                sources = {}
                for name in names:
                    with (snapshot / name).open("rb") as stream:
                        publication_started = True
                        sources[name] = self._write(
                            request.session_id, name, stream, ArtifactKind.INPUT
                        )
                revision = ModelRevision(
                    model=model,
                    inputs=ModelInputs(
                        artifacts=tuple(ref.artifact_id for ref in sources.values()),
                        entrypoint=sources[request.entrypoint].artifact_id,
                    ),
                    unit_system=UnitSystem.FIELD,
                    coordinates=coordinates,
                    parent=parent,
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
        except (ContractError, OSError, UnicodeError, ValidationError) as cause:
            if not publication_started:
                raise
            error = (
                cause.error
                if isinstance(cause, ContractError)
                else Error(
                    code=ErrorCode.STORAGE_FAILED
                    if isinstance(cause, OSError)
                    else ErrorCode.INVALID_MODEL,
                    message=str(cause),
                )
            )
            raise ContractError(
                error.model_copy(
                    update={
                        "effect": MutationEffect.UNKNOWN,
                        "message": (
                            f"{error.message} Import publication may be incomplete for "
                            f"session {model.session_id}, revision {model.revision_id}. "
                            "Inspect the session artifacts and revision before retrying."
                        ),
                    }
                )
            ) from cause
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
        revision = self._stored_revision(request.revision.model)
        if revision != request.revision:
            raise invalid("The supplied revision differs from the stored revision.")
        with self.materialize(revision.model):
            return PreparedModel(revision=revision, backend=Backend.OPM_FLOW)

    def _stored_revision(self, model: ModelRef) -> ModelRevision:
        revision = _value(self._store.get_revision(model))
        if (
            revision.unit_system != UnitSystem.FIELD
            or revision.coordinates.length_unit != Unit.FOOT
            or revision.coordinates.depth_direction != DepthDirection.POSITIVE_DOWN
        ):
            raise invalid("FIELD inputs require feet and positive-down depth coordinates.")
        return revision

    def materialize_persistent(self, model: ModelRef, destination: Path) -> MaterializedModel:
        """Create validated sources in a new owned directory without automatic cleanup."""
        revision = self._stored_revision(model)
        try:
            if not destination.is_absolute() or destination.resolve() != destination:
                raise invalid("Persistent model sources require an absolute canonical directory.")
            destination.mkdir(parents=True, exist_ok=False)
            return self._materialized(revision, destination.resolve())
        except (OSError, UnicodeError, ValidationError) as error:
            raise invalid(f"Persistent model materialization failed: {error}") from error

    def reopen_persistent(self, model: ModelRef, destination: Path) -> MaterializedModel:
        """Reparse retained inputs against the fixed revision before native restoration."""
        if not destination.is_absolute() or destination.resolve() != destination:
            raise invalid("Persistent sources require their original absolute directory.")
        with self.materialize(model) as expected:
            entrypoint = expected.entrypoint.relative_to(expected.directory)
            names = tuple(
                _value(
                    self._store.get_artifact(
                        ArtifactRef(session_id=model.session_id, artifact_id=artifact)
                    )
                ).relative_path
                for artifact in expected.revision.inputs.artifacts
            )
            paths = tuple(destination / "inputs" / name for name in names) + (
                destination / "properties.GRDECL",
            )
            if any(path.resolve() != path or not path.is_file() for path in paths):
                raise invalid("A persistent model source is unavailable or redirected.")
            with TemporaryDirectory(prefix="opm-reopen-") as directory:
                temporary = Path(directory)
                actual, _ = collect(destination / "inputs", str(entrypoint), temporary / "inputs")
                if set(actual) != set(names):
                    raise invalid("The persistent include graph differs from the fixed revision.")
                inspection = _validate(
                    temporary / "inputs" / entrypoint,
                    temporary / "validation.json",
                    expected_source=expected.entrypoint,
                )
                if inspection != expected.inspection:
                    raise invalid("The persistent model differs from its fixed parser inspection.")
            return expected.model_copy(
                update={
                    "directory": destination / "inputs",
                    "entrypoint": destination / "inputs" / entrypoint,
                    "property_file": destination / "properties.GRDECL",
                }
            )

    @contextmanager
    def materialize(self, model: ModelRef) -> Iterator[MaterializedModel]:
        """Validate fixed inputs and yield isolated files with parser-derived inspection."""
        revision = self._stored_revision(model)
        staging: TemporaryDirectory[str] | None = None
        original: BaseException | None = None
        try:
            try:
                staging = TemporaryDirectory(prefix="opm-materialize-")
                materialized = self._materialized(revision, Path(staging.name).resolve())
            except (OSError, UnicodeError, ValidationError) as error:
                raise invalid(f"Model materialization failed: {error}") from error
            yield materialized
        except BaseException as error:
            original = error
            raise
        finally:
            if staging is not None:
                try:
                    staging.cleanup()
                except OSError as error:
                    message = f"Model materialization cleanup failed: {error}"
                    if original is not None:
                        original.add_note(message)
                    else:
                        raise ContractError(
                            Error(
                                code=ErrorCode.STORAGE_FAILED,
                                message=message,
                                effect=MutationEffect.UNKNOWN,
                            )
                        ) from error

    def _materialized(self, revision: ModelRevision, root: Path) -> MaterializedModel:
        stored = root / "stored"
        names = []
        entrypoint = ""
        for artifact_id in revision.inputs.artifacts:
            ref = ArtifactRef(session_id=revision.model.session_id, artifact_id=artifact_id)
            artifact = _value(self._store.get_artifact(ref))
            path = stored / artifact.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._store.open_artifact(ref) as source, path.open("wb") as target:
                shutil.copyfileobj(source, target)
            names.append(artifact.relative_path)
            if artifact_id == revision.inputs.entrypoint:
                entrypoint = artifact.relative_path
        inputs = root / "inputs"
        collected, _ = collect(stored, entrypoint, inputs)
        if set(collected) != set(names):
            raise invalid("Every revision input must belong to the entrypoint include graph.")
        inspection = _validate(inputs / entrypoint, root / "validation.json")
        property_file = root / "properties.GRDECL"
        with property_file.open("w", encoding="utf-8") as output:
            output.write("-- Derived FIELD properties: lengths in feet and permeability in mD.\n")
            for keyword, values in inspection.properties.keyword_arrays():
                output.write(f"{keyword}\n")
                output.write(" ".join(format(value, ".17g") for value in values))
                output.write("\n/\n")
        return MaterializedModel(
            revision=revision,
            directory=inputs,
            entrypoint=inputs / entrypoint,
            property_file=property_file,
            inspection=inspection,
        )
