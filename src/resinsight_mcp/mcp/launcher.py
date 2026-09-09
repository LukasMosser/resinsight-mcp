"""Compose the shipped services from explicit local configuration."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.models.synthetic import SyntheticModelService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .catalog import Bindings


class ConfigurationError(ValueError):
    """The launcher cannot provide the requested service configuration."""


def _native_factory(log_directory: Path) -> ApplicationFactory:
    try:
        from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
    except (ImportError, OSError) as error:
        raise ConfigurationError(
            "Cannot load ResInsight support. Install the resinsight extra and its native "
            f"dependencies: {error}"
        ) from error
    if shutil.which("lsof") is None:
        raise ConfigurationError("ResInsight session configuration requires lsof on PATH.")
    return RipsApplicationFactory(log_directory)


@dataclass(frozen=True)
class LauncherConfiguration:
    workspace_root: Path
    create_workspace: bool = False
    resinsight_log_directory: Path | None = None
    enable_models: bool = False

    def __post_init__(self) -> None:
        if not self.workspace_root.is_absolute():
            raise ConfigurationError("The workspace root must be an absolute path.")
        directory = self.resinsight_log_directory
        if directory is None:
            return
        if not directory.is_absolute():
            raise ConfigurationError("The ResInsight log directory must be an absolute path.")
        if not directory.is_dir() or not os.access(directory, os.W_OK | os.X_OK):
            raise ConfigurationError("The ResInsight log directory must exist and be writable.")

    def bindings(self) -> Bindings:
        """Check native dependencies before opening or creating the workspace."""
        if self.enable_models:
            OpmImportService.check_dependencies()
        factory = (
            _native_factory(self.resinsight_log_directory)
            if self.resinsight_log_directory is not None
            else None
        )
        open_store = (
            SqliteWorkspaceStore.create if self.create_workspace else SqliteWorkspaceStore.open
        )
        workspaces = open_store(self.workspace_root)
        sessions = ResInsightSessionService(workspaces, factory) if factory is not None else None
        return Bindings(
            workspaces=workspaces,
            sessions=sessions,
            imports=OpmImportService(workspaces) if self.enable_models else None,
            synthetic_models=SyntheticModelService(workspaces) if self.enable_models else None,
        )
