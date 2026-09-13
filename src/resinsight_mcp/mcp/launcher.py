"""Compose the shipped services from explicit local configuration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.models.synthetic import SyntheticModelService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .catalog import Bindings

if TYPE_CHECKING:
    from resinsight_mcp.models.general.arrays import AuthoringPolicy


class ConfigurationError(ValueError):
    """The launcher cannot provide the requested service configuration."""


def _native_factory(
    log_directory: Path, policy: AuthoringPolicy | None = None
) -> ApplicationFactory:
    try:
        from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
    except (ImportError, OSError) as error:
        raise ConfigurationError(
            "Cannot load ResInsight support. Install the resinsight extra and its native "
            f"dependencies: {error}"
        ) from error
    if shutil.which("lsof") is None:
        raise ConfigurationError("ResInsight session configuration requires lsof on PATH.")
    if policy is None:
        return RipsApplicationFactory(log_directory)
    return RipsApplicationFactory(
        log_directory,
        launch_timeout=policy.native_launch_timeout_seconds,
        rpc_timeout=policy.native_rpc_timeout_seconds,
    )


@dataclass(frozen=True)
class LauncherConfiguration:
    workspace_root: Path
    create_workspace: bool = False
    resinsight_log_directory: Path | None = None
    enable_general_models: bool = False
    authoring_policy: Path | None = None
    enable_models: bool = False
    enable_opm_workflow: bool = False
    docker_executable: Path | None = None

    def __post_init__(self) -> None:
        if self.authoring_policy is not None and not self.enable_general_models:
            raise ConfigurationError("An authoring policy requires general model support.")
        if not self.workspace_root.is_absolute():
            raise ConfigurationError("The workspace root must be an absolute path.")
        if self.enable_opm_workflow and self.resinsight_log_directory is None:
            raise ConfigurationError("The OPM workflow requires a ResInsight log directory.")
        if self.docker_executable is not None and not self.enable_opm_workflow:
            raise ConfigurationError("A Docker executable requires the OPM workflow configuration.")
        if self.docker_executable is not None and not self.docker_executable.is_absolute():
            raise ConfigurationError("The Docker executable must use an absolute path.")
        directory = self.resinsight_log_directory
        if directory is None:
            return
        if not directory.is_absolute():
            raise ConfigurationError("The ResInsight log directory must be an absolute path.")
        if not directory.is_dir() or not os.access(directory, os.W_OK | os.X_OK):
            raise ConfigurationError("The ResInsight log directory must exist and be writable.")

    def bindings(self) -> Bindings:
        """Check native dependencies before opening or creating the workspace."""
        policy = self._policy()
        models_enabled = self.enable_models or self.enable_opm_workflow
        if models_enabled:
            OpmImportService.check_dependencies()
        factory = (
            _native_factory(self.resinsight_log_directory, policy)
            if self.resinsight_log_directory is not None
            else None
        )
        flow_configuration = None
        if self.enable_opm_workflow:
            from ._workflow import check_dependencies

            flow_configuration = check_dependencies(self.docker_executable)
        open_store = (
            SqliteWorkspaceStore.create if self.create_workspace else SqliteWorkspaceStore.open
        )
        workspaces = open_store(self.workspace_root)
        sessions = ResInsightSessionService(workspaces, factory) if factory is not None else None
        if flow_configuration is not None:
            from ._workflow import workflow_bindings

            assert sessions is not None
            bindings = workflow_bindings(
                self.workspace_root.resolve(), workspaces, sessions, flow_configuration
            )
            return self._general(bindings, sessions, policy)
        return self._general(
            Bindings(
                workspaces=workspaces,
                sessions=sessions,
                imports=OpmImportService(workspaces) if models_enabled else None,
                synthetic_models=SyntheticModelService(workspaces) if models_enabled else None,
            ),
            sessions,
            policy,
        )

    def _policy(self) -> AuthoringPolicy | None:
        if not self.enable_general_models:
            return None
        from resinsight_mcp.models.general.arrays import AuthoringPolicy

        if self.authoring_policy is not None and not self.authoring_policy.is_absolute():
            raise ConfigurationError("The authoring policy path must be absolute.")
        return (
            AuthoringPolicy.model_validate_json(self.authoring_policy.read_text())
            if self.authoring_policy is not None
            else AuthoringPolicy()
        )

    def _general(
        self,
        bindings: Bindings,
        sessions: ResInsightSessionService | None,
        policy: AuthoringPolicy | None,
    ) -> Bindings:
        if policy is None:
            return bindings
        from resinsight_mcp.models.general.arrays import ArrayService
        from resinsight_mcp.models.general.physics.service import GeneralPhysics
        from resinsight_mcp.models.general.schedules.service import GeneralSchedules
        from resinsight_mcp.models.general.service import GeneralModelService
        from resinsight_mcp.models.general.wells import GeneralWellModels

        arrays = ArrayService(bindings.workspaces, policy)
        models = GeneralModelService(arrays)
        plans = GeneralWellModels(models)
        native = None
        wells = None
        if sessions is not None:
            from resinsight_mcp.resinsight.general.service import GeneralGridService
            from resinsight_mcp.resinsight.general.wells import GeneralNativeWells
            from resinsight_mcp.resinsight.wells.rips import RipsGeometryBackend

            native = GeneralGridService(models, sessions, self.workspace_root.resolve())
            wells = GeneralNativeWells(plans, native, RipsGeometryBackend())
        return replace(
            bindings,
            arrays=arrays,
            general_models=models,
            general_grids=native,
            general_well_models=plans,
            general_schedules=GeneralSchedules(plans),
            general_physics=GeneralPhysics(models),
            general_native_wells=wells,
        )
