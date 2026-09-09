"""Restore fixed model bindings without reusing a previous native lifetime."""

from dataclasses import replace
from pathlib import Path

import pytest
from sessions._support import error, value

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.contracts.identifiers import RevisionId
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    CloseRequest,
    ObjectKind,
    ProjectSaveRequest,
)
from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.models.wells.records import (
    PreparedCaseRequest,
    PreparedCaseRestoreRequest,
    WellAdoptRequest,
    WellCreateRequest,
    WellExportRequest,
    WellUpdateRequest,
)
from resinsight_mcp.resinsight.wells import ResInsightWellService

from ._support import Harness, harness

__all__ = ["harness"]


def reopened_service(harness: Harness) -> ResInsightWellService:
    assert harness.backend.loaded is not None
    return ResInsightWellService(
        harness.store,
        harness.sessions,
        OpmImportService(harness.store),
        harness.backend,
        source_root=harness.backend.loaded.directory.parents[2],
    )


def test_reconnect_restores_case_and_adopts_well_with_fresh_version(harness: Harness) -> None:
    created = harness.create()
    exported = value(
        harness.service.export(WellExportRequest(well=created.well, expected_version=0))
    )
    value(harness.service.close())
    value(
        harness.sessions.close(
            CloseRequest(
                session_id=created.well.context.session_id,
                connection_id=created.well.context.connection_id,
            )
        )
    )
    connection = value(
        harness.sessions.attach(
            AttachRequest(
                session_id=created.well.context.session_id,
                endpoint=harness.backend.application.endpoint,
            )
        )
    )
    service = reopened_service(harness)
    project = value(harness.sessions.inspect_project(connection.context.session_id))
    case = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.CASE)
    well = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.WELL)
    restored = value(
        service.restore_case(
            PreparedCaseRestoreRequest(
                model=created.binding.model, case=case, receipt=created.binding.receipt
            )
        )
    )
    assert error(service.inspect(created.well)).code == ErrorCode.STALE_OBJECT
    assert error(service.inspect(well)).code == ErrorCode.STALE_OBJECT
    mutations = harness.backend.mutations
    adopted = value(
        service.adopt_well(
            WellAdoptRequest(
                binding=restored,
                well=well,
                definition=created.definition,
                trajectory=created.trajectory,
            )
        )
    )
    assert adopted.version == 0
    assert adopted.well.context.project_generation > well.context.project_generation
    assert adopted.well.context.connection_id != created.well.context.connection_id
    assert adopted.trajectory == created.trajectory
    assert harness.backend.mutations == mutations
    assert value(service.get_export(exported.artifact)) == exported
    repeated = value(service.export(WellExportRequest(well=adopted.well, expected_version=0)))
    assert repeated.connections == exported.connections
    assert error(service.inspect(well)).code == ErrorCode.STALE_OBJECT
    service.close()


def test_adoption_retires_the_old_version_zero_reference(harness: Harness) -> None:
    created = harness.create()
    adopted = value(
        harness.service.adopt_well(
            WellAdoptRequest(
                binding=created.binding,
                well=created.well,
                definition=created.definition,
                trajectory=created.trajectory,
            )
        )
    )
    assert adopted.version == created.version == 0
    rejected = harness.service.update(
        WellUpdateRequest(
            well=created.well, expected_version=0, definition=harness.definition(end=8450.0)
        )
    )
    assert error(rejected).code == ErrorCode.STALE_OBJECT
    assert value(harness.service.inspect(adopted.well)) == adopted


@pytest.mark.parametrize("save_first", [False, True])
def test_restoring_a_case_requires_explicit_well_adoption(
    harness: Harness, tmp_path: Path, save_first: bool
) -> None:
    created = harness.create()
    if save_first:
        value(
            harness.sessions.save_project(
                ProjectSaveRequest(context=created.well.context, path=tmp_path / "project.rsp")
            )
        )
    project = value(harness.sessions.inspect_project(created.binding.model.session_id))
    case = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.CASE)
    well = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.WELL)
    restored = value(
        harness.service.restore_case(
            PreparedCaseRestoreRequest(
                model=created.binding.model, case=case, receipt=created.binding.receipt
            )
        )
    )
    assert error(harness.service.inspect(well)).code == ErrorCode.STALE_OBJECT
    adopted = value(
        harness.service.adopt_well(
            WellAdoptRequest(
                binding=restored,
                well=well,
                definition=created.definition,
                trajectory=created.trajectory,
            )
        )
    )
    assert adopted.version == 0


@pytest.mark.parametrize("change", ["definition", "trajectory", "case"])
def test_adoption_rejects_changed_native_data(harness: Harness, change: str) -> None:
    created = harness.create()
    native = harness.backend.wells["well-PROD"]
    if change == "definition":
        harness.backend.wells["well-PROD"] = replace(
            native, definition=harness.definition(end=8450.0)
        )
    elif change == "trajectory":
        harness.backend.wells["well-PROD"] = replace(
            native,
            trajectory=(
                native.trajectory[0],
                native.trajectory[-1].model_copy(update={"measured_depth_ft": 8431.0}),
            ),
        )
    else:
        harness.backend.changed_case = True
    before = value(harness.sessions.inspect_project(created.binding.model.session_id))
    rejected = harness.service.adopt_well(
        WellAdoptRequest(
            binding=created.binding,
            well=created.well,
            definition=created.definition,
            trajectory=created.trajectory,
        )
    )
    assert error(rejected).code == ErrorCode.STALE_OBJECT
    assert value(harness.sessions.inspect_project(created.binding.model.session_id)) == before


def test_restore_rejects_changed_case_and_wrong_model_receipt(harness: Harness) -> None:
    service = reopened_service(harness)
    request = PreparedCaseRestoreRequest(**harness.binding.model_dump())
    harness.backend.changed_case = True
    assert error(service.restore_case(request)).code == ErrorCode.STALE_OBJECT
    harness.backend.changed_case = False
    cloned = value(harness.store.clone_revision(request.model, RevisionId.new()))
    wrong = request.model_copy(update={"model": cloned.model})
    assert error(service.restore_case(wrong)).code == ErrorCode.STALE_OBJECT
    assert value(service.restore_case(request)).receipt == harness.binding.receipt
    service.close()


def test_clone_can_explicitly_adopt_an_existing_well_name(harness: Harness) -> None:
    created = harness.create()
    cloned = value(harness.store.clone_revision(created.binding.model, RevisionId.new()))
    binding = value(
        harness.service.load(PreparedCaseRequest(context=created.well.context, model=cloned.model))
    )
    project = value(harness.sessions.inspect_project(binding.model.session_id))
    case = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.CASE)
    binding = value(
        harness.service.restore_case(
            PreparedCaseRestoreRequest(model=cloned.model, case=case, receipt=binding.receipt)
        )
    )
    well = next(item.ref for item in project.objects if item.ref.kind == ObjectKind.WELL)
    duplicate = harness.service.create(
        WellCreateRequest(binding=binding, definition=created.definition)
    )
    assert error(duplicate).code == ErrorCode.CONFLICT
    adopted = value(
        harness.service.adopt_well(
            WellAdoptRequest(
                binding=binding,
                well=well,
                definition=created.definition,
                trajectory=created.trajectory,
            )
        )
    )
    assert adopted.binding.model == cloned.model
    assert adopted.version == 0
    assert error(harness.service.inspect(created.well)).code == ErrorCode.STALE_OBJECT


@pytest.mark.parametrize("redirected", [False, True])
def test_source_root_requires_an_explicit_canonical_path(
    harness: Harness, tmp_path: Path, redirected: bool
) -> None:
    root = Path("relative-native-sources")
    if redirected:
        root = tmp_path / "redirected"
        root.symlink_to(tmp_path / "actual", target_is_directory=True)
    with pytest.raises(ContractError, match="absolute canonical"):
        ResInsightWellService(
            harness.store,
            harness.sessions,
            OpmImportService(harness.store),
            harness.backend,
            source_root=root,
        )
    assert not (tmp_path / "actual").exists()
