"""Import real OPM inputs and reject unsupported models before saving files."""

import json
import shutil
from pathlib import Path

import pytest

from resinsight_mcp.contracts.errors import ErrorCode, Failure, OperationResult, Success
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.interfaces import ModelPreparer
from resinsight_mcp.contracts.models import Backend, PreparationRequest, Session
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.models.imports.records import ImportRecord
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result
    return result.outcome.value


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return Path(shutil.copytree(Path(__file__).parent / "data" / "spe1", tmp_path / "source"))


@pytest.fixture
def store(tmp_path: Path) -> SqliteWorkspaceStore:
    return SqliteWorkspaceStore.create(tmp_path / "workspace")


@pytest.fixture
def request_model(store: SqliteWorkspaceStore, source: Path) -> ImportRequest:
    session = value(store.create_session(Session(session_id=SessionId.new(), name="SPE1")))
    return ImportRequest(
        session_id=session.session_id,
        source_root=source,
        entrypoint="SPE1.DATA",
        datum="SPE1 local datum",
    )


def replace(source: Path, name: str, old: str, new: str) -> None:
    path = source / name
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def rejected(store: SqliteWorkspaceStore, request: ImportRequest) -> str:
    result = OpmImportService(store).import_model(request)
    assert isinstance(result.outcome, Failure), result
    assert result.outcome.error.code == ErrorCode.INVALID_MODEL
    assert result.outcome.error.message
    assert value(store.list_artifacts(request.session_id)) == ()
    assert value(store.list_jobs(request.session_id)) == ()
    return result.outcome.error.message


@pytest.mark.parametrize("source_change", ["modify", "remove"])
def test_import_preserves_lineage_and_prepares_stored_inputs_after_reopen(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tmp_path: Path, source_change: str
) -> None:
    receipt = value(OpmImportService(store).import_model(request_model))
    assert receipt.summary.dimensions == (10, 10, 3)
    assert receipt.summary.active_cells == 300
    assert receipt.summary.wells == ("PROD", "INJ")
    assert receipt.summary.report_steps == 2
    assert receipt.summary.elapsed_days == 2.0
    assert receipt.summary.unit_system == "FIELD"
    revision = receipt.prepared.revision
    assert revision.coordinates.datum == "SPE1 local datum"
    with store.open_artifact(receipt.record) as stream:
        record = ImportRecord.model_validate(json.load(stream))
    assert record.model == revision.model
    assert record.summary == receipt.summary
    assert record.changes == ()
    assert record.source_entrypoint == "SPE1.DATA"
    assert set(record.sources) == {
        "SPE1.DATA",
        "includes/grid.inc",
        "includes/props.inc",
        "includes/regions.inc",
        "includes/schedule.inc",
    }
    assert {(edge.source, edge.target) for edge in record.includes} == {
        ("SPE1.DATA", name) for name in record.sources if name != "SPE1.DATA"
    }
    assert set(revision.inputs.artifacts) == {ref.artifact_id for ref in record.sources.values()}
    assert revision.inputs.entrypoint == record.sources["SPE1.DATA"].artifact_id
    assert receipt.record.artifact_id not in revision.inputs.artifacts
    for name, ref in record.sources.items():
        assert value(store.get_artifact(ref)).kind == ArtifactKind.INPUT
        with store.open_artifact(ref) as stream:
            assert (
                stream.read().decode().splitlines()
                == (request_model.source_root / name).read_text().splitlines()
            )
    if source_change == "remove":
        shutil.rmtree(request_model.source_root)
    else:
        replace(request_model.source_root, "SPE1.DATA", "FIELD", "METRIC")
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert value(reopened.get_revision(revision.model)) == revision
    preparer: ModelPreparer = OpmImportService(reopened)
    assert (
        value(preparer.prepare(PreparationRequest(revision=revision, backend=Backend.OPM_FLOW)))
        == receipt.prepared
    )
    assert value(reopened.list_jobs(request_model.session_id)) == ()
    altered = revision.model_copy(
        update={"coordinates": revision.coordinates.model_copy(update={"datum": "Changed datum"})}
    )
    outcome = preparer.prepare(PreparationRequest(revision=altered, backend=Backend.OPM_FLOW))
    assert isinstance(outcome.outcome, Failure)
    assert value(reopened.get_revision(revision.model)) == revision


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("SPE1.DATA", "FIELD", "FIELD\nMETRIC"),
        ("SPE1.DATA", "DISGAS", "DISGAS\nVAPOIL"),
        ("SPE1.DATA", "UNIFOUT", "UNIFOUT\nNOTAKEYWORD"),
        ("SPE1.DATA", "10 10 3 /", "0 10 3 /"),
        ("SPE1.DATA", "10 10 3 /", "ten 10 3 /"),
        ("includes/schedule.inc", "20000 4* 1000", "1* 4* 1000"),
        ("includes/schedule.inc", "20000 4* 1000", "20000 5*"),
        ("includes/schedule.inc", "100000 1* 9014", "1* 1* 9014"),
        ("includes/schedule.inc", "100000 1* 9014", "100000 2*"),
        ("includes/schedule.inc", "WCONPROD\n 'PROD' 'OPEN' 'ORAT' 20000 4* 1000 /\n/", ""),
        ("includes/schedule.inc", "'PROD' 10 10 3 3", "'PROD' 10 10 4 4"),
    ],
)
def test_invalid_model_leaves_no_saved_artifacts_or_jobs(
    store: SqliteWorkspaceStore,
    request_model: ImportRequest,
    name: str,
    old: str,
    new: str,
) -> None:
    replace(request_model.source_root, name, old, new)
    rejected(store, request_model)


def test_nested_includes_use_source_root_and_preserve_empty_files(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    source = request_model.source_root
    replace(source, "SPE1.DATA", "'includes/grid.inc'", "'includes/wrapper.inc'")
    (source / "includes/wrapper.inc").write_text(
        "INCLUDE\n 'empty.inc' /\nINCLUDE\n 'includes/grid.inc' /\n"
    )
    (source / "empty.inc").write_text("")
    receipt = value(OpmImportService(store).import_model(request_model))
    with store.open_artifact(receipt.record) as stream:
        record = ImportRecord.model_validate(json.load(stream))
    assert ("includes/wrapper.inc", "includes/grid.inc") in {
        (edge.source, edge.target) for edge in record.includes
    }
    with store.open_artifact(record.sources["empty.inc"]) as stream:
        assert stream.read().decode() == ""
    assert receipt.summary.active_cells == 300


@pytest.mark.parametrize("kind", ["missing", "cycle", "traversal", "absolute", "symlink"])
def test_unsafe_include_graph_is_rejected(
    store: SqliteWorkspaceStore, request_model: ImportRequest, kind: str, tmp_path: Path
) -> None:
    source = request_model.source_root
    target = "missing.inc"
    if kind == "cycle":
        target = "SPE1.DATA"
    elif kind in {"absolute", "traversal", "symlink"}:
        outside = tmp_path / "outside.inc"
        outside.write_text("-- External file\n")
        target = str(outside) if kind == "absolute" else "../outside.inc"
        if kind == "symlink":
            (source / "link.inc").symlink_to(outside)
            target = "link.inc"
    replace(source, "SPE1.DATA", "'includes/grid.inc'", f"'{target}'")
    rejected(store, request_model)


@pytest.mark.parametrize("directive", ["END", "ENDINC", "SKIP", "SKIP100", "SKIP300", "ENDSKIP"])
def test_consumed_parser_directives_are_rejected(
    store: SqliteWorkspaceStore, request_model: ImportRequest, directive: str
) -> None:
    replace(request_model.source_root, "SPE1.DATA", "RUNSPEC", f"{directive}\nRUNSPEC")
    rejected(store, request_model)


def test_comma_include_cannot_bypass_source_collection(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    replace(request_model.source_root, "SPE1.DATA", "INCLUDE", ",INCLUDE")
    rejected(store, request_model)


def test_repeated_include_expansion_is_bounded(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    source = request_model.source_root
    replace(source, "SPE1.DATA", "'includes/grid.inc'", "'level0.inc'")
    for level in range(9):
        (source / f"level{level}.inc").write_text(f"INCLUDE\n 'level{level + 1}.inc' /\n" * 2)
    (source / "level9.inc").write_text("")
    assert "Expanded includes" in rejected(store, request_model)
