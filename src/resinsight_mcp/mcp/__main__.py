"""Launch workspace and configured ResInsight services over local standard input and output."""

import argparse
import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError

from .launcher import ConfigurationError, LauncherConfiguration
from .stdio import _serve_stdio_from
from .workspace_manager import WorkspaceManager


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    workspace_paths = parser.add_mutually_exclusive_group(required=True)
    workspace_paths.add_argument("--workspace-root", type=Path)
    workspace_paths.add_argument("--workspaces-root", type=Path)
    parser.add_argument("--create-workspace", action="store_true")
    parser.add_argument("--enable-general-models", action="store_true")
    parser.add_argument("--authoring-policy", type=Path)
    parser.add_argument(
        "--enable-models",
        action="store_true",
        help="Enable validated FIELD model import, creation, inspection, and preparation.",
    )
    parser.add_argument(
        "--enable-opm-workflow",
        action="store_true",
        help="Enable the bounded OPM model, well, job, result, and native image workflow.",
    )
    parser.add_argument(
        "--docker-executable",
        type=Path,
        help="Use an explicit absolute Docker client path for the OPM workflow.",
    )
    parser.add_argument(
        "--resinsight-log-directory",
        type=Path,
        help="Enable native session tools with an absolute, existing application log directory.",
    )
    arguments = parser.parse_args()
    if arguments.workspaces_root is not None and arguments.create_workspace:
        parser.error("--create-workspace requires --workspace-root.")
    logging.basicConfig(level=logging.INFO)
    try:
        if arguments.workspace_root is not None:
            configuration = LauncherConfiguration(
                workspace_root=arguments.workspace_root,
                create_workspace=arguments.create_workspace,
                resinsight_log_directory=arguments.resinsight_log_directory,
                enable_general_models=arguments.enable_general_models,
                authoring_policy=arguments.authoring_policy,
                enable_models=arguments.enable_models,
                enable_opm_workflow=arguments.enable_opm_workflow,
                docker_executable=arguments.docker_executable,
            )
            asyncio.run(_serve_stdio_from(configuration.bindings))
            return

        assert arguments.workspaces_root is not None
        configuration = LauncherConfiguration(
            workspace_root=arguments.workspaces_root,
            resinsight_log_directory=arguments.resinsight_log_directory,
            enable_general_models=arguments.enable_general_models,
            authoring_policy=arguments.authoring_policy,
            enable_models=arguments.enable_models,
            enable_opm_workflow=arguments.enable_opm_workflow,
            docker_executable=arguments.docker_executable,
        )
        manager = WorkspaceManager(
            arguments.workspaces_root,
            lambda workspace_root: replace(configuration, workspace_root=workspace_root).bindings(),
        )
        asyncio.run(
            _serve_stdio_from(
                lambda: manager.managed_bindings(
                    sessions=arguments.resinsight_log_directory is not None,
                    models=arguments.enable_models or arguments.enable_opm_workflow,
                    workflow=arguments.enable_opm_workflow,
                    general=arguments.enable_general_models,
                )
            )
        )
    except (ConfigurationError, ContractError, OSError, ValueError) as error:
        parser.exit(2, f"Configuration failed: {error}\n")


if __name__ == "__main__":
    main()
