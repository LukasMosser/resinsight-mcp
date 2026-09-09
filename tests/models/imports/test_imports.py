"""Import real OPM inputs and reject unsupported models before saving files."""

import json
import shutil
from pathlib import Path

import pytest

from resinsight_mcp.contracts.engineering import CellIndex, ModelRef
from resinsight_mcp.contracts.errors import (
    ContractError,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import RevisionId, SessionId
from resinsight_mcp.contracts.interfaces import ModelPreparer
from resinsight_mcp.contracts.models import Backend, PreparationRequest, Session
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.models.imports import DerivedModelRequest, ImportRequest, OpmImportService
from resinsight_mcp.models.imports.records import ImportRecord, ModelSummary
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


def test_persistent_sources_reopen_through_a_new_store(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tmp_path: Path
) -> None:
    service = OpmImportService(store)
    model = value(service.import_model(request_model)).prepared.revision.model
    directory = tmp_path / "persistent"
    first = service.materialize_persistent(model, directory)
    shutil.rmtree(request_model.source_root)
    reopened = OpmImportService(SqliteWorkspaceStore.open(tmp_path / "workspace"))
    actual = reopened.reopen_persistent(model, directory)
    assert actual == first
    assert actual.inspection.active_cells[0] == CellIndex(i=0, j=0, k=0)
    assert actual.inspection.properties.permx_millidarcy[0] == pytest.approx(500.0, rel=1e-12)


@pytest.mark.parametrize("change", ["property", "control", "source-link"])
def test_persistent_sources_reject_changed_values_and_redirected_files(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tmp_path: Path, change: str
) -> None:
    service = OpmImportService(store)
    model = value(service.import_model(request_model)).prepared.revision.model
    directory = tmp_path / "persistent"
    materialized = service.materialize_persistent(model, directory)
    if change == "property":
        path = materialized.directory / "includes" / "grid.inc"
        path.write_text(path.read_text().replace("500", "501"))
    elif change == "control":
        path = materialized.directory / "includes" / "schedule.inc"
        path.write_text(path.read_text().replace("20000", "20001"))
    else:
        path = materialized.directory / "includes" / "props.inc"
        moved = tmp_path / "moved-properties.inc"
        path.rename(moved)
        path.symlink_to(moved)
    with pytest.raises(ContractError, match="persistent|Persistent"):
        service.reopen_persistent(model, directory)


@pytest.mark.parametrize("kind", ["relative", "existing", "linked-parent"])
def test_persistent_materialization_rejects_invalid_destinations_before_writes(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tmp_path: Path, kind: str
) -> None:
    service = OpmImportService(store)
    model = value(service.import_model(request_model)).prepared.revision.model
    actual = tmp_path / "actual"
    actual.mkdir()
    if kind == "relative":
        destination = Path("relative-model-directory")
    elif kind == "existing":
        destination = actual
    else:
        linked = tmp_path / "linked"
        linked.symlink_to(actual, target_is_directory=True)
        destination = linked / "new-model"
    with pytest.raises(ContractError):
        service.materialize_persistent(model, destination)
    assert list(actual.iterdir()) == []


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
        ("includes/schedule.inc", "20000 4* 1000", "20000 -100 3* 1000"),
        ("includes/schedule.inc", "1 1 /", "0 1 /"),
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


def test_unclosed_include_quotes_return_a_clear_failure(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    replace(request_model.source_root, "SPE1.DATA", "'includes/grid.inc' /", '"broken /')
    assert "quotes" in rejected(store, request_model)


def test_open_well_with_shut_completion_is_rejected_before_opm_can_close_it(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    replace(
        request_model.source_root,
        "includes/schedule.inc",
        "'PROD' 10 10 3 3 'OPEN'",
        "'PROD' 10 10 3 3 'SHUT'",
    )
    assert "OPEN completions" in rejected(store, request_model)


def test_materialization_inspects_stored_field_geometry_and_cleans_staging(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    import opm.io.deck  # noqa: F401
    from opm.io.parser import Parser

    service = OpmImportService(store)
    receipt = value(service.import_model(request_model))
    shutil.rmtree(request_model.source_root)
    with service.materialize(receipt.prepared.revision.model) as materialized:
        inspection = materialized.inspection
        assert materialized.revision == receipt.prepared.revision
        assert inspection.summary.support_profile == "spe1-field-v2"
        assert inspection.active_cells[0] == CellIndex(i=0, j=0, k=0)
        assert inspection.active_cells[10] == CellIndex(i=0, j=1, k=0)
        assert inspection.active_cells[100] == CellIndex(i=0, j=0, k=1)
        assert inspection.active_cells[-1] == CellIndex(i=9, j=9, k=2)
        assert inspection.cell_depths_ft[0] == pytest.approx(8335.0)
        assert inspection.cell_volumes_ft3[0] == pytest.approx(20_000_000.0)
        assert inspection.properties.dx_ft[0] == pytest.approx(1000.0)
        assert inspection.properties.permx_millidarcy[0] == pytest.approx(500.0)
        assert inspection.report_elapsed_days == (0.0, 1.0, 2.0)
        property_deck = Parser().parse(str(materialized.property_file))
        for keyword, values in inspection.properties.keyword_arrays():
            assert list(property_deck[keyword].get_raw_array()) == pytest.approx(values)
        with service.materialize(receipt.prepared.revision.model) as second:
            assert materialized.directory != second.directory
            materialized.entrypoint.write_text("Invalid staged input")
            assert "RUNSPEC" in second.entrypoint.read_text()
    assert not materialized.directory.exists()
    assert not materialized.property_file.exists()
    assert not second.directory.exists()
    assert (
        value(
            service.prepare(
                PreparationRequest(revision=receipt.prepared.revision, backend=Backend.OPM_FLOW)
            )
        )
        == receipt.prepared
    )


def test_materialize_rejects_missing_revision_before_yield(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    missing = ModelRef(session_id=request_model.session_id, revision_id=RevisionId.new())
    with pytest.raises(ContractError) as failure:
        with OpmImportService(store).materialize(missing):
            pytest.fail("A missing revision cannot yield staged inputs.")
    assert failure.value.error.code == ErrorCode.NOT_FOUND


def test_derived_revision_inherits_identity_and_preserves_parent_inputs(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tmp_path: Path
) -> None:
    service = OpmImportService(store)
    parent = value(service.import_model(request_model)).prepared.revision
    with service.materialize(parent.model) as materialized:
        candidate = Path(shutil.copytree(materialized.directory, tmp_path / "changed"))
    replace(candidate, "includes/schedule.inc", "20000 4* 1000", "10000 4* 1000")
    child = value(
        service.derive_model(
            DerivedModelRequest(parent=parent.model, source_root=candidate, entrypoint="SPE1.DATA")
        )
    ).prepared.revision
    assert child.parent == parent.model
    assert child.model.session_id == parent.model.session_id
    assert child.model != parent.model
    assert child.coordinates == parent.coordinates
    assert child.unit_system == parent.unit_system
    with service.materialize(parent.model) as original, service.materialize(child.model) as changed:
        assert "20000 4* 1000" in (original.directory / "includes/schedule.inc").read_text()
        assert "10000 4* 1000" in (changed.directory / "includes/schedule.inc").read_text()
    assert value(store.get_revision(parent.model)) == parent


def test_derived_invalid_input_does_not_publish_artifacts(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    service = OpmImportService(store)
    parent = value(service.import_model(request_model)).prepared.revision
    before = value(store.list_artifacts(parent.model.session_id))
    replace(request_model.source_root, "SPE1.DATA", "FIELD", "METRIC")
    result = service.derive_model(
        DerivedModelRequest(
            parent=parent.model,
            source_root=request_model.source_root,
            entrypoint=request_model.entrypoint,
        )
    )
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.INVALID_MODEL
    assert value(store.list_artifacts(parent.model.session_id)) == before
    assert value(store.get_revision(parent.model)) == parent


def test_explicit_connection_fields_use_current_profile_and_opm_units(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import Parser
    from opm.io.schedule import Schedule

    replace(
        request_model.source_root,
        "includes/schedule.inc",
        "'OPEN' 1* 1* 0.5",
        "'OPEN' 1* 10.07878 0.5 9500 0 1* 'Z'",
    )
    service = OpmImportService(store)
    receipt = value(service.import_model(request_model))
    assert receipt.summary.support_profile == "spe1-field-v2"
    with service.materialize(receipt.prepared.revision.model) as materialized:
        deck = Parser().parse(str(materialized.entrypoint))
        schedule = Schedule(deck, EclipseState(deck))
        connection = schedule.get_wells(0)[0].connections()[0]
        items = {item.name(): item for item in deck["COMPDAT"][0]}
        assert connection.cf == pytest.approx(items["CONNECTION_TRANSMISSIBILITY_FACTOR"].get_SI(0))
        assert connection.kh == pytest.approx(items["Kh"].get_SI(0))
        assert connection.pos == (9, 9, 2)
    prior = ModelSummary.model_validate(
        {**receipt.summary.model_dump(), "support_profile": "spe1-field-v1"}
    )
    assert prior.support_profile == "spe1-field-v1"


@pytest.mark.parametrize(
    "tail",
    [
        "-1 0.5 9500 0 1* 'Z'",
        "0 0.5 9500 0 1* 'Z'",
        "1e999 0.5 9500 0 1* 'Z'",
        "10 0.5 -1 0 1* 'Z'",
        "10 0.5 0 0 1* 'Z'",
        "10 0.5 1e999 0 1* 'Z'",
        "10 0.5 9500 -1 1* 'Z'",
        "10 0.5 9500 1e999 1* 'Z'",
        "10 0.5 9500 0 1* 'A'",
    ],
)
def test_invalid_explicit_connection_fields_are_rejected(
    store: SqliteWorkspaceStore, request_model: ImportRequest, tail: str
) -> None:
    replace(
        request_model.source_root, "includes/schedule.inc", "'OPEN' 1* 1* 0.5", "'OPEN' 1* " + tail
    )
    rejected(store, request_model)


@pytest.mark.parametrize("cells", ["10 10 2 4", "0 10 3 3", "10 10 3 2"])
def test_completion_cannot_partly_overlap_or_default_outside_the_grid(
    store: SqliteWorkspaceStore, request_model: ImportRequest, cells: str
) -> None:
    replace(
        request_model.source_root, "includes/schedule.inc", "'PROD' 10 10 3 3", "'PROD' " + cells
    )
    assert "active cells" in rejected(store, request_model)


def test_inactive_cell_deck_remains_outside_the_supported_profile(
    store: SqliteWorkspaceStore, request_model: ImportRequest
) -> None:
    replace(request_model.source_root, "includes/grid.inc", "GRID", "GRID\nACTNUM\n 299*1 0 /\n")
    assert "Unsupported keywords: ACTNUM" in rejected(store, request_model)
