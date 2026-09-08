"""Durable sessions and live application handles have separate lifetimes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.interfaces import SessionService
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    AttachRequest,
    CloseAction,
    CloseRequest,
    ConnectionState,
    Endpoint,
    LaunchRequest,
    ObjectKind,
    ObjectRef,
    ProcessIdentity,
    ProcessOwnership,
    ProjectCloseRequest,
    ProjectOpenRequest,
    ProjectSaveRequest,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import NativeObject, ProjectSnapshot
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import FactoryDouble, error, value

type Setup = tuple[SessionService, FactoryDouble, Session, Session]


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    factory = FactoryDouble()
    service: SessionService = ResInsightSessionService(
        SqliteWorkspaceStore.create(tmp_path / "workspace"), factory
    )
    first = value(service.create_session(Session(session_id=SessionId.new(), name="First")))
    second = value(service.create_session(Session(session_id=SessionId.new(), name="Second")))
    return service, factory, first, second


def test_sessions_survive_a_new_controller_without_live_connections(
    setup: Setup, tmp_path: Path
) -> None:
    service, factory, first, second = setup
    value(service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051))))
    reopened = ResInsightSessionService(SqliteWorkspaceStore.open(tmp_path / "workspace"), factory)
    assert set(value(reopened.list_sessions())) == {first, second}
    assert value(reopened.select_session(first.session_id)) == first
    assert value(reopened.list_connections()) == ()
    assert factory.apps[50051].calls == []


@pytest.mark.parametrize("launch", [False, True])
def test_unknown_session_never_starts_or_attaches_an_application(
    setup: Setup, launch: bool
) -> None:
    service, factory, _, _ = setup
    unknown = SessionId.new()
    result = (
        service.launch(LaunchRequest(session_id=unknown, executable=Path("/app")))
        if launch
        else service.attach(AttachRequest(session_id=unknown, endpoint=Endpoint(port=50051)))
    )
    assert error(result).code == ErrorCode.NOT_FOUND
    assert factory.calls == []


def test_one_process_cannot_bind_two_sessions_and_selection_does_not_retarget(setup: Setup) -> None:
    service, factory, first, second = setup
    connection = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    assert (
        error(
            service.attach(
                AttachRequest(session_id=second.session_id, endpoint=Endpoint(port=50051))
            )
        ).code
        == ErrorCode.CONFLICT
    )
    value(service.select_session(second.session_id))
    value(service.close_project(ProjectCloseRequest(context=connection.context)))
    assert factory.apps[50051].calls[-1] == ("close_project", None)
    assert factory.apps[50052].calls == []


def test_external_inventory_change_rejects_old_and_forged_references(setup: Setup) -> None:
    service, factory, first, second = setup
    for session, port in ((first, 50051), (second, 50052)):
        value(
            service.attach(
                AttachRequest(session_id=session.session_id, endpoint=Endpoint(port=port))
            )
        )
    before = value(service.inspect_project(first.session_id))
    ref = before.objects[0].ref
    assert value(service.resolve_object(ref)) == before.objects[0]
    other = value(service.inspect_project(second.session_id))
    forged = ObjectRef(context=other.context, kind=ref.kind, object_id=ref.object_id)
    assert error(service.resolve_object(forged)).code == ErrorCode.STALE_OBJECT
    factory.apps[50051].project = ProjectSnapshot(
        "root", (NativeObject(ObjectKind.CASE, "case-0", "Renamed"),)
    )
    assert error(service.resolve_object(ref)).code == ErrorCode.STALE_OBJECT
    after = value(service.inspect_project(first.session_id))
    assert after.context.project_generation > before.context.project_generation
    assert after.objects[0].name == "Renamed"
    assert value(service.inspect_project(second.session_id)) == other


def test_explicit_project_operations_invalidate_even_an_identical_inventory(
    setup: Setup, tmp_path: Path
) -> None:
    service, _, first, _ = setup
    value(service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051))))
    state = value(service.inspect_project(first.session_id))
    project = tmp_path / "input.rsp"
    project.write_text("Test project")
    opened = value(service.open_project(ProjectOpenRequest(context=state.context, path=project)))
    assert opened.context.project_generation > state.context.project_generation
    assert (
        error(service.close_project(ProjectCloseRequest(context=state.context))).code
        == ErrorCode.STALE_OBJECT
    )
    saved_path = tmp_path / "saved.rsp"
    saved = value(service.save_project(ProjectSaveRequest(context=opened.context, path=saved_path)))
    assert saved.last_saved_path == saved_path
    assert saved.context.project_generation > opened.context.project_generation
    closed = value(service.close_project(ProjectCloseRequest(context=saved.context)))
    assert closed.context.project_generation > saved.context.project_generation


def test_invalid_paths_and_default_overwrite_reject_before_application_calls(
    setup: Setup, tmp_path: Path
) -> None:
    service, factory, first, _ = setup
    connection = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    for path in (tmp_path / "missing.rsp", tmp_path):
        assert (
            error(
                service.open_project(ProjectOpenRequest(context=connection.context, path=path))
            ).code
            == ErrorCode.INVALID_PATH
        )
    target = tmp_path / "existing.rsp"
    target.write_text("Original project")
    assert (
        error(
            service.save_project(ProjectSaveRequest(context=connection.context, path=target))
        ).code
        == ErrorCode.CONFLICT
    )
    assert (
        error(
            service.save_project(
                ProjectSaveRequest(
                    context=connection.context, path=tmp_path / "missing" / "file.rsp"
                )
            )
        ).code
        == ErrorCode.INVALID_PATH
    )
    assert target.read_text() == "Original project"
    assert factory.apps[50051].calls == []
    value(
        service.save_project(
            ProjectSaveRequest(context=connection.context, path=target, overwrite=True)
        )
    )
    assert target.read_text() == "Saved test project"


@pytest.mark.parametrize(
    "code,effect",
    [
        (ErrorCode.EXECUTION_FAILED, MutationEffect.UNKNOWN),
        (ErrorCode.LOST_CONNECTION, MutationEffect.NOT_APPLIED),
    ],
)
def test_uncertain_mutation_loses_binding_and_reconnect_rejects_previous_refs(
    setup: Setup, tmp_path: Path, code: ErrorCode, effect: MutationEffect
) -> None:
    service, factory, first, _ = setup
    connection = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    state = value(service.inspect_project(first.session_id))
    factory.apps[50051].failure = ContractError(
        Error(code=code, message="Transport failed", effect=effect)
    )
    failed = error(
        service.save_project(ProjectSaveRequest(context=state.context, path=tmp_path / "out.rsp"))
    )
    assert failed.code == code
    assert failed.effect == effect
    assert value(service.get_connection(first.session_id)).state == ConnectionState.LOST
    rebound = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    assert rebound.context.connection_id != connection.context.connection_id
    assert rebound.ownership == ProcessOwnership.ATTACHED
    assert error(service.resolve_object(state.objects[0].ref)).code == ErrorCode.STALE_OBJECT


def test_busy_session_does_not_block_another_application_or_lose_connection(setup: Setup) -> None:
    service, factory, first, second = setup
    for session, port in ((first, 50051), (second, 50052)):
        value(
            service.attach(
                AttachRequest(session_id=session.session_id, endpoint=Endpoint(port=port))
            )
        )
    app = factory.apps[50051]
    app.entered, app.release = Event(), Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        blocked = pool.submit(service.inspect_project, first.session_id)
        try:
            assert app.entered.wait(5)
            busy = error(service.inspect_project(first.session_id))
            assert busy.code == ErrorCode.BUSY
            assert busy.effect == MutationEffect.NOT_APPLIED
            assert (
                value(
                    pool.submit(service.inspect_project, second.session_id).result(timeout=2)
                ).context.session_id
                == second.session_id
            )
        finally:
            app.release.set()
        value(blocked.result(timeout=5))
    assert value(service.get_connection(first.session_id)).state == ConnectionState.READY


def test_owned_default_close_detaches_and_attached_termination_needs_trusted_permission(
    setup: Setup,
) -> None:
    service, factory, first, second = setup
    owned = value(
        service.launch(LaunchRequest(session_id=first.session_id, executable=Path("/app")))
    )
    value(
        service.close(
            CloseRequest(session_id=first.session_id, connection_id=owned.context.connection_id)
        )
    )
    assert factory.apps[50051].calls == [("disconnect", None)]
    attached = value(
        service.attach(AttachRequest(session_id=second.session_id, endpoint=Endpoint(port=50052)))
    )
    request = CloseRequest(
        session_id=second.session_id,
        connection_id=attached.context.connection_id,
        action=CloseAction.TERMINATE,
    )
    assert error(service.close(request)).code == ErrorCode.UNSUPPORTED_OPERATION
    assert factory.apps[50052].calls == []
    value(service.close(request, attached_termination_authorized=True))
    assert ("terminate", None) in factory.apps[50052].calls


def test_termination_rejects_changed_process_lifetime(setup: Setup) -> None:
    service, factory, first, _ = setup
    connection = value(
        service.launch(LaunchRequest(session_id=first.session_id, executable=Path("/app")))
    )
    factory.apps[50051].verified_process = ProcessIdentity(pid=50051, start_marker="reused-pid")
    result = service.close(
        CloseRequest(
            session_id=first.session_id,
            connection_id=connection.context.connection_id,
            action=CloseAction.TERMINATE,
        )
    )
    assert error(result).code == ErrorCode.LOST_CONNECTION
    assert factory.apps[50051].calls == []


def test_detach_keeps_session_and_new_binding_rejects_old_references(setup: Setup) -> None:
    service, factory, first, _ = setup
    attached = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    state = value(service.inspect_project(first.session_id))
    assert (
        error(
            service.attach(
                AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50052))
            )
        ).code
        == ErrorCode.CONFLICT
    )
    value(
        service.close(
            CloseRequest(session_id=first.session_id, connection_id=attached.context.connection_id)
        )
    )
    assert value(service.get_connection(first.session_id)).state == ConnectionState.DETACHED
    assert value(service.select_session(first.session_id)) == first
    rebound = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    assert rebound.context.connection_id != attached.context.connection_id
    assert error(service.resolve_object(state.objects[0].ref)).code == ErrorCode.STALE_OBJECT
    assert factory.apps[50051].calls == [("disconnect", None)]


def test_process_binding_spans_controllers_until_explicit_detach(
    setup: Setup, tmp_path: Path
) -> None:
    service, factory, first, _ = setup
    other = ResInsightSessionService(
        SqliteWorkspaceStore.create(tmp_path / "other-workspace"), factory
    )
    second = value(
        other.create_session(Session(session_id=SessionId.new(), name="Other controller"))
    )
    connection = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    rejected = other.attach(
        AttachRequest(session_id=second.session_id, endpoint=Endpoint(port=50051))
    )
    assert error(rejected).code == ErrorCode.CONFLICT
    assert value(other.list_connections()) == ()
    value(
        service.close(
            CloseRequest(
                session_id=first.session_id, connection_id=connection.context.connection_id
            )
        )
    )
    attached = value(
        other.attach(AttachRequest(session_id=second.session_id, endpoint=Endpoint(port=50051)))
    )
    assert attached.context.connection_id != connection.context.connection_id
    assert attached.context.session_id == second.session_id


def test_save_verification_failure_reports_uncertainty_and_loses_connection(
    setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, factory, first, _ = setup
    connection = value(
        service.attach(AttachRequest(session_id=first.session_id, endpoint=Endpoint(port=50051)))
    )
    target = tmp_path / "saved-but-unreadable.rsp"
    original_is_file = Path.is_file

    def inaccessible_after_save(path: Path) -> bool:
        if path == target and ("save", target) in factory.apps[50051].calls:
            raise PermissionError("The saved project cannot be inspected.")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", inaccessible_after_save)
    result = service.save_project(ProjectSaveRequest(context=connection.context, path=target))
    assert error(result).effect == MutationEffect.UNKNOWN
    assert target.read_text() == "Saved test project"
    assert value(service.get_connection(first.session_id)).state == ConnectionState.LOST


@pytest.mark.parametrize("action", [CloseAction.DETACH, CloseAction.TERMINATE])
def test_close_cleanup_failure_retires_connection_and_reports_uncertainty(
    setup: Setup, action: CloseAction
) -> None:
    service, factory, first, _ = setup
    connection = value(
        service.launch(LaunchRequest(session_id=first.session_id, executable=Path("/app")))
    )
    state = value(service.inspect_project(first.session_id))
    app = factory.apps[50051]
    app.disconnect_failure = ContractError(
        Error(code=ErrorCode.EXECUTION_FAILED, message="Client channel cleanup failed.")
    )
    result = service.close(
        CloseRequest(
            session_id=first.session_id,
            connection_id=connection.context.connection_id,
            action=action,
        )
    )
    assert error(result).effect == MutationEffect.UNKNOWN
    assert value(service.get_connection(first.session_id)).state == ConnectionState.DETACHED
    assert error(service.resolve_object(state.objects[0].ref)).code == ErrorCode.LOST_CONNECTION
    if action == CloseAction.TERMINATE:
        assert app.calls == [("terminate", None), ("disconnect", None)]
    else:
        assert app.calls == [("disconnect", None)]
