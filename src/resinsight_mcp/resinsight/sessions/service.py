"""Explicit session operations with one mutation at a time per application."""

import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import NoReturn
from uuid import uuid4
from weakref import WeakValueDictionary

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ConnectionId, SessionId
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    ApplicationContext,
    AttachRequest,
    CloseAction,
    CloseReceipt,
    CloseRequest,
    Connection,
    ConnectionState,
    LaunchRequest,
    ObjectRef,
    ProcessIdentity,
    ProcessOwnership,
    ProjectCloseRequest,
    ProjectObject,
    ProjectOpenRequest,
    ProjectSaveRequest,
    ProjectState,
    authorize_close,
)

from ._backend import (
    Application,
    ApplicationAccess,
    ApplicationFactory,
    ProjectMutation,
    ProjectSnapshot,
)


def _fail(code: ErrorCode, message: str) -> NoReturn:
    raise ContractError(Error(code=code, message=message))


def _value[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


def _operation[**P, T](method: Callable[P, T]) -> Callable[P, OperationResult[T]]:
    @wraps(method)
    def run(*args: P.args, **kwargs: P.kwargs) -> OperationResult[T]:
        try:
            return OperationResult(outcome=Success(value=method(*args, **kwargs)))
        except ContractError as error:
            return OperationResult(outcome=Failure(error=error.error))

    return run


@dataclass
class _InstanceLock:
    lock: threading.Lock = field(default_factory=threading.Lock)


_instance_guard = threading.Lock()
_instance_locks: WeakValueDictionary[ProcessIdentity, _InstanceLock] = WeakValueDictionary()


def _instance_lock(process: ProcessIdentity, current: _InstanceLock | None) -> _InstanceLock:
    with _instance_guard:
        lock = _instance_locks.get(process)
        if lock is not None:
            if lock is current:
                return lock
            _fail(
                ErrorCode.CONFLICT, "The application is already bound to another session service."
            )
        lock = _InstanceLock()
        _instance_locks[process] = lock
        return lock


@dataclass
class _Slot:
    lock: threading.Lock = field(default_factory=threading.Lock)
    application: Application | None = None
    connection: Connection | None = None
    instance_lock: _InstanceLock | None = None
    snapshot: ProjectSnapshot | None = None
    project: ProjectState | None = None


@contextmanager
def _acquire(lock: threading.Lock) -> Iterator[None]:
    if not lock.acquire(blocking=False):
        _fail(ErrorCode.BUSY, "Another operation is active for this session or application.")
    try:
        yield
    finally:
        lock.release()


class ResInsightSessionService:
    """Own runtime connections without tying their lifetime to a protocol client."""

    def __init__(self, workspaces: WorkspaceStore, factory: ApplicationFactory) -> None:
        self._workspaces = workspaces
        self._factory = factory
        self._guard = threading.Lock()
        self._slots: dict[SessionId, _Slot] = {}

    def create_session(self, session: Session) -> OperationResult[Session]:
        return self._workspaces.create_session(session)

    def list_sessions(self) -> OperationResult[tuple[Session, ...]]:
        return self._workspaces.list_sessions()

    def select_session(self, session_id: SessionId) -> OperationResult[Session]:
        return self._workspaces.get_session(session_id)

    def _slot(self, session_id: SessionId) -> _Slot:
        _value(self._workspaces.get_session(session_id))
        with self._guard:
            return self._slots.setdefault(session_id, _Slot())

    @_operation
    def list_connections(self) -> tuple[Connection, ...]:
        with self._guard:
            return tuple(slot.connection for slot in self._slots.values() if slot.connection)

    @_operation
    def get_connection(self, session_id: SessionId) -> Connection:
        return self._connection(self._slot(session_id))

    @staticmethod
    def _connection(slot: _Slot) -> Connection:
        if slot.connection is None:
            _fail(ErrorCode.NOT_FOUND, "The session has no application connection.")
        return slot.connection

    @_operation
    def launch(self, request: LaunchRequest) -> Connection:
        return self._connect(
            request.session_id,
            lambda: self._factory.launch(request.executable),
            ProcessOwnership.OWNED,
        )

    @_operation
    def attach(self, request: AttachRequest) -> Connection:
        return self._connect(
            request.session_id,
            lambda: self._factory.attach(request.endpoint),
            ProcessOwnership.ATTACHED,
        )

    def _connect(
        self,
        session_id: SessionId,
        connect: Callable[[], Application],
        ownership: ProcessOwnership,
    ) -> Connection:
        slot = self._slot(session_id)
        with _acquire(slot.lock):
            self._allow_connect(slot)
            application = connect()
            try:
                with self._guard:
                    slot.instance_lock = _instance_lock(application.process, slot.instance_lock)
                    slot.application = application
                    slot.connection = Connection(
                        context=ApplicationContext(
                            session_id=session_id,
                            connection_id=ConnectionId.new(),
                            project_generation=0,
                        ),
                        endpoint=application.endpoint,
                        ownership=ownership,
                        state=ConnectionState.READY,
                        process=application.process,
                    )
                    slot.snapshot = None
                    slot.project = None
            except ContractError:
                application.disconnect()
                raise
            return self._connection(slot)

    @staticmethod
    def _allow_connect(slot: _Slot) -> None:
        if slot.connection is None:
            return
        if slot.connection.state not in {ConnectionState.LOST, ConnectionState.DETACHED}:
            _fail(ErrorCode.CONFLICT, "Detach the current connection before replacing it.")
        if slot.application is not None:
            slot.application.disconnect()

    @contextmanager
    def _application(self, session_id: SessionId) -> Iterator[tuple[_Slot, Application]]:
        slot = self._slot(session_id)
        with _acquire(slot.lock):
            connection = self._connection(slot)
            if connection.state in {ConnectionState.LOST, ConnectionState.DETACHED}:
                _fail(
                    ErrorCode.LOST_CONNECTION, "Attach a new connection before using this session."
                )
            application = slot.application
            instance_lock = slot.instance_lock
            assert application is not None and instance_lock is not None
            with _acquire(instance_lock.lock):
                slot.connection = connection.transition(ConnectionState.BUSY)
                try:
                    if application.verify_process() != connection.process:
                        _fail(
                            ErrorCode.LOST_CONNECTION, "The application process identity changed."
                        )
                    yield slot, application
                except ContractError as error:
                    if (
                        error.error.code == ErrorCode.LOST_CONNECTION
                        or error.error.effect == MutationEffect.UNKNOWN
                    ):
                        slot.connection = self._connection(slot).transition(ConnectionState.LOST)
                        slot.snapshot = None
                        slot.project = None
                    raise
                finally:
                    if self._connection(slot).state == ConnectionState.BUSY:
                        slot.connection = self._connection(slot).transition(ConnectionState.READY)

    def _observe(
        self, slot: _Slot, application: Application, *, changed: bool = False
    ) -> ProjectState:
        snapshot = application.snapshot()
        previous = slot.snapshot
        connection = self._connection(slot)
        if changed or (previous is not None and snapshot != previous):
            context = ApplicationContext(
                session_id=connection.context.session_id,
                connection_id=connection.context.connection_id,
                project_generation=connection.context.project_generation + 1,
            )
            slot.connection = Connection.model_validate(
                {**connection.model_dump(), "context": context}
            )
            slot.project = None
        if slot.project is None:
            context = self._connection(slot).context
            slot.project = ProjectState(
                context=context,
                objects=tuple(
                    ProjectObject(
                        ref=ObjectRef(context=context, kind=item.kind, object_id=uuid4().hex),
                        name=item.name,
                    )
                    for item in snapshot.objects
                ),
            )
        slot.snapshot = snapshot
        return slot.project

    @staticmethod
    def _require_context(context: ApplicationContext, project: ProjectState) -> None:
        if context != project.context:
            _fail(ErrorCode.STALE_OBJECT, "The project context changed. Inspect the project again.")

    @_operation
    def inspect_project(self, session_id: SessionId) -> ProjectState:
        with self._application(session_id) as (slot, application):
            return self._observe(slot, application)

    @_operation
    def resolve_object(self, reference: ObjectRef) -> ProjectObject:
        with self._application(reference.context.session_id) as (slot, application):
            project = self._observe(slot, application)
            reference.require_current(project.context)
            for item in project.objects:
                if item.ref == reference:
                    return item
            _fail(ErrorCode.STALE_OBJECT, "The object reference was not issued for this project.")

    @contextmanager
    def access_objects(self, references: tuple[ObjectRef, ...]) -> Iterator[ApplicationAccess]:
        """Hold one verified application lock for a complete native operation."""
        if not references:
            _fail(ErrorCode.INVALID_MODEL, "Native access requires explicit object references.")
        with self._application(references[0].context.session_id) as (slot, application):
            project = self._observe(slot, application)
            assert slot.snapshot is not None
            objects = {
                item.ref: native
                for item, native in zip(project.objects, slot.snapshot.objects, strict=True)
            }
            for reference in references:
                reference.require_current(project.context)
                if reference not in objects:
                    _fail(ErrorCode.STALE_OBJECT, "The object reference was not issued here.")
            yield ApplicationAccess(
                application=application,
                project=project,
                objects=tuple(objects[reference] for reference in references),
            )

    @staticmethod
    def _project_access(
        slot: _Slot, application: Application, project: ProjectState
    ) -> ApplicationAccess:
        assert slot.snapshot is not None
        return ApplicationAccess(
            application=application, project=project, objects=slot.snapshot.objects
        )

    def mutate_project[T](
        self, context: ApplicationContext, change: Callable[[ApplicationAccess], T]
    ) -> ProjectMutation[T]:
        """Hold session ownership through a trusted mutation and reference refresh."""
        with self._application(context.session_id) as (slot, application):
            project = self._observe(slot, application)
            self._require_context(context, project)
            access = self._project_access(slot, application, project)
            try:
                value = change(access)
                refreshed = self._after_change(slot, application)
                return ProjectMutation(
                    value=value, access=self._project_access(slot, application, refreshed)
                )
            except ContractError:
                raise
            except Exception as error:
                raise ContractError(
                    Error(
                        code=ErrorCode.EXECUTION_FAILED,
                        message="The native project mutation failed without a confirmed outcome.",
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from error

    @_operation
    def open_project(self, request: ProjectOpenRequest) -> ProjectState:
        self._input_path(request.path)
        return self._change_project(request.context, lambda app: app.open_project(request.path))

    @_operation
    def close_project(self, request: ProjectCloseRequest) -> ProjectState:
        return self._change_project(request.context, lambda app: app.close_project())

    def _change_project(
        self, context: ApplicationContext, change: Callable[[Application], None]
    ) -> ProjectState:
        with self._application(context.session_id) as (slot, application):
            self._require_context(context, self._observe(slot, application))
            change(application)
            return self._after_change(slot, application)

    def _after_change(self, slot: _Slot, application: Application) -> ProjectState:
        try:
            return self._observe(slot, application, changed=True)
        except ContractError as error:
            raise ContractError(
                Error(
                    code=error.error.code,
                    message="The project command completed, but observing its new state failed.",
                    effect=MutationEffect.UNKNOWN,
                )
            ) from error

    @_operation
    def save_project(self, request: ProjectSaveRequest) -> ProjectState:
        with self._application(request.context.session_id) as (slot, application):
            self._require_context(request.context, self._observe(slot, application))
            self._output_path(request.path, overwrite=request.overwrite)
            application.save_project(request.path)
            project = self._after_change(slot, application)
            self._require_saved_file(request.path)
            slot.project = ProjectState(
                context=project.context,
                objects=project.objects,
                last_saved_path=request.path,
            )
            return slot.project

    @staticmethod
    def _require_saved_file(path: Path) -> None:
        try:
            exists = path.is_file()
        except OSError as error:
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message=f"The project save completed, but checking its output failed: {error}",
                    effect=MutationEffect.UNKNOWN,
                )
            ) from error
        if not exists:
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message="The save command completed without the requested project file.",
                    effect=MutationEffect.UNKNOWN,
                )
            )

    @staticmethod
    def _input_path(path: Path) -> None:
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                _fail(ErrorCode.INVALID_PATH, "The project input must be a regular file.")
        except OSError as error:
            raise ContractError(
                Error(code=ErrorCode.INVALID_PATH, message=f"Cannot read the project path: {error}")
            ) from error

    @staticmethod
    def _output_path(path: Path, *, overwrite: bool) -> None:
        try:
            if not path.parent.is_dir() or path.is_symlink():
                _fail(
                    ErrorCode.INVALID_PATH, "Use an existing directory and a regular project file."
                )
            if path.exists():
                if not path.is_file():
                    _fail(ErrorCode.INVALID_PATH, "The project output must be a regular file.")
                if not overwrite:
                    _fail(
                        ErrorCode.CONFLICT, "The project file exists. Explicitly allow overwrite."
                    )
        except OSError as error:
            raise ContractError(
                Error(code=ErrorCode.INVALID_PATH, message=f"Cannot use the project path: {error}")
            ) from error

    @_operation
    def close(
        self,
        request: CloseRequest,
        *,
        attached_termination_authorized: bool = False,
    ) -> CloseReceipt:
        slot = self._slot(request.session_id)
        with _acquire(slot.lock):
            connection = self._connection(slot)
            if request.action == CloseAction.DETACH:
                authorize_close(connection, request)
                self._detach(slot)
            else:
                self._terminate(slot, request, attached_termination_authorized)
            return CloseReceipt(
                session_id=request.session_id,
                connection_id=request.connection_id,
                action=request.action,
            )

    @staticmethod
    def _detach(slot: _Slot) -> None:
        application = slot.application
        assert slot.connection is not None
        if slot.connection.state != ConnectionState.DETACHED:
            slot.connection = slot.connection.transition(ConnectionState.DETACHED)
        slot.application = None
        slot.instance_lock = None
        slot.snapshot = None
        slot.project = None
        if application is not None:
            try:
                application.disconnect()
            except ContractError as error:
                raise ContractError(
                    Error(
                        code=error.error.code,
                        message="The connection is detached, but its client channel did not close.",
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from error

    def _terminate(self, slot: _Slot, request: CloseRequest, authorized: bool) -> None:
        connection = self._connection(slot)
        # Check caller identity and attached ownership before contacting the application.
        authorize_close(
            connection,
            request,
            verified_process=connection.process,
            attached_termination_authorized=authorized,
        )
        application = slot.application
        instance_lock = slot.instance_lock
        assert application is not None and instance_lock is not None
        with _acquire(instance_lock.lock):
            try:
                authorize_close(
                    connection,
                    request,
                    verified_process=application.verify_process(),
                    attached_termination_authorized=authorized,
                )
                application.terminate()
            except ContractError as error:
                if (
                    error.error.code == ErrorCode.LOST_CONNECTION
                    or error.error.effect == MutationEffect.UNKNOWN
                ):
                    if connection.state != ConnectionState.LOST:
                        slot.connection = connection.transition(ConnectionState.LOST)
                    slot.snapshot = None
                    slot.project = None
                raise
            self._detach(slot)
