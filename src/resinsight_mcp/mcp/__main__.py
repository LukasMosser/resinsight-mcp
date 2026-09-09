"""Launch workspace and configured ResInsight services over local standard input and output."""

import argparse
import asyncio
import logging
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError

from .launcher import ConfigurationError, LauncherConfiguration
from .stdio import _serve_stdio_from


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--create-workspace", action="store_true")
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
    logging.basicConfig(level=logging.INFO)
    try:
        configuration = LauncherConfiguration(
            workspace_root=arguments.workspace_root,
            create_workspace=arguments.create_workspace,
            resinsight_log_directory=arguments.resinsight_log_directory,
            enable_models=arguments.enable_models,
            enable_opm_workflow=arguments.enable_opm_workflow,
            docker_executable=arguments.docker_executable,
        )
        asyncio.run(_serve_stdio_from(configuration.bindings))
    except (ConfigurationError, ContractError, OSError) as error:
        parser.exit(2, f"Configuration failed: {error}\n")


if __name__ == "__main__":
    main()
