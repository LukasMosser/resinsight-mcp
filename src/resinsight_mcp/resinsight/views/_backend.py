"""Native view operations stay separate from observation storage."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from resinsight_mcp.contracts.observations import Camera, ViewContext
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess


@dataclass(frozen=True)
class NativeViewState:
    address: str
    camera: Camera
    vertical_exaggeration: float


class NativeView(Protocol):
    def validate(self, context: ViewContext) -> None:
        """Reject unsupported settings before changing the native view."""
        ...

    def apply(self, context: ViewContext) -> ViewContext:
        """Apply the settings and return their observed native context."""
        ...

    def inspect(self, context: ViewContext) -> ViewContext:
        """Read current settings using the supplied trusted result identity."""
        ...

    def export(self, folder: Path, width: int, height: int) -> None: ...


class ViewBackend(Protocol):
    def list_views(
        self, access: ApplicationAccess, case_address: str
    ) -> tuple[NativeViewState, ...]:
        """Read view ownership and camera settings without adopting a scene."""
        ...

    def select(self, access: ApplicationAccess, context: ViewContext) -> NativeView:
        """Resolve the exact native case, view, and selected well identities."""
        ...
