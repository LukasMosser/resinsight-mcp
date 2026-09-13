"""Route one MCP connection to one selected local workspace at a time."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.workspace import Workspace, WorkspaceRequest
from resinsight_mcp.workspaces import SqliteWorkspaceStore

if TYPE_CHECKING:
    from .catalog import Bindings


RuntimeFactory = Callable[[Path], Any]


def _failure(error: Error) -> OperationResult[Any]:
    return OperationResult(outcome=Failure(error=error))


def _success[T](value: T) -> OperationResult[T]:
    return OperationResult(outcome=Success(value=value))


def _storage_failure(error: OSError) -> ContractError:
    return ContractError(
        Error(
            code=ErrorCode.STORAGE_FAILED,
            message=f"The workspace manager operation failed: {error}",
        )
    )


class _ServiceProxy:
    """Resolve a service method only after the agent selects a workspace."""

    def __init__(self, manager: WorkspaceManager, attribute: str) -> None:
        self._manager = manager
        self._attribute = attribute

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            target = self._manager.current_target(self._attribute)
            return getattr(target, name)(*args, **kwargs)

        return call


class WorkspaceManager:
    """Create, list, and select workspaces below one trusted local directory."""

    def __init__(self, root: Path, runtime_factory: RuntimeFactory) -> None:
        if not root.is_absolute():
            raise ValueError("The managed workspace root must be absolute.")
        if root.exists() and root.is_symlink():
            raise ValueError("The managed workspace root cannot be a symbolic link.")
        try:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            if not root.is_dir():
                raise ValueError("The managed workspace root must be a directory.")
            self._root = root.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"The managed workspace root is unavailable: {error}") from error
        self._runtime_factory = runtime_factory
        self._lock = RLock()
        self._active: Workspace | None = None
        self._runtimes: dict[str, Any] = {}

    @property
    def root(self) -> Path:
        return self._root

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Hold selection stable while one MCP operation runs."""
        with self._lock:
            yield

    def _descriptor(self, path: Path) -> Workspace:
        if path.is_symlink():
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_PATH,
                    message="Managed workspaces cannot be symbolic links.",
                )
            )
        if not path.is_dir():
            raise ContractError(
                Error(code=ErrorCode.NOT_FOUND, message="The requested workspace does not exist.")
            )
        SqliteWorkspaceStore.open(path)
        try:
            return Workspace(name=path.name, root=path.resolve(strict=True))
        except ValidationError as error:
            raise ContractError(
                Error(
                    code=ErrorCode.CORRUPT_WORKSPACE,
                    message="A managed workspace has an invalid directory name.",
                )
            ) from error

    def _list_locked(self) -> tuple[Workspace, ...]:
        try:
            directories = tuple(
                entry for entry in self._root.iterdir() if entry.is_dir() or entry.is_symlink()
            )
        except OSError as error:
            raise _storage_failure(error) from error
        workspaces = tuple(
            self._descriptor(entry)
            for entry in sorted(directories, key=lambda item: (item.name.casefold(), item.name))
        )
        names = tuple(
            unicodedata.normalize("NFC", workspace.name).casefold() for workspace in workspaces
        )
        if len(set(names)) != len(names):
            raise ContractError(
                Error(
                    code=ErrorCode.CORRUPT_WORKSPACE,
                    message="Managed workspace directory names collide.",
                )
            )
        return workspaces

    def create_workspace(self, request: WorkspaceRequest) -> OperationResult[Workspace]:
        """Create one empty workspace without changing the current selection."""
        with self._lock:
            path = self._root / request.name
            try:
                if path.exists() or path.is_symlink():
                    raise ContractError(
                        Error(
                            code=ErrorCode.CONFLICT,
                            message="A workspace already uses that name.",
                        )
                    )
                SqliteWorkspaceStore.create(path)
                workspace = Workspace(name=request.name, root=path.resolve(strict=True))
            except ContractError as error:
                return _failure(error.error)
            except (OSError, ValidationError) as error:
                failure = (
                    _storage_failure(error)
                    if isinstance(error, OSError)
                    else ContractError(
                        Error(
                            code=ErrorCode.INVALID_MODEL,
                            message="The workspace name is invalid.",
                        )
                    )
                )
                return _failure(failure.error)
            return _success(workspace)

    def list_workspaces(self) -> OperationResult[tuple[Workspace, ...]]:
        """List valid workspace directories below the managed root."""
        with self._lock:
            try:
                return _success(self._list_locked())
            except ContractError as error:
                return _failure(error.error)

    def select_workspace(self, request: WorkspaceRequest) -> OperationResult[Workspace]:
        """Open one workspace and make its services active for later tool calls."""
        with self._lock:
            try:
                workspace = self._descriptor(self._root / request.name)
                key = str(workspace.root)
                runtime = self._runtimes.get(key)
                if runtime is None:
                    runtime = self._runtime_factory(workspace.root)
                    self._runtimes[key] = runtime
            except ContractError as error:
                return _failure(error.error)
            except (OSError, ValueError, TypeError) as error:
                return _failure(
                    Error(
                        code=ErrorCode.EXECUTION_FAILED,
                        message=f"The workspace services could not be opened: {error}",
                    )
                )
            self._active = workspace
            return _success(workspace)

    def current_workspace(self) -> OperationResult[Workspace | None]:
        """Return the current selection without changing it."""
        with self._lock:
            return _success(self._active)

    def current_target(self, attribute: str) -> Any:
        with self._lock:
            if self._active is None:
                raise ContractError(
                    Error(
                        code=ErrorCode.INVALID_TRANSITION,
                        message="Select a workspace before using workspace-scoped tools.",
                    )
                )
            target = getattr(self._runtimes[str(self._active.root)], attribute, None)
            if target is None:
                raise ContractError(
                    Error(
                        code=ErrorCode.UNSUPPORTED_OPERATION,
                        message="This service is not enabled for the selected workspace.",
                    )
                )
            return target

    def managed_bindings(
        self,
        *,
        sessions: bool = False,
        models: bool = False,
        workflow: bool = False,
        general: bool = False,
    ) -> Bindings:
        """Build typed catalog bindings backed by the current workspace runtime."""
        from .catalog import Bindings

        if workflow:
            sessions = True
            models = True
        store = cast(Any, _ServiceProxy(self, "workspaces"))
        session_proxy = cast(Any, _ServiceProxy(self, "sessions")) if sessions else None
        import_proxy = cast(Any, _ServiceProxy(self, "imports")) if models else None
        synthetic_proxy = cast(Any, _ServiceProxy(self, "synthetic_models")) if models else None
        renderer_proxy = cast(Any, _ServiceProxy(self, "renderer")) if workflow else None
        jobs_proxy = cast(Any, _ServiceProxy(self, "jobs")) if workflow else None
        views_proxy = cast(Any, _ServiceProxy(self, "views")) if workflow else None
        wells_proxy = cast(Any, _ServiceProxy(self, "wells")) if workflow else None
        schedules_proxy = cast(Any, _ServiceProxy(self, "schedules")) if workflow else None
        flow_proxy = cast(Any, _ServiceProxy(self, "flow")) if workflow else None
        results_proxy = cast(Any, _ServiceProxy(self, "results")) if workflow else None
        return Bindings(
            workspaces=store,
            sessions=session_proxy,
            renderer=renderer_proxy,
            jobs=jobs_proxy,
            views=views_proxy,
            imports=import_proxy,
            synthetic_models=synthetic_proxy,
            wells=wells_proxy,
            schedules=schedules_proxy,
            flow=flow_proxy,
            results=results_proxy,
            workspace_manager=self,
            arrays=cast(Any, _ServiceProxy(self, "arrays")) if general else None,
            general_models=cast(Any, _ServiceProxy(self, "general_models")) if general else None,
            general_compilation=cast(Any, _ServiceProxy(self, "general_compilation"))
            if general
            else None,
            general_physics=cast(Any, _ServiceProxy(self, "general_physics")) if general else None,
            general_schedules=cast(Any, _ServiceProxy(self, "general_schedules"))
            if general
            else None,
            general_well_models=cast(Any, _ServiceProxy(self, "general_well_models"))
            if general
            else None,
            general_native_wells=cast(Any, _ServiceProxy(self, "general_native_wells"))
            if general and sessions
            else None,
            general_grids=cast(Any, _ServiceProxy(self, "general_grids"))
            if general and sessions
            else None,
        )
