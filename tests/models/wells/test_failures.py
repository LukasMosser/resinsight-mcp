"""Reject incompatible exports and retain honest publication failure effects."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import pytest

from resinsight_mcp.contracts.engineering import CellIndex
from resinsight_mcp.contracts.errors import (
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision
from resinsight_mcp.contracts.wells import InjectorControl, WellStatus
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.models.imports import ImportRequest
from resinsight_mcp.models.imports.records import ImportRecord
from resinsight_mcp.models.wells.records import (
    CompletionExport,
    ScheduledControl,
    ScheduledWell,
    WellScheduleRequest,
)
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .test_schedule_service import Case, case_for, completion, value


def rejected(
    case: Case, request: WellScheduleRequest, expected: str, *exports: CompletionExport
) -> None:
    before = value(case.store.list_artifacts(case.parent.model.session_id))
    result = case.service(*exports).publish(request)
    assert isinstance(result.outcome, Failure), result
    assert result.outcome.error.code == ErrorCode.INVALID_MODEL
    assert result.outcome.error.effect == MutationEffect.NOT_APPLIED
    assert expected in result.outcome.error.message
    assert value(case.store.get_revision(case.parent.model)) == case.parent
    assert value(case.store.list_artifacts(case.parent.model.session_id)) == before
    assert value(case.store.list_jobs(case.parent.model.session_id)) == ()


@pytest.mark.parametrize(
    "fault",
    ["parent", "datum", "cell", "status", "interval", "diameter", "skin", "wellhead", "name"],
)
def test_incompatible_completion_export_does_not_publish(tmp_path: Path, fault: str) -> None:
    case = case_for(tmp_path)
    export = case.export
    expected = ""
    if fault == "parent":
        binding = export.modeled_well.binding.model_copy(
            update={"model": case.parent.model.model_copy(update={"revision_id": RevisionId.new()})}
        )
        export = export.model_copy(
            update={"modeled_well": export.modeled_well.model_copy(update={"binding": binding})}
        )
        expected = "exact parent"
    elif fault == "datum":
        definition = export.modeled_well.definition.model_copy(
            update={
                "coordinates": case.parent.coordinates.model_copy(update={"datum": "Other datum"})
            }
        )
        export = export.model_copy(
            update={
                "modeled_well": export.modeled_well.model_copy(update={"definition": definition})
            }
        )
        expected = "depth datum"
    elif fault == "wellhead":
        export = export.model_copy(
            update={"wellhead": export.wellhead.model_copy(update={"i": 10})}
        )
        expected = "wellhead"
    elif fault == "name":
        export = completion(case.parent, "MISSING")
        expected = "report zero"
    else:
        changes = {
            "cell": {"cell": CellIndex(i=10, j=4, k=0)},
            "status": {"status": WellStatus.SHUT},
            "interval": {"start_md_ft": 8300.0},
            "diameter": {"diameter_ft": 0.6},
            "skin": {"skin": 1.0},
        }
        export = export.model_copy(
            update={
                "connections": (
                    export.connections[0].model_copy(update=changes[fault]),
                    *export.connections[1:],
                )
            }
        )
        expected = "active cell" if fault in {"cell", "status"} else "perforation"
    request = case.request().model_copy(
        update={"wells": (case.request().wells[0].model_copy(update={"export": export.artifact}),)}
    )
    rejected(case, request, expected, export)


def test_distinct_exports_for_same_well_are_rejected(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    other = completion(case.parent)
    request = case.request()
    request = request.model_copy(
        update={
            "wells": (
                *request.wells,
                request.wells[0].model_copy(update={"export": other.artifact}),
            )
        }
    )
    rejected(case, request, "well name", case.export, other)


def test_unissued_export_retains_source_failure_without_publication(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    request = case.request()
    unknown = ArtifactRef(session_id=case.parent.model.session_id, artifact_id=ArtifactId.new())
    request = request.model_copy(
        update={"wells": (request.wells[0].model_copy(update={"export": unknown}),)}
    )
    before = value(case.store.list_artifacts(case.parent.model.session_id))
    result = case.service().publish(request)
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.NOT_FOUND
    assert result.outcome.error.effect == MutationEffect.NOT_APPLIED
    assert value(case.store.list_artifacts(case.parent.model.session_id)) == before


@pytest.mark.parametrize("phase", ["GAS", "WATER"])
def test_role_and_injection_phase_changes_are_rejected(
    tmp_path: Path, phase: Literal["GAS", "WATER"]
) -> None:
    case = case_for(tmp_path)
    export = completion(case.parent, "PROD" if phase == "GAS" else "INJ")
    request = WellScheduleRequest(
        parent=case.parent.model,
        wells=(
            ScheduledWell(
                export=export.artifact,
                controls=(
                    ScheduledControl(
                        report_index=0,
                        control=InjectorControl(
                            status=WellStatus.OPEN,
                            phase=phase,
                            mode="BHP",
                            bhp_psia=9000.0,
                        ),
                    ),
                ),
            ),
        ),
    )
    rejected(
        case, request, "production and injection" if phase == "GAS" else "injection phase", export
    )


def test_report_index_beyond_parent_reports_is_rejected(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    rejected(case, case.request(report=3), "existing report index")


def test_parent_with_later_injection_phase_change_is_rejected(tmp_path: Path) -> None:
    case = case_for(
        tmp_path, schedule_tail="\nWCONINJE\n 'INJ' 'WATER' 'OPEN' 'BHP' 1* 1* 9014 /\n/\n"
    )
    export = completion(case.parent, "INJ")
    request = WellScheduleRequest(
        parent=case.parent.model,
        wells=(
            ScheduledWell(
                export=export.artifact,
                controls=(
                    ScheduledControl(
                        report_index=0,
                        control=InjectorControl(
                            status=WellStatus.OPEN,
                            phase="GAS",
                            mode="BHP",
                            bhp_psia=9000.0,
                        ),
                    ),
                ),
            ),
        ),
    )
    rejected(case, request, "changing phase", export)


def test_parent_with_uninitialized_fluid_table_entry_is_rejected(tmp_path: Path) -> None:
    case = case_for(tmp_path)
    path = case.source / "includes/props.inc"
    original = path.read_text()
    assert "4.648760331e-08" in original
    path.write_text(original.replace("4.648760331e-08", "1*"))
    case.parent = value(
        case.imports.import_model(
            ImportRequest(
                session_id=case.parent.model.session_id,
                source_root=case.source,
                entrypoint="SPE1.DATA",
                datum=case.parent.coordinates.datum,
            )
        )
    ).prepared.revision
    case.export = completion(case.parent)
    rejected(case, case.request(), "uninitialized")


class FailChildStore(SqliteWorkspaceStore):
    def save_revision(self, revision: ModelRevision) -> OperationResult[ModelRevision]:
        if revision.parent is not None:
            return OperationResult(
                outcome=Failure(
                    error=Error(
                        code=ErrorCode.STORAGE_FAILED,
                        message="Injected child revision failure.",
                    )
                )
            )
        return super().save_revision(revision)


def test_partial_child_publication_retains_unknown_and_parent(tmp_path: Path) -> None:
    case = case_for(tmp_path, store_type=FailChildStore)
    before = value(case.store.list_artifacts(case.parent.model.session_id))
    result = case.service().publish(case.request())
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.STORAGE_FAILED
    assert result.outcome.error.effect == MutationEffect.UNKNOWN
    assert "Injected child revision failure" in result.outcome.error.message
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    assert value(reopened.get_revision(case.parent.model)) == case.parent
    assert len(value(reopened.list_artifacts(case.parent.model.session_id))) > len(before)
    assert value(reopened.list_jobs(case.parent.model.session_id)) == ()


@pytest.mark.parametrize("during_failure", [False, True])
def test_materialization_cleanup_after_publication_retains_unknown_and_recovery_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    during_failure: bool,
) -> None:
    case = case_for(tmp_path, store_type=FailChildStore if during_failure else SqliteWorkspaceStore)
    cleanup = TemporaryDirectory.cleanup

    def fail_cleanup(directory: TemporaryDirectory[str]) -> None:
        cleanup(directory)
        if Path(directory.name).name.startswith("opm-materialize-"):
            raise OSError("Injected materialization cleanup failure.")

    with monkeypatch.context() as patch:
        patch.setattr(TemporaryDirectory, "cleanup", fail_cleanup)
        result = case.service().publish(case.request())
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.STORAGE_FAILED
    assert result.outcome.error.effect == MutationEffect.UNKNOWN
    assert "materialization cleanup failure" in result.outcome.error.message
    reopened = SqliteWorkspaceStore.open(tmp_path / "workspace")
    records = []
    for artifact in value(reopened.list_artifacts(case.parent.model.session_id)):
        if artifact.kind == ArtifactKind.LOG:
            with reopened.open_artifact(artifact.ref) as stream:
                records.append(ImportRecord.model_validate(json.load(stream)))
    child = next(record for record in records if record.model != case.parent.model)
    assert str(child.model.revision_id) in result.outcome.error.message
    assert isinstance(reopened.get_revision(child.model).outcome, Failure) == during_failure
    assert value(reopened.get_revision(case.parent.model)) == case.parent


def test_well_introduced_after_report_zero_cannot_be_replaced(tmp_path: Path) -> None:
    case = case_for(
        tmp_path,
        schedule_tail="""
WELSPECS
 'LATE' 'G1' 10 10 8400 'OIL' /
/
COMPDAT
 'LATE' 10 10 3 3 'OPEN' 2* 0.5 /
/
WCONPROD
 'LATE' 'OPEN' 'BHP' 5* 1000 /
/
TSTEP
 1 /
""",
    )
    export = completion(case.parent, "LATE")
    requested = case.request()
    request = requested.model_copy(
        update={"wells": (requested.wells[0].model_copy(update={"export": export.artifact}),)}
    )
    rejected(case, request, "report zero", export)


@pytest.mark.parametrize("field", ["start_md_ft", "end_md_ft", "diameter_ft", "skin"])
def test_native_difference_beyond_tolerance_does_not_publish(tmp_path: Path, field: str) -> None:
    case = case_for(tmp_path)
    connection = case.export.connections[0]
    perforation = case.export.modeled_well.definition.perforations[0]
    outside = {
        "start_md_ft": perforation.start_md_ft - 2e-6,
        "end_md_ft": perforation.end_md_ft + 2e-6,
        "diameter_ft": perforation.diameter_ft + 2e-6,
        "skin": perforation.skin + 2e-6,
    }
    case.export = case.export.model_copy(
        update={
            "connections": (
                connection.model_copy(update={field: outside[field]}),
                *case.export.connections[1:],
            ),
        }
    )
    rejected(case, case.request(), "perforation")
