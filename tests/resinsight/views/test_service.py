"""Test view coordination with real storage and controlled native operations."""

from dataclasses import dataclass
from threading import Thread

import pytest

from resinsight_mcp.contracts.engineering import Unit
from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
)
from resinsight_mcp.contracts.identifiers import GridId, ObservationId
from resinsight_mcp.contracts.jobs import LoadedResult, Result
from resinsight_mcp.contracts.observations import (
    EditedView,
    RenderRequest,
    ViewContext,
    ViewEditReceipt,
    ViewUpdateRequest,
)
from resinsight_mcp.contracts.sessions import AttachRequest, ConnectionState, ObjectRef
from resinsight_mcp.resinsight.sessions.service import ResInsightSessionService
from resinsight_mcp.resinsight.views import _capture
from resinsight_mcp.resinsight.views.service import ResInsightViewService
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import ControlledApplication, ControlledBackend, ControlledFactory, ControlledView
from .conftest import value


@dataclass
class Harness:
    service: ResInsightViewService
    sessions: ResInsightSessionService
    backend: ControlledBackend
    context: ViewContext
    result: Result
    other_view: ObjectRef

    def bind(self) -> None:
        value(self.service.bind_result(LoadedResult(case=self.context.case, result=self.result)))


def failure[T](result: OperationResult[T], code: ErrorCode) -> None:
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == code


def request(context: ViewContext, expected: ObservationId | None = None) -> ViewUpdateRequest:
    return ViewUpdateRequest(context=context, width=64, height=48, expected_observation_id=expected)


@pytest.fixture
def harness(store: SqliteWorkspaceStore, view_context: ViewContext, result: Result) -> Harness:
    application = ControlledApplication()
    sessions = ResInsightSessionService(store, ControlledFactory(application))
    value(
        sessions.attach(
            AttachRequest(session_id=result.model.session_id, endpoint=application.endpoint)
        )
    )
    project = value(sessions.inspect_project(result.model.session_id))
    case, view, well, other_view = (item.ref for item in project.objects)
    context = ViewContext.model_validate(
        {
            **view_context.model_dump(),
            "case": case,
            "view": view,
            "selected_wells": (well,),
            "scene_version": 0,
        }
    )
    backend = ControlledBackend(ControlledView())
    return Harness(
        ResInsightViewService(store, sessions, backend),
        sessions,
        backend,
        context,
        result,
        other_view,
    )


def test_apply_requires_trusted_result_binding(harness: Harness) -> None:
    failure(harness.service.apply(request(harness.context)), ErrorCode.STALE_OBJECT)
    assert harness.backend.native.current is None
    harness.bind()
    edited = value(harness.service.apply(request(harness.context)))
    assert isinstance(edited.edit, ViewEditReceipt)
    assert edited.edit.previous_scene_version == 0
    assert edited.edit.context.scene_version == 1
    observation = value(edited.observation)
    assert observation.context == edited.edit.context
    assert observation.context.selected_wells == harness.context.selected_wells
    assert [item.address for item in harness.backend.selections[-1]] == ["case", "view", "well"]
    assert (
        value(
            harness.service.get_observation(
                harness.result.model.session_id, observation.observation_id
            )
        )
        == observation
    )


@pytest.mark.parametrize("reference", ["case", "view", "well"])
def test_forged_object_references_fail_before_edit(harness: Harness, reference: str) -> None:
    harness.bind()
    context = harness.context
    original = context.selected_wells[0] if reference == "well" else getattr(context, reference)
    forged = original.model_copy(update={"object_id": "not-issued"})
    changes = {"selected_wells": (forged,)} if reference == "well" else {reference: forged}
    invalid = ViewContext.model_validate({**context.model_dump(), **changes})
    failure(harness.service.apply(request(invalid)), ErrorCode.STALE_OBJECT)
    assert harness.backend.native.current is None


def test_next_edit_rejects_previous_observation_and_render(harness: Harness) -> None:
    harness.bind()
    first = value(value(harness.service.apply(request(harness.context))).observation)
    second = value(
        value(harness.service.apply(request(first.context, first.observation_id))).observation
    )
    assert second.context.scene_version == first.context.scene_version + 1
    assert second.observation_id != first.observation_id
    failure(
        harness.service.get_observation(harness.result.model.session_id, first.observation_id),
        ErrorCode.STALE_OBJECT,
    )
    failure(
        harness.service.render(
            RenderRequest(result=harness.result, context=first.context, width=64, height=48)
        ),
        ErrorCode.STALE_OBJECT,
    )
    failure(
        harness.service.apply(request(second.context, first.observation_id)), ErrorCode.STALE_OBJECT
    )
    assert harness.backend.native.current == second.context


def test_expected_observation_must_belong_to_requested_view(harness: Harness) -> None:
    harness.bind()
    first = value(value(harness.service.apply(request(harness.context))).observation)
    other = ViewContext.model_validate({**harness.context.model_dump(), "view": harness.other_view})
    failure(harness.service.apply(request(other, first.observation_id)), ErrorCode.STALE_OBJECT)
    assert harness.backend.native.current == first.context


def test_external_change_invalidates_observation_until_new_apply(harness: Harness) -> None:
    harness.bind()
    first = value(value(harness.service.apply(request(harness.context))).observation)
    harness.backend.native.current = first.context.model_copy(update={"vertical_exaggeration": 2.0})
    failure(
        harness.service.apply(request(first.context, first.observation_id)), ErrorCode.STALE_OBJECT
    )
    harness.backend.native.current = first.context
    failure(
        harness.service.get_observation(harness.result.model.session_id, first.observation_id),
        ErrorCode.STALE_OBJECT,
    )
    fresh = value(value(harness.service.apply(request(first.context))).observation)
    assert fresh.context.scene_version == 2
    assert (
        value(
            harness.service.get_observation(harness.result.model.session_id, fresh.observation_id)
        )
        == fresh
    )


def test_failed_export_preserves_edit_receipt_without_previous_image(
    harness: Harness, store: SqliteWorkspaceStore
) -> None:
    harness.bind()
    first = value(value(harness.service.apply(request(harness.context))).observation)
    artifacts = value(store.list_artifacts(harness.result.model.session_id))
    harness.backend.native.missing_export = True
    edited = value(harness.service.apply(request(first.context)))
    assert isinstance(edited.edit, ViewEditReceipt)
    assert edited.edit.effect == "applied"
    assert edited.edit.context.scene_version == 2
    failure(edited.observation, ErrorCode.RENDER_FAILED)
    assert value(store.list_artifacts(harness.result.model.session_id)) == artifacts
    failure(
        harness.service.get_observation(harness.result.model.session_id, first.observation_id),
        ErrorCode.STALE_OBJECT,
    )
    assert value(harness.sessions.get_connection(harness.result.model.session_id)).state == (
        ConnectionState.READY
    )


@pytest.mark.parametrize("operation", ["edit", "export"])
def test_unknown_native_failure_retires_session(harness: Harness, operation: str) -> None:
    harness.bind()
    error = Error(
        code=ErrorCode.EXECUTION_FAILED,
        message="The native operation outcome is unknown.",
        effect=MutationEffect.UNKNOWN,
    )
    if operation == "edit":
        harness.backend.native.edit_error = error
    else:
        harness.backend.native.export_error = error
    outcome = harness.service.apply(request(harness.context))
    if operation == "export":
        edited = value(outcome)
        assert isinstance(edited.edit, ViewEditReceipt)
        assert edited.edit.context.scene_version == 1
        failure(edited.observation, ErrorCode.EXECUTION_FAILED)
    else:
        failure(outcome, ErrorCode.EXECUTION_FAILED)
    assert value(harness.sessions.get_connection(harness.result.model.session_id)).state == (
        ConnectionState.LOST
    )
    failure(
        harness.sessions.inspect_project(harness.result.model.session_id), ErrorCode.LOST_CONNECTION
    )


def test_busy_access_fails_promptly_and_releases_lock(harness: Harness) -> None:
    harness.bind()
    outcomes: list[OperationResult[EditedView]] = []

    def apply_while_busy() -> None:
        outcomes.append(harness.service.apply(request(harness.context)))

    worker = Thread(target=apply_while_busy, daemon=True)
    with harness.sessions.access_objects((harness.context.case,)):
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive(), "The busy request did not return promptly."
        assert len(outcomes) == 1
        failure(outcomes[0], ErrorCode.BUSY)
    edited = value(harness.service.apply(request(harness.context)))
    assert value(edited.observation).context.scene_version == 1


def test_binding_rejects_result_that_differs_from_storage(harness: Harness) -> None:
    changed = harness.result.model_copy(update={"grid_id": GridId.new()})
    failure(
        harness.service.bind_result(LoadedResult(case=harness.context.case, result=changed)),
        ErrorCode.STALE_OBJECT,
    )
    failure(harness.service.apply(request(harness.context)), ErrorCode.STALE_OBJECT)
    assert harness.backend.native.current is None


def test_temporary_directory_failure_preserves_applied_view(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.bind()

    def unavailable_directory(*args, **kwargs):
        raise OSError("No space left for a new observation directory.")

    monkeypatch.setattr(_capture, "TemporaryDirectory", unavailable_directory)
    edited = value(harness.service.apply(request(harness.context)))
    assert isinstance(edited.edit, ViewEditReceipt)
    assert edited.edit.context.scene_version == 1
    failure(edited.observation, ErrorCode.RENDER_FAILED)
    assert harness.backend.native.current == edited.edit.context


@pytest.mark.parametrize("invalid", ["unit", "coordinates", "property"])
def test_apply_rejects_untrusted_metadata(harness: Harness, invalid: str) -> None:
    harness.bind()
    context = harness.context.model_dump()
    if invalid == "unit":
        context["property"] = {"name": "PRESSURE", "unit": Unit.BAR}
    elif invalid == "coordinates":
        context["coordinates"]["datum"] = "Another origin"
    else:
        context["property"]["name"] = "UNSUPPORTED"
    outcome = harness.service.apply(request(ViewContext.model_validate(context)))
    code = ErrorCode.UNSUPPORTED_OPERATION if invalid == "property" else ErrorCode.INVALID_MODEL
    failure(outcome, code)
    assert harness.backend.native.current is None


def test_inspection_error_keeps_old_observation_invalid(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.bind()
    observation = value(value(harness.service.apply(request(harness.context))).observation)
    original = harness.backend.native.inspect

    def unavailable_scene(context: ViewContext) -> ViewContext:
        raise ContractError(
            Error(code=ErrorCode.STALE_OBJECT, message="A linked view prevents inspection.")
        )

    monkeypatch.setattr(harness.backend.native, "inspect", unavailable_scene)
    failure(
        harness.service.get_observation(
            observation.context.model.session_id, observation.observation_id
        ),
        ErrorCode.STALE_OBJECT,
    )
    monkeypatch.setattr(harness.backend.native, "inspect", original)
    failure(
        harness.service.get_observation(
            observation.context.model.session_id, observation.observation_id
        ),
        ErrorCode.STALE_OBJECT,
    )


def test_changed_scene_during_export_rejects_image(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.bind()
    original = harness.backend.native.export

    def change_during_export(folder, width, height):
        original(folder, width, height)
        current = harness.backend.native.current
        assert current is not None
        harness.backend.native.current = current.model_copy(update={"vertical_exaggeration": 2})

    monkeypatch.setattr(harness.backend.native, "export", change_during_export)
    edited = value(harness.service.apply(request(harness.context)))
    assert isinstance(edited.edit, ViewEditReceipt)
    assert edited.edit.context.scene_version == 1
    failure(edited.observation, ErrorCode.STALE_OBJECT)
