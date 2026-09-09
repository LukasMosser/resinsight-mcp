"""Inject startup conditions only into a launcher test subprocess.

Tests copy this file as sitecustomize.py on an explicit temporary Python path.
The normal test process and native protocol fixture do not import this hook.
"""

import builtins
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from types import ModuleType
from unittest.mock import patch

_original_import = builtins.__import__


def _import(
    name: str,
    globals: Mapping[str, object] | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = (),
    level: int = 0,
) -> ModuleType:
    mode = os.environ.get("LAUNCHER_TEST_STARTUP")
    if mode == "missing-rips" and name == "rips":
        raise ImportError("Launcher fixture hides optional rips")
    module = _original_import(name, globals, locals, fromlist, level)
    if mode == "missing-workflow-interface" and name == "rips":
        patch.object(module.Project, "export_prepared_input_grid", None, create=True).start()
    if mode in {"workflow-ready", "workflow-docker-failure"} and name == "_workflow":
        from resinsight_mcp.simulators.opm import FlowConfiguration

        def workflow_dependencies(docker_executable):
            configuration = (
                FlowConfiguration(docker=docker_executable)
                if docker_executable is not None
                else FlowConfiguration()
            )
            if mode == "workflow-docker-failure":
                configuration.check_dependencies()
            return configuration

        patch.object(module, "check_dependencies", side_effect=workflow_dependencies).start()
    if mode == "missing-model-dependencies" and name == "resinsight_mcp.models.imports":
        from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode

        patch.object(
            module.OpmImportService,
            "check_dependencies",
            side_effect=ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="OPM import dependencies are unavailable: fixture dependency failure.",
                )
            ),
        ).start()
    if mode == "noisy" and name == "resinsight_mcp.resinsight.sessions.rips":
        print("Launcher fixture native import", flush=True)
        factory = module.RipsApplicationFactory

        def noisy_factory(*args, **kwargs):
            print("Launcher fixture native construction", flush=True)
            subprocess.run(
                [sys.executable, "-S", "-c", "print('Launcher fixture inherited output')"],
                check=True,
            )
            return factory(*args, **kwargs)

        patch.object(module, "RipsApplicationFactory", side_effect=noisy_factory).start()
    return module


patch.object(builtins, "__import__", side_effect=_import).start()
