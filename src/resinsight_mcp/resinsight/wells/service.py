"""Own native well identity while keeping simulator publication separate."""

import io
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from functools import wraps
from math import isclose
from threading import Condition, Lock, RLock
from typing import Concatenate, NoReturn, Protocol

from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, ConnectionId, SessionId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.models.imports import MaterializedModel, OpmImportService
from resinsight_mcp.models.wells.records import (
    CompletionExport,
    ModeledWell,
    ModeledWellDefinition,
    PreparedCase,
    PreparedCaseRequest,
    WellCreateRequest,
    WellExportRequest,
    WellUpdateRequest,
)
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess, ProjectMutation

from ._backend import NativeWell, WellBackend


class SessionAccess(Protocol):
    def access_objects(
        self, references: tuple[ObjectRef, ...]
    ) -> AbstractContextManager[ApplicationAccess]: ...

    def mutate_project[T](
        self,
        context: ApplicationContext,
        change: Callable[[ApplicationAccess], T],
        *,
        validate: Callable[[ProjectMutation[T]], None] | None = None,
    ) -> ProjectMutation[T]: ...


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _error(cause: Exception, *, unknown: bool = False) -> Error:
    if isinstance(cause, ContractError):
        error = cause.error
    else:
        error = Error(
            code=ErrorCode.STORAGE_FAILED
            if isinstance(cause, OSError)
            else ErrorCode.INVALID_MODEL,
            message=str(cause),
        )
    return error.model_copy(update={"effect": MutationEffect.UNKNOWN}) if unknown else error


def _operation[**P, T](
    function: Callable[Concatenate["ResInsightWellService", P], T],
) -> Callable[Concatenate["ResInsightWellService", P], OperationResult[T]]:
    @wraps(function)
    def run(self: "ResInsightWellService", *args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            with self._active_call():
                return OperationResult(outcome=Success(value=function(self, *args, **kwargs)))
        except (ContractError, OSError, ValidationError) as cause:
            return OperationResult(outcome=Failure(error=_error(cause)))

    return run


def _stale(message: str) -> NoReturn:
    raise ContractError(Error(code=ErrorCode.STALE_OBJECT, message=message))


@dataclass(frozen=True)
class _Case:
    address: str
    materialized: MaterializedModel


@dataclass(frozen=True)
class _Well:
    case: _Case
    native: NativeWell
    version: int


type _Key = tuple[ConnectionId, str]


def _same_definition(first: ModeledWellDefinition, second: ModeledWellDefinition) -> bool:
    if first.name != second.name or first.coordinates != second.coordinates:
        return False
    if len(first.targets) != len(second.targets) or len(first.perforations) != len(
        second.perforations
    ):
        return False
    first_values = tuple(
        value for target in first.targets for value in (target.x_ft, target.y_ft, target.depth_ft)
    ) + tuple(
        value
        for interval in first.perforations
        for value in (interval.start_md_ft, interval.end_md_ft, interval.diameter_ft, interval.skin)
    )
    second_values = tuple(
        value for target in second.targets for value in (target.x_ft, target.y_ft, target.depth_ft)
    ) + tuple(
        value
        for interval in second.perforations
        for value in (interval.start_md_ft, interval.end_md_ft, interval.diameter_ft, interval.skin)
    )
    return all(
        isclose(actual, wanted, rel_tol=1e-6, abs_tol=1e-6)
        for actual, wanted in zip(first_values, second_values, strict=True)
    )


class ResInsightWellService:
    """Working cases depend on staged sources until explicit service close."""

    def __init__(
        self,
        workspaces: WorkspaceStore,
        sessions: SessionAccess,
        imports: OpmImportService,
        backend: WellBackend,
    ) -> None:
        self._workspaces = workspaces
        self._sessions = sessions
        self._imports = imports
        self._backend = backend
        self._staging = ExitStack()
        self._staging_lock = Lock()
        self._state_lock = RLock()
        self._lifetime = Condition()
        self._active_calls = 0
        self._closing = False
        self._closed = False
        self._close_result: OperationResult[None] | None = None
        self._contexts: dict[SessionId, ApplicationContext] = {}
        self._cases: dict[_Key, _Case] = {}
        self._wells: dict[_Key, _Well] = {}
        self._references: dict[_Key, ObjectRef] = {}
        self._exports: dict[ArtifactRef, CompletionExport] = {}

    @contextmanager
    def _active_call(self) -> Iterator[None]:
        with self._lifetime:
            if self._closing or self._closed:
                _stale("The well service has closed its staged sources.")
            self._active_calls += 1
        try:
            yield
        finally:
            with self._lifetime:
                self._active_calls -= 1
                self._lifetime.notify_all()

    def _current(self, context: ApplicationContext, *, new: bool = False) -> None:
        if self._closed:
            _stale("The well service has closed its staged sources.")
        previous = self._contexts.get(context.session_id)
        if previous != context and not (new and previous is None):
            _stale(
                "The native project changed outside the well service. "
                "Use a new well service lifetime."
            )

    def _refresh(self, access: ApplicationAccess) -> None:
        with self._state_lock:
            context = access.project.context
            self._contexts[context.session_id] = context
            self._references = {
                key: reference
                for key, reference in self._references.items()
                if key[0] != context.connection_id
            }
            for issued, native in zip(access.project.objects, access.objects, strict=True):
                self._references[(context.connection_id, native.address)] = issued.ref

    def _case(self, binding: PreparedCase) -> _Case:
        with self._state_lock:
            self._current(binding.case.context)
            matches = [
                state
                for key, state in self._cases.items()
                if self._references.get(key) == binding.case
            ]
            if len(matches) != 1 or matches[0].materialized.revision.model != binding.model:
                _stale("The prepared case binding was not issued by this well service.")
            return matches[0]

    def _well(self, reference: ObjectRef) -> _Well:
        with self._state_lock:
            self._current(reference.context)
            if reference.kind != ObjectKind.WELL:
                _stale("The reference does not identify a modeled well.")
            matches = [
                state
                for key, state in self._wells.items()
                if self._references.get(key) == reference
            ]
            if len(matches) != 1:
                _stale("The well was not issued by this well service.")
            return matches[0]

    def _validate_case(self, access: ApplicationAccess, case: _Case) -> None:
        expected = case.materialized.revision
        if _value(self._workspaces.get_revision(expected.model)) != expected:
            _stale("The stored model differs from the bound model revision.")
        self._backend.verify_case(access, case.address, case.materialized.inspection)

    @staticmethod
    def _validate_definition(case: _Case, definition: ModeledWellDefinition) -> None:
        if definition.coordinates != case.materialized.revision.coordinates:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="The well coordinates differ from the prepared model.",
                )
            )
        if definition.name not in case.materialized.inspection.summary.wells:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="The well name does not exist in the prepared simulator model.",
                )
            )

    def _observed(self, context: ApplicationContext, state: _Well) -> ModeledWell:
        with self._state_lock:
            case_ref = self._references[(context.connection_id, state.case.address)]
            well_ref = self._references[(context.connection_id, state.native.address)]
            return ModeledWell(
                binding=PreparedCase(model=state.case.materialized.revision.model, case=case_ref),
                well=well_ref,
                version=state.version,
                definition=state.native.definition,
                trajectory=state.native.trajectory,
            )

    def _inspect(self, access: ApplicationAccess, state: _Well) -> NativeWell:
        self._validate_case(access, state.case)
        actual = self._backend.inspect(
            access, state.native.address, state.native.definition.coordinates
        )
        if actual.address != state.native.address:
            _stale("The observed native well has another identity.")
        if not _same_definition(actual.definition, state.native.definition):
            _stale("The native well definition changed outside this service.")
        if len(actual.trajectory) != len(state.native.trajectory):
            _stale("The native sampled trajectory changed outside this service.")
        for observed, expected in zip(actual.trajectory, state.native.trajectory, strict=True):
            if not all(
                isclose(first, second, rel_tol=1e-6, abs_tol=1e-6)
                for first, second in zip(
                    (observed.x_ft, observed.y_ft, observed.depth_ft, observed.measured_depth_ft),
                    (expected.x_ft, expected.y_ft, expected.depth_ft, expected.measured_depth_ft),
                    strict=True,
                )
            ):
                _stale("The native sampled trajectory changed outside this service.")
        return actual

    @_operation
    def load(self, request: PreparedCaseRequest) -> PreparedCase:
        self._current(request.context, new=True)
        with self._staging_lock:
            materialized = self._staging.enter_context(self._imports.materialize(request.model))
        completed: PreparedCase | None = None

        def finish(mutation: ProjectMutation[str]) -> None:
            nonlocal completed
            self._refresh(mutation.access)
            context = mutation.access.project.context
            case = _Case(mutation.value, materialized)
            key = (context.connection_id, case.address)
            completed = PreparedCase(model=request.model, case=self._references[key])
            with self._state_lock:
                self._cases[key] = case

        self._sessions.mutate_project(
            request.context,
            lambda access: self._backend.load(access, materialized),
            validate=finish,
        )
        assert completed is not None
        return completed

    @_operation
    def create(self, request: WellCreateRequest) -> ModeledWell:
        case = self._case(request.binding)
        self._validate_definition(case, request.definition)

        def change(access: ApplicationAccess) -> NativeWell:
            self._validate_case(access, case)
            native = self._backend.create(access, case.address, request.definition)
            self._validate_native_result(native, request.definition)
            return native

        completed: ModeledWell | None = None

        def finish(mutation: ProjectMutation[NativeWell]) -> None:
            nonlocal completed
            completed = self._accept_well(mutation, case, 0)

        self._sessions.mutate_project(request.binding.case.context, change, validate=finish)
        assert completed is not None
        return completed

    @_operation
    def update(self, request: WellUpdateRequest) -> ModeledWell:
        state = self._well(request.well)
        if state.version != request.expected_version:
            _stale("The requested modeled well version is stale.")
        self._validate_definition(state.case, request.definition)
        if request.definition.name != state.native.definition.name:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="A modeled well update cannot change its simulator name.",
                )
            )

        def change(access: ApplicationAccess) -> NativeWell:
            self._inspect(access, state)
            native = self._backend.update(
                access, state.case.address, state.native.address, request.definition
            )
            self._validate_native_result(native, request.definition)
            if native.address != state.native.address:
                raise ContractError(
                    Error(
                        code=ErrorCode.STALE_OBJECT,
                        message="The native update changed well identity.",
                        effect=MutationEffect.UNKNOWN,
                    )
                )
            return native

        completed: ModeledWell | None = None

        def finish(mutation: ProjectMutation[NativeWell]) -> None:
            nonlocal completed
            completed = self._accept_well(mutation, state.case, state.version + 1)

        self._sessions.mutate_project(request.well.context, change, validate=finish)
        assert completed is not None
        return completed

    def _accept_well(
        self, mutation: ProjectMutation[NativeWell], case: _Case, version: int
    ) -> ModeledWell:
        with self._state_lock:
            self._refresh(mutation.access)
            state = _Well(case, mutation.value, version)
            context = mutation.access.project.context
            completed = self._observed(context, state)
            self._wells[(context.connection_id, state.native.address)] = state
            return completed

    @_operation
    def inspect(self, well: ObjectRef) -> ModeledWell:
        state = self._well(well)
        with self._sessions.access_objects((well,)) as access:
            self._inspect(access, state)
            return self._observed(access.project.context, state)

    @_operation
    def export(self, request: WellExportRequest) -> CompletionExport:
        state = self._well(request.well)
        if state.version != request.expected_version:
            _stale("The requested modeled well version is stale.")
        with self._sessions.access_objects((request.well,)) as access:
            self._inspect(access, state)
            native = self._backend.completions(access, state.case.address, state.native.address)
            active = set(state.case.materialized.inspection.active_cells)
            for connection in native.connections:
                if connection.cell not in active:
                    raise ContractError(
                        Error(
                            code=ErrorCode.INVALID_MODEL,
                            message="An exported completion does not identify an active cell.",
                        )
                    )
                if not any(
                    interval.start_md_ft - 1e-6 <= connection.start_md_ft
                    and connection.end_md_ft <= interval.end_md_ft + 1e-6
                    for interval in state.native.definition.perforations
                ):
                    raise ContractError(
                        Error(
                            code=ErrorCode.INVALID_MODEL,
                            message="An exported completion falls outside its perforations.",
                        )
                    )
            ni, nj, _ = state.case.materialized.inspection.summary.dimensions
            if native.wellhead.i >= ni or native.wellhead.j >= nj:
                raise ContractError(
                    Error(
                        code=ErrorCode.INVALID_MODEL,
                        message="The native wellhead falls outside the prepared grid.",
                    )
                )
            reference = ArtifactRef(
                session_id=request.well.context.session_id, artifact_id=ArtifactId.new()
            )
            exported = CompletionExport(
                artifact=reference,
                modeled_well=self._observed(access.project.context, state),
                wellhead=native.wellhead,
                connections=native.connections,
            )
            artifact = Artifact(
                ref=reference,
                relative_path=f"native-wells/{reference.artifact_id}.json",
                kind=ArtifactKind.LOG,
            )
            try:
                _value(
                    self._workspaces.write_artifact(
                        artifact, io.BytesIO(exported.model_dump_json(indent=2).encode("utf-8"))
                    )
                )
            except (ContractError, OSError) as cause:
                raise ContractError(_error(cause, unknown=True)) from cause
            self._exports[reference] = exported
            return exported

    @_operation
    def get_export(self, reference: ArtifactRef) -> CompletionExport:
        exported = self._exports.get(reference)
        if exported is None:
            _stale("The completion snapshot was not issued by this well service.")
        with self._workspaces.open_artifact(reference) as stream:
            stored = CompletionExport.model_validate_json(stream.read())
        if stored != exported:
            _stale("The stored completion snapshot differs from the issued export.")
        return exported

    @staticmethod
    def _validate_native_result(native: NativeWell, definition: ModeledWellDefinition) -> None:
        try:
            if not _same_definition(native.definition, definition):
                _stale("The observed native definition differs from the requested well.")
            definition.require_trajectory(native.trajectory)
        except (ContractError, ValueError) as cause:
            raise ContractError(_error(cause, unknown=True)) from cause

    def close(self) -> OperationResult[None]:
        """End staged-source support explicitly; do not call on an MCP disconnect."""
        with self._lifetime:
            if self._close_result is not None:
                return self._close_result
            self._closing = True
            self._lifetime.wait_for(lambda: self._active_calls == 0)
            if self._close_result is not None:
                return self._close_result
            self._closed = True
            try:
                self._staging.close()
                self._close_result = OperationResult(outcome=Success(value=None))
            except (ContractError, OSError) as cause:
                self._close_result = OperationResult(outcome=Failure(error=_error(cause)))
            return self._close_result
