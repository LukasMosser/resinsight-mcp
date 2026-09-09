"""Public well operations preserve ownership, staged inputs, and export provenance."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from threading import Event

import pytest
from sessions._support import error, value

from resinsight_mcp.contracts.errors import ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ConnectionState
from resinsight_mcp.models.imports import MaterializedModel
from resinsight_mcp.models.wells.records import (
    ModeledWellDefinition,
    PreparedCaseRequest,
    WellCreateRequest,
    WellExportRequest,
    WellUpdateRequest,
)
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.wells._backend import NativeWell

from ._support import Harness, harness

__all__ = ["harness"]


def test_create_update_and_export_preserve_fixed_model_and_snapshot(harness: Harness) -> None:
    created = harness.create()
    assert created.binding.model == harness.binding.model
    assert created.well.context.project_generation > harness.binding.case.context.project_generation
    assert created.trajectory[-1].depth_ft == 8430.0
    exported = value(
        harness.service.export(WellExportRequest(well=created.well, expected_version=0))
    )
    assert exported.modeled_well == created
    updated = value(
        harness.service.update(
            WellUpdateRequest(
                well=created.well, expected_version=0, definition=harness.definition(end=8450.0)
            )
        )
    )
    assert updated.version == 1 and updated.trajectory[-1].depth_ft == 8450.0
    assert value(harness.service.get_export(exported.artifact)) == exported
    assert error(harness.service.inspect(created.well)).code == ErrorCode.STALE_OBJECT
    assert value(harness.service.inspect(updated.well)) == updated
    assert harness.backend.checks >= 4


def test_another_created_well_can_be_inspected_through_fresh_project_reference(
    harness: Harness,
) -> None:
    first = harness.create()
    second = value(
        harness.service.create(
            WellCreateRequest(binding=first.binding, definition=harness.definition(name="INJ"))
        )
    )
    project = value(harness.sessions.inspect_project(first.binding.model.session_id))
    fresh = next(item.ref for item in project.objects if item.name == "PROD")
    inspected = value(harness.service.inspect(fresh))
    assert inspected.version == first.version
    assert inspected.definition == first.definition
    assert inspected.binding.case.context == second.well.context


def test_invalid_name_and_changed_case_reject_before_native_mutation(harness: Harness) -> None:
    before = harness.backend.mutations
    rejected = harness.service.create(
        WellCreateRequest(binding=harness.binding, definition=harness.definition(name="MISSING"))
    )
    assert error(rejected).code == ErrorCode.INVALID_MODEL
    harness.backend.changed_case = True
    rejected = harness.service.create(
        WellCreateRequest(binding=harness.binding, definition=harness.definition())
    )
    assert error(rejected).code == ErrorCode.STALE_OBJECT
    assert error(rejected).effect == MutationEffect.NOT_APPLIED
    assert harness.backend.mutations == before


def test_reversed_native_depth_does_not_return_a_successful_well(harness: Harness) -> None:
    harness.backend.reverse_depth = True
    rejected = harness.service.create(
        WellCreateRequest(binding=harness.binding, definition=harness.definition())
    )
    assert error(rejected).effect == MutationEffect.UNKNOWN
    assert "positive-down" in error(rejected).message
    assert (
        value(harness.sessions.get_connection(harness.binding.model.session_id)).state
        == ConnectionState.LOST
    )


def test_invalid_completion_does_not_publish_an_export(harness: Harness) -> None:
    created = harness.create()
    before = value(harness.store.list_artifacts(created.binding.model.session_id))
    harness.backend.invalid_cell = True
    rejected = harness.service.export(
        WellExportRequest(well=created.well, expected_version=created.version)
    )
    assert error(rejected).code == ErrorCode.INVALID_MODEL
    assert error(rejected).effect == MutationEffect.NOT_APPLIED
    assert value(harness.store.list_artifacts(created.binding.model.session_id)) == before


def test_changed_native_well_and_stale_version_reject(harness: Harness) -> None:
    created = harness.create()
    assert (
        error(harness.service.export(WellExportRequest(well=created.well, expected_version=1))).code
        == ErrorCode.STALE_OBJECT
    )
    native = harness.backend.wells["well-PROD"]
    harness.backend.wells["well-PROD"] = replace(native, definition=harness.definition(end=8500.0))
    assert (
        error(harness.service.export(WellExportRequest(well=created.well, expected_version=0))).code
        == ErrorCode.STALE_OBJECT
    )


def test_unknown_native_update_stays_unknown(harness: Harness) -> None:
    created = harness.create()
    harness.backend.unknown_update = True
    rejected = harness.service.update(
        WellUpdateRequest(
            well=created.well, expected_version=0, definition=harness.definition(end=8450.0)
        )
    )
    assert error(rejected).effect == MutationEffect.UNKNOWN
    assert error(rejected).code == ErrorCode.LOST_CONNECTION


def test_unknown_export_artifact_is_not_trusted(harness: Harness) -> None:
    reference = ArtifactRef(
        session_id=harness.binding.model.session_id, artifact_id=ArtifactId.new()
    )
    assert error(harness.service.get_export(reference)).code == ErrorCode.NOT_FOUND


def test_persistent_sources_survive_explicit_service_close(harness: Harness) -> None:
    assert harness.backend.loaded is not None
    materialized = harness.backend.loaded
    assert materialized.entrypoint.is_file() and materialized.property_file.is_file()
    value(harness.service.close())
    assert materialized.directory.exists()
    assert materialized.property_file.exists()
    rejected = harness.service.create(
        WellCreateRequest(binding=harness.binding, definition=harness.definition())
    )
    assert error(rejected).code == ErrorCode.STALE_OBJECT


def test_service_close_is_idempotent(harness: Harness) -> None:
    closed = harness.service.close()
    value(closed)
    assert harness.service.close() == closed


def test_export_with_another_artifact_identity_is_not_trusted(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    from contextlib import contextmanager

    created = harness.create()
    exported = value(
        harness.service.export(WellExportRequest(well=created.well, expected_version=0))
    )
    changed = exported.model_copy(
        update={
            "artifact": ArtifactRef(
                session_id=exported.artifact.session_id, artifact_id=ArtifactId.new()
            )
        }
    )

    @contextmanager
    def changed_content(reference: ArtifactRef):
        assert reference == exported.artifact
        yield io.BytesIO(changed.model_dump_json().encode("utf-8"))

    monkeypatch.setattr(harness.store, "open_artifact", changed_content)
    assert error(harness.service.get_export(exported.artifact)).code == ErrorCode.STALE_OBJECT


def test_missing_created_address_retires_the_connection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = harness.backend.create

    def missing_address(
        access: ApplicationAccess, address: str, definition: ModeledWellDefinition
    ) -> NativeWell:
        return replace(original(access, address, definition), address="absent")

    monkeypatch.setattr(harness.backend, "create", missing_address)
    rejected = harness.service.create(
        WellCreateRequest(binding=harness.binding, definition=harness.definition())
    )
    assert error(rejected).effect == MutationEffect.UNKNOWN
    assert (
        value(harness.sessions.get_connection(harness.binding.model.session_id)).state
        == ConnectionState.LOST
    )


def test_missing_loaded_address_retires_the_connection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = harness.backend.load

    def missing_address(access: ApplicationAccess, materialized: MaterializedModel) -> str:
        original(access, materialized)
        return "absent"

    monkeypatch.setattr(harness.backend, "load", missing_address)
    rejected = harness.service.load(
        PreparedCaseRequest(context=harness.binding.case.context, model=harness.binding.model)
    )
    assert error(rejected).effect == MutationEffect.UNKNOWN
    assert (
        value(harness.sessions.get_connection(harness.binding.model.session_id)).state
        == ConnectionState.LOST
    )


def test_close_waits_for_native_load_and_rejects_new_work(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = Event(), Event()
    original = harness.backend.load
    staged: list[MaterializedModel] = []

    def blocked_load(access: ApplicationAccess, materialized: MaterializedModel) -> str:
        staged.append(materialized)
        entered.set()
        assert release.wait(5), "The test did not release native loading."
        assert materialized.entrypoint.is_file() and materialized.property_file.is_file()
        return original(access, materialized)

    monkeypatch.setattr(harness.backend, "load", blocked_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        loading = executor.submit(
            harness.service.load,
            PreparedCaseRequest(context=harness.binding.case.context, model=harness.binding.model),
        )
        try:
            assert entered.wait(5), "The native load did not begin."
            closing = executor.submit(harness.service.close)
            with pytest.raises(TimeoutError):
                closing.result(timeout=0.2)
            assert staged[0].entrypoint.is_file() and staged[0].property_file.is_file()
            rejected = harness.service.create(
                WellCreateRequest(binding=harness.binding, definition=harness.definition())
            )
            assert "closed" in error(rejected).message
        finally:
            release.set()
        value(loading.result(timeout=5))
        value(closing.result(timeout=5))
    assert staged[0].directory.exists() and staged[0].property_file.exists()


def test_removed_case_address_cannot_reuse_an_old_reference(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from resinsight_mcp.resinsight.sessions._backend import ProjectSnapshot

    def removed_case(access: ApplicationAccess, materialized: MaterializedModel) -> str:
        harness.backend.application.project = ProjectSnapshot("root", ())
        return "prepared"

    monkeypatch.setattr(harness.backend, "load", removed_case)
    rejected = harness.service.load(
        PreparedCaseRequest(context=harness.binding.case.context, model=harness.binding.model)
    )
    assert error(rejected).effect == MutationEffect.UNKNOWN
    assert (
        value(harness.sessions.get_connection(harness.binding.model.session_id)).state
        == ConnectionState.LOST
    )
