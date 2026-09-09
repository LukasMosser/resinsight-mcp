"""Keep parser inputs isolated and report partial import publication honestly."""

import io
import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

import pytest

from resinsight_mcp.contracts.engineering import ModelRef
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
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision, Session
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.models.imports import DerivedModelRequest, ImportRequest, OpmImportService
from resinsight_mcp.models.imports.records import ImportRecord
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result
    return result.outcome.value


def request_for(store: SqliteWorkspaceStore, tmp_path: Path) -> ImportRequest:
    source = Path(shutil.copytree(Path(__file__).parent / "data" / "spe1", tmp_path / "source"))
    session = value(store.create_session(Session(session_id=SessionId.new(), name="SPE1")))
    return ImportRequest(
        session_id=session.session_id,
        source_root=source,
        entrypoint="SPE1.DATA",
        datum="SPE1 local datum",
    )


def assert_unpublished(store: SqliteWorkspaceStore, request: ImportRequest) -> None:
    assert value(store.list_artifacts(request.session_id)) == ()
    assert value(store.list_jobs(request.session_id)) == ()


@pytest.mark.parametrize("module", ["resinsight_mcp.py", "resinsight_mcp/__init__.py", "opm.py"])
def test_model_files_cannot_run_as_python_modules(tmp_path: Path, module: str) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    marker = tmp_path / "module-executed"
    module_path = request.source_root / module
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(f"from pathlib import Path\nPath('{marker}').touch()\n")
    entrypoint = request.source_root / request.entrypoint
    entrypoint.write_text(entrypoint.read_text() + f"\nINCLUDE\n '{module}' /\n")

    result = OpmImportService(store).import_model(request)

    assert not marker.exists(), "The parser process executed a model source file."
    assert isinstance(result.outcome, Failure), result
    assert result.outcome.error.code == ErrorCode.INVALID_MODEL
    assert result.outcome.error.effect == MutationEffect.NOT_APPLIED
    assert_unpublished(store, request)


def test_oversized_repetition_returns_a_model_error_without_publication(tmp_path: Path) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    schedule = request.source_root / "includes/schedule.inc"
    schedule.write_text(schedule.read_text().replace("1 1 /", "9" * 5000 + "*1 /"))

    result = OpmImportService(store).import_model(request)

    assert isinstance(result.outcome, Failure), result
    assert result.outcome.error.code == ErrorCode.INVALID_MODEL
    assert result.outcome.error.effect == MutationEffect.NOT_APPLIED
    assert_unpublished(store, request)


class FailSecondArtifactStore(SqliteWorkspaceStore):
    """Save one real source artifact before reporting a storage failure."""

    def write_artifact(self, artifact: Artifact, source: BinaryIO) -> OperationResult[Artifact]:
        if value(self.list_artifacts(artifact.ref.session_id)):
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED, message="Injected artifact storage failure."
                    )
                )
            )
        return super().write_artifact(artifact, source)


class FailRevisionStore(SqliteWorkspaceStore):
    """Leave source artifacts visible when revision storage reports a conflict."""

    def save_revision(self, revision: ModelRevision) -> OperationResult[ModelRevision]:
        return OperationResult(
            outcome=Failure(
                error=Error(code=ErrorCode.CONFLICT, message="Injected revision conflict.")
            )
        )


@pytest.mark.parametrize(
    ("store_class", "code", "message", "artifact_count"),
    [
        (
            FailSecondArtifactStore,
            ErrorCode.STORAGE_FAILED,
            "Injected artifact storage failure.",
            1,
        ),
        (FailRevisionStore, ErrorCode.CONFLICT, "Injected revision conflict.", 6),
    ],
)
def test_partial_publication_preserves_failure_and_reports_recovery_context(
    tmp_path: Path,
    store_class: type[SqliteWorkspaceStore],
    code: ErrorCode,
    message: str,
    artifact_count: int,
) -> None:
    store = store_class.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)

    result = OpmImportService(store).import_model(request)

    assert isinstance(result.outcome, Failure), result
    error = result.outcome.error
    assert error.code == code
    assert error.effect == MutationEffect.UNKNOWN
    assert message in error.message
    assert str(request.session_id) in error.message
    match = re.search(r"revision_[0-9a-f]{32}", error.message)
    assert match is not None, "Partial publication needs a revision identifier for recovery."
    model = ModelRef(session_id=request.session_id, revision_id=RevisionId(match[0]))
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    artifacts = value(reopened.list_artifacts(request.session_id))
    assert len(artifacts) == artifact_count
    assert value(reopened.list_jobs(request.session_id)) == ()
    assert isinstance(reopened.get_revision(model).outcome, Failure)
    entrypoint = next(item for item in artifacts if item.relative_path == "SPE1.DATA")
    with reopened.open_artifact(entrypoint.ref) as stream:
        assert "RUNSPEC" in stream.read().decode().splitlines()
    for artifact in artifacts:
        if artifact.kind == ArtifactKind.LOG:
            with reopened.open_artifact(artifact.ref) as stream:
                record = ImportRecord.model_validate(json.load(stream))
            assert record.model == model
            assert len(record.sources) == 5


def test_leading_zero_repetition_does_not_trigger_integer_conversion_failure(
    tmp_path: Path,
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    schedule = request.source_root / "includes/schedule.inc"
    schedule.write_text(schedule.read_text().replace("1 1 /", "0" * 5000 + "2*1 /"))

    result = OpmImportService(store).import_model(request)

    receipt = value(result)
    assert receipt.summary.report_steps == 2
    assert receipt.summary.elapsed_days == 2.0


def test_cleanup_failure_reports_the_published_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    cleanup = TemporaryDirectory.cleanup

    def fail_cleanup(directory: TemporaryDirectory[str]) -> None:
        cleanup(directory)
        raise OSError("Injected temporary cleanup failure.")

    monkeypatch.setattr(TemporaryDirectory, "cleanup", fail_cleanup)
    result = OpmImportService(store).import_model(request)

    assert isinstance(result.outcome, Failure), result
    error = result.outcome.error
    assert error.code == ErrorCode.STORAGE_FAILED
    assert error.effect == MutationEffect.UNKNOWN
    assert "Injected temporary cleanup failure." in error.message
    assert str(request.session_id) in error.message
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    artifacts = value(reopened.list_artifacts(request.session_id))
    assert len(artifacts) == 6
    record_artifact = next(item for item in artifacts if item.kind == ArtifactKind.LOG)
    with reopened.open_artifact(record_artifact.ref) as stream:
        record = ImportRecord.model_validate(json.load(stream))
    assert str(record.model.revision_id) in error.message
    revision = value(reopened.get_revision(record.model))
    assert set(revision.inputs.artifacts) == {ref.artifact_id for ref in record.sources.values()}
    assert value(reopened.list_jobs(request.session_id)) == ()


class FailChildRevisionStore(SqliteWorkspaceStore):
    """Accept a parent but reject publication of its child revision."""

    def save_revision(self, revision: ModelRevision) -> OperationResult[ModelRevision]:
        if revision.parent is not None:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED, message="Injected child publication failure."
                    )
                )
            )
        return super().save_revision(revision)


def test_derived_publication_failure_preserves_parent_and_reports_unknown(tmp_path: Path) -> None:
    store = FailChildRevisionStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    service = OpmImportService(store)
    parent = value(service.import_model(request)).prepared.revision
    before = value(store.list_artifacts(request.session_id))
    result = service.derive_model(
        DerivedModelRequest(
            parent=parent.model, source_root=request.source_root, entrypoint=request.entrypoint
        )
    )
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.STORAGE_FAILED
    assert result.outcome.error.effect == MutationEffect.UNKNOWN
    assert "Injected child publication failure" in result.outcome.error.message
    assert value(store.get_revision(parent.model)) == parent
    assert len(value(store.list_artifacts(request.session_id))) == len(before) + 6


def test_materialization_validates_the_stored_include_graph_before_yield(tmp_path: Path) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    request = request_for(store, tmp_path)
    service = OpmImportService(store)
    parent = value(service.import_model(request)).prepared.revision
    extra = Artifact(
        ref=ArtifactRef(session_id=request.session_id, artifact_id=ArtifactId.new()),
        relative_path="orphan.inc",
        kind=ArtifactKind.INPUT,
    )
    value(store.write_artifact(extra, io.BytesIO(b"-- Unreferenced input\n")))
    revision = ModelRevision(
        model=ModelRef(session_id=request.session_id, revision_id=RevisionId.new()),
        inputs=parent.inputs.model_copy(
            update={"artifacts": (*parent.inputs.artifacts, extra.ref.artifact_id)}
        ),
        coordinates=parent.coordinates,
        unit_system=parent.unit_system,
        parent=parent.model,
    )
    value(store.save_revision(revision))
    before = value(store.list_artifacts(request.session_id))
    with pytest.raises(ContractError, match="include graph"):
        with service.materialize(revision.model):
            pytest.fail("An invalid stored graph cannot yield materialized files.")
    assert value(store.list_artifacts(request.session_id)) == before


def test_materialization_preserves_consumer_oserror(tmp_path: Path) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    service = OpmImportService(store)
    model = value(service.import_model(request_for(store, tmp_path))).prepared.revision.model
    failure = OSError("The consumer failed after native work.")
    with pytest.raises(OSError) as caught:
        with service.materialize(model) as materialized:
            raise failure
    assert caught.value is failure
    assert not materialized.directory.exists()


def test_materialization_preserves_unknown_with_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    service = OpmImportService(store)
    model = value(service.import_model(request_for(store, tmp_path))).prepared.revision.model
    failure = ContractError(
        Error(
            code=ErrorCode.STORAGE_FAILED,
            message="Consumer publication failed.",
            effect=MutationEffect.UNKNOWN,
        )
    )
    cleanup = TemporaryDirectory.cleanup

    def fail_cleanup(directory: TemporaryDirectory[str]) -> None:
        cleanup(directory)
        raise OSError("Injected staging cleanup failure.")

    with pytest.raises(ContractError) as caught:
        with service.materialize(model):
            monkeypatch.setattr(TemporaryDirectory, "cleanup", fail_cleanup)
            raise failure
    assert caught.value is failure
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert "Injected staging cleanup failure." in " ".join(caught.value.__notes__)


def test_materialization_cleanup_failure_after_consumer_reports_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    service = OpmImportService(store)
    model = value(service.import_model(request_for(store, tmp_path))).prepared.revision.model
    cleanup = TemporaryDirectory.cleanup

    def fail_cleanup(directory: TemporaryDirectory[str]) -> None:
        cleanup(directory)
        raise OSError("Injected staging cleanup failure.")

    with pytest.raises(ContractError) as caught:
        with service.materialize(model):
            monkeypatch.setattr(TemporaryDirectory, "cleanup", fail_cleanup)
    assert caught.value.error.code == ErrorCode.STORAGE_FAILED
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert "Injected staging cleanup failure." in caught.value.error.message


def test_materialization_cleanup_failure_inside_unrelated_exception_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    service = OpmImportService(store)
    model = value(service.import_model(request_for(store, tmp_path))).prepared.revision.model
    cleanup = TemporaryDirectory.cleanup
    unrelated = ValueError("An unrelated operation failed.")

    def fail_cleanup(directory: TemporaryDirectory[str]) -> None:
        cleanup(directory)
        raise OSError("Injected recovery cleanup failure.")

    try:
        raise unrelated
    except ValueError:
        with pytest.raises(ContractError) as caught:
            with service.materialize(model):
                monkeypatch.setattr(TemporaryDirectory, "cleanup", fail_cleanup)
    assert caught.value.error.code == ErrorCode.STORAGE_FAILED
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert "Injected recovery cleanup failure." in caught.value.error.message
    assert not hasattr(unrelated, "__notes__")
