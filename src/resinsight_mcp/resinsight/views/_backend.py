"""Native view operations stay separate from observation storage."""

from pathlib import Path
from typing import Protocol

from resinsight_mcp.contracts.observations import ViewContext
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess


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
    def select(self, access: ApplicationAccess, context: ViewContext) -> NativeView:
        """Resolve the exact native case, view, and selected well identities."""
        ...
