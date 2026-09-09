"""Internal application boundary for session coordination."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ProcessIdentity, ProjectState


@dataclass(frozen=True)
class NativeObject:
    kind: ObjectKind
    address: str
    name: str
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProjectSnapshot:
    """Comparable observations, without a claim of complete project change history."""

    root_address: str
    objects: tuple[NativeObject, ...]


class Application(Protocol):
    @property
    def endpoint(self) -> Endpoint: ...

    @property
    def process(self) -> ProcessIdentity: ...

    def verify_process(self) -> ProcessIdentity: ...

    def snapshot(self) -> ProjectSnapshot: ...

    def open_project(self, path: Path) -> None: ...

    def save_project(self, path: Path) -> None: ...

    def close_project(self) -> None: ...

    def disconnect(self) -> None:
        """Release the client channel without terminating the application."""
        ...

    def terminate(self) -> None:
        """Verify the recorded process lifetime and confirm its exit."""
        ...


class ApplicationFactory(Protocol):
    def launch(self, executable: Path) -> Application: ...

    def attach(self, endpoint: Endpoint) -> Application: ...


@dataclass(frozen=True)
class ApplicationAccess:
    """Resolved native identities, valid only inside the session access context."""

    application: Application
    project: ProjectState
    objects: tuple[NativeObject, ...]


@dataclass(frozen=True)
class ProjectMutation[T]:
    """A completed callback value and the session's refreshed object mapping."""

    value: T
    access: ApplicationAccess
