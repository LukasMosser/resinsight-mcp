"""Trusted mutations retain session ownership until fresh references exist."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    ConnectionState,
    Endpoint,
    ObjectKind,
    ProcessIdentity,
    ProjectState,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import (
    ApplicationAccess,
    NativeObject,
    ProjectMutation,
    ProjectSnapshot,
)
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import FactoryDouble, error, value

type Setup = tuple[ResInsightSessionService, FactoryDouble, ProjectState, ProjectState]


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    factory = FactoryDouble()
    service = ResInsightSessionService(SqliteWorkspaceStore.create(tmp_path / "workspace"), factory)
    projects = []
    for port in (50051, 50052):
        session = value(service.create_session(Session(session_id=SessionId.new(), name=str(port))))
        value(
            service.attach(
                AttachRequest(session_id=session.session_id, endpoint=Endpoint(port=port))
            )
        )
        projects.append(value(service.inspect_project(session.session_id)))
    return service, factory, projects[0], projects[1]


def test_empty_project_creation_returns_complete_fresh_mapping(setup: Setup) -> None:
    service, factory, first, _ = setup
    app = factory.apps[50051]
    app.project = ProjectSnapshot("empty", ())
    empty = value(service.inspect_project(first.context.session_id))
    created = (
        NativeObject(ObjectKind.CASE, "case-new", "Created case"),
        NativeObject(ObjectKind.VIEW, "view-new", "Created view"),
    )

    def create(access: ApplicationAccess) -> str:
        assert access.application is app
        assert access.project == empty
        assert access.objects == ()
        app.project = ProjectSnapshot("populated", created)
        return created[1].address

    result = service.mutate_project(empty.context, create)
    assert result.value == "view-new"
    assert result.access.objects == created
    assert result.access.project.context.project_generation > empty.context.project_generation
    mapping = dict(zip(result.access.objects, result.access.project.objects, strict=True))
    reference = mapping[created[1]].ref
    assert value(service.resolve_object(reference)).name == "Created view"
    with service.access_objects((reference,)) as access:
        assert access.objects == (created[1],)
    assert value(service.inspect_project(first.context.session_id)) == result.access.project


def test_stale_context_rejects_before_callback(setup: Setup) -> None:
    service, factory, first, _ = setup
    factory.apps[50051].project = ProjectSnapshot("changed", ())
    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, lambda access: pytest.fail("A stale callback ran."))
    assert caught.value.error.code == ErrorCode.STALE_OBJECT
    assert caught.value.error.effect == MutationEffect.NOT_APPLIED
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.READY


def test_changed_process_rejects_before_callback_and_retires_connection(setup: Setup) -> None:
    service, factory, first, _ = setup
    factory.apps[50051].verified_process = ProcessIdentity(pid=50051, start_marker="replacement")
    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, lambda access: pytest.fail("A foreign callback ran."))
    assert caught.value.error.code == ErrorCode.LOST_CONNECTION
    assert caught.value.error.effect == MutationEffect.NOT_APPLIED
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.LOST


def test_all_mutation_phases_exclude_same_session_without_blocking_another(setup: Setup) -> None:
    service, factory, first, second = setup
    app = factory.apps[50051]
    callback_entered, callback_release = Event(), Event()
    refresh_entered, refresh_release = Event(), Event()
    validation_entered, validation_release = Event(), Event()

    def change(access: ApplicationAccess) -> str:
        assert access.objects == app.project.objects
        assert access.project == first
        callback_entered.set()
        assert callback_release.wait(5), "The test did not release the callback."
        app.entered, app.release = refresh_entered, refresh_release
        return "changed"

    def validate(mutation: ProjectMutation[str]) -> None:
        assert mutation.value == "changed"
        assert mutation.access.objects == app.project.objects
        assert mutation.access.project.context.project_generation > first.context.project_generation
        validation_entered.set()
        assert validation_release.wait(5), "The test did not release final validation."

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.mutate_project, first.context, change, validate=validate)
        try:
            for entered, release in (
                (callback_entered, callback_release),
                (refresh_entered, refresh_release),
                (validation_entered, validation_release),
            ):
                assert entered.wait(5)
                assert (
                    error(service.inspect_project(first.context.session_id)).code == ErrorCode.BUSY
                )
                with pytest.raises(ContractError) as caught:
                    with service.access_objects((first.objects[0].ref,)):
                        pytest.fail("Native access overlapped a mutation.")
                assert caught.value.error.code == ErrorCode.BUSY
                assert value(service.inspect_project(second.context.session_id)) == second
                release.set()
        finally:
            callback_release.set()
            refresh_release.set()
            validation_release.set()
        result = pending.result(timeout=5)
    assert result.value == "changed"
    assert result.access.project.context.project_generation > first.context.project_generation
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.READY
    assert value(service.inspect_project(second.context.session_id)) == second


def test_invisible_edit_invalidates_all_old_references(setup: Setup) -> None:
    service, factory, first, second = setup
    observed = []

    def change(access: ApplicationAccess) -> None:
        observed.append(access.objects[0].address)

    result = service.mutate_project(first.context, change)
    assert observed == ["case-0"]
    assert result.value is None
    assert result.access.objects == factory.apps[50051].project.objects
    assert result.access.project.context.project_generation > first.context.project_generation
    assert result.access.project.objects[0].ref != first.objects[0].ref
    assert error(service.resolve_object(first.objects[0].ref)).code == ErrorCode.STALE_OBJECT
    with service.access_objects((result.access.project.objects[0].ref,)) as access:
        assert access.objects == result.access.objects
    assert value(service.inspect_project(second.context.session_id)) == second


def test_known_unapplied_callback_failure_preserves_connection_and_references(setup: Setup) -> None:
    service, _, first, _ = setup
    failure = ContractError(
        Error(code=ErrorCode.INVALID_MODEL, message="The proposed well is invalid.")
    )

    def reject(access: ApplicationAccess) -> None:
        raise failure

    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, reject)
    assert caught.value is failure
    assert caught.value.error.effect == MutationEffect.NOT_APPLIED
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.READY
    assert value(service.resolve_object(first.objects[0].ref)) == first.objects[0]
    assert value(service.inspect_project(first.context.session_id)) == first


@pytest.mark.parametrize("known", [False, True])
def test_uncertain_callback_failure_retires_connection(setup: Setup, known: bool) -> None:
    service, _, first, _ = setup
    failure = (
        ContractError(
            Error(
                code=ErrorCode.EXECUTION_FAILED,
                message="Native outcome is uncertain.",
                effect=MutationEffect.UNKNOWN,
            )
        )
        if known
        else RuntimeError("The domain callback failed.")
    )

    def fail(access: ApplicationAccess) -> None:
        raise failure

    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, fail)
    if known:
        assert caught.value is failure
    else:
        assert caught.value.__cause__ is failure
    assert caught.value.error.code == ErrorCode.EXECUTION_FAILED
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.LOST
    value(
        service.attach(
            AttachRequest(session_id=first.context.session_id, endpoint=Endpoint(port=50051))
        )
    )
    assert error(service.resolve_object(first.objects[0].ref)).code == ErrorCode.STALE_OBJECT


@pytest.mark.parametrize("known", [False, True])
def test_failed_observation_after_completed_mutation_reports_unknown(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, known: bool
) -> None:
    service, factory, first, _ = setup
    app = factory.apps[50051]
    completed = ProjectSnapshot("completed", (NativeObject(ObjectKind.CASE, "new-case", "New"),))

    def fail_observation() -> ProjectSnapshot:
        if known:
            raise ContractError(
                Error(code=ErrorCode.INVALID_MODEL, message="The inventory cannot be read.")
            )
        raise RuntimeError("The inventory reader failed.")

    def change(access: ApplicationAccess) -> None:
        app.project = completed
        monkeypatch.setattr(app, "snapshot", fail_observation)

    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, change)
    assert app.project == completed
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert caught.value.error.code == (
        ErrorCode.INVALID_MODEL if known else ErrorCode.EXECUTION_FAILED
    )
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.LOST
    assert error(service.resolve_object(first.objects[0].ref)).code == ErrorCode.LOST_CONNECTION


@pytest.mark.parametrize("known", [False, True])
def test_failed_final_mapping_validation_retires_completed_mutation(
    setup: Setup, known: bool
) -> None:
    service, factory, first, second = setup
    app = factory.apps[50051]
    completed = ProjectSnapshot("changed", (NativeObject(ObjectKind.CASE, "case-new", "Created"),))
    observed = []

    def change(access: ApplicationAccess) -> str:
        app.project = completed
        return "well-not-observed"

    def validate(mutation: ProjectMutation[str]) -> None:
        observed.append(mutation.access.project)
        assert mutation.access.objects == completed.objects
        assert mutation.value not in {item.address for item in mutation.access.objects}
        if known:
            raise ContractError(
                Error(code=ErrorCode.INVALID_MODEL, message="The created well is not observable.")
            )
        raise RuntimeError("Final mapping validation failed.")

    with pytest.raises(ContractError) as caught:
        service.mutate_project(first.context, change, validate=validate)
    assert app.project == completed
    assert len(observed) == 1
    assert observed[0].context.project_generation > first.context.project_generation
    assert caught.value.error.code == (
        ErrorCode.INVALID_MODEL if known else ErrorCode.EXECUTION_FAILED
    )
    assert caught.value.error.effect == MutationEffect.UNKNOWN
    assert value(service.get_connection(first.context.session_id)).state == ConnectionState.LOST
    assert (
        error(service.resolve_object(observed[0].objects[0].ref)).code == ErrorCode.LOST_CONNECTION
    )
    assert value(service.inspect_project(second.context.session_id)) == second
