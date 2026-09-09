"""Serialize complete view edits and reject old scene observations."""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import EditId, ObservationId, SessionId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.jobs import LoadedResult, Result
from resinsight_mcp.contracts.observations import (
    EditedView,
    Observation,
    RenderRequest,
    ViewContext,
    ViewEditReceipt,
    ViewUpdateRequest,
)
from resinsight_mcp.contracts.sessions import ObjectRef
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess

from ._backend import NativeView, ViewBackend
from ._capture import _value, capture
from ._properties import require_units


class SessionAccess(Protocol):
    def access_objects(
        self, references: tuple[ObjectRef, ...]
    ) -> AbstractContextManager[ApplicationAccess]: ...


def _stale(message: str) -> None:
    raise ContractError(Error(code=ErrorCode.STALE_OBJECT, message=message))


def _references(context: ViewContext) -> tuple[ObjectRef, ...]:
    return (context.case, context.view, *context.selected_wells)


class ResInsightViewService:
    """Keep result bindings and scene versions inside one application controller."""

    def __init__(
        self, workspaces: WorkspaceStore, sessions: SessionAccess, backend: ViewBackend
    ) -> None:
        self._workspaces = workspaces
        self._sessions = sessions
        self._backend = backend
        self._results: dict[ObjectRef, Result] = {}
        self._scenes: dict[ObjectRef, ViewContext] = {}
        self._invalidated: set[ObjectRef] = set()

    def bind_result(self, loaded: LoadedResult) -> OperationResult[LoadedResult]:
        """Accept a trusted loader's case binding after checking its stored result."""
        try:
            with self._sessions.access_objects((loaded.case,)):
                stored = _value(
                    self._workspaces.get_result(
                        loaded.result.model.session_id, loaded.result.result_id
                    )
                )
                if stored != loaded.result:
                    _stale("The loaded result differs from the stored result.")
                previous = self._results.get(loaded.case)
                if previous is not None and previous != stored:
                    _stale("The case already belongs to another result.")
                self._results[loaded.case] = stored
            return OperationResult(outcome=Success(value=loaded))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))

    def _require_result(self, context: ViewContext) -> Result:
        result = _value(self._workspaces.get_result(context.model.session_id, context.result_id))
        if self._results.get(context.case) != result:
            _stale("The case has no current trusted binding to this result.")
        try:
            context.require_result(result)
        except ValueError as error:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL, message="The view differs from its stored result."
                )
            ) from error
        require_units(context, _value(self._workspaces.get_revision(context.model)))
        return result

    def _require_scene(self, context: ViewContext, native: NativeView) -> None:
        if context.view in self._invalidated or self._scenes.get(context.view) != context:
            _stale("The observation scene is no longer current. Apply a new view request.")
        try:
            actual = native.inspect(context)
        except ContractError:
            self._invalidated.add(context.view)
            raise
        if actual != context:
            self._invalidated.add(context.view)
            _stale("The native view changed outside this controller. Apply a new view request.")

    def apply(self, request: ViewUpdateRequest) -> OperationResult[EditedView]:
        edit: ViewEditReceipt | None = None
        try:
            with self._sessions.access_objects(_references(request.context)) as access:
                self._require_result(request.context)
                previous = self._scenes.get(request.context.view)
                expected_version = previous.scene_version if previous is not None else 0
                if request.context.scene_version != expected_version:
                    _stale("The request uses an old scene version.")
                native = self._backend.select(access, request.context)
                self._require_expected_observation(request, native)
                native.validate(request.context)
                updated = ViewContext.model_validate(
                    {**request.context.model_dump(), "scene_version": expected_version + 1}
                )
                actual = native.apply(updated)
                edit = ViewEditReceipt(
                    edit_id=EditId.new(), previous_scene_version=expected_version, context=actual
                )
                self._scenes[actual.view] = actual
                self._invalidated.discard(actual.view)
                observation = self._capture(actual, native, request.width, request.height)
            return OperationResult(
                outcome=Success(
                    value=EditedView(
                        edit=edit, observation=OperationResult(outcome=Success(value=observation))
                    )
                )
            )
        except ContractError as error:
            failure = Failure(error=error.error)
            if edit is None:
                return OperationResult(outcome=failure)
            return OperationResult(
                outcome=Success(
                    value=EditedView(edit=edit, observation=OperationResult(outcome=failure))
                )
            )

    def _require_expected_observation(self, request: ViewUpdateRequest, native: NativeView) -> None:
        if request.expected_observation_id is None:
            return
        observation = _value(
            self._workspaces.get_observation(
                request.context.model.session_id, request.expected_observation_id
            )
        )
        if observation.context.view != request.context.view:
            _stale("The expected observation belongs to another view.")
        self._require_scene(observation.context, native)

    def render(self, request: RenderRequest) -> OperationResult[Observation]:
        try:
            with self._sessions.access_objects(_references(request.context)) as access:
                if self._require_result(request.context) != request.result:
                    _stale("The render request uses another result.")
                native = self._backend.select(access, request.context)
                self._require_scene(request.context, native)
                observation = self._capture(request.context, native, request.width, request.height)
            return OperationResult(outcome=Success(value=observation))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))

    def _capture(
        self, context: ViewContext, native: NativeView, width: int, height: int
    ) -> Observation:
        def export(folder: Path, width: int, height: int) -> None:
            native.export(folder, width, height)
            self._require_scene(context, native)

        return capture(self._workspaces, context, width, height, export)

    def get_observation(
        self, session_id: SessionId, observation_id: ObservationId
    ) -> OperationResult[Observation]:
        try:
            observation = _value(self._workspaces.get_observation(session_id, observation_id))
            context = observation.context
            with self._sessions.access_objects(_references(context)) as access:
                self._require_result(context)
                native = self._backend.select(access, context)
                self._require_scene(context, native)
            return OperationResult(outcome=Success(value=observation))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))
