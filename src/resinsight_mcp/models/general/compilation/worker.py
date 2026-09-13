"""Run compilation and official OPM parsing inside one isolated process."""

import importlib.metadata
import json
import math
import os
import resource
import sys
import time
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import ArrayService, AuthoringPolicy
from resinsight_mcp.models.general.physics.service import GeneralPhysics
from resinsight_mcp.models.general.schedules.service import GeneralSchedules
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.models.general.wells import GeneralWellModels
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .render import render
from .service import GeneralCompilation
from .verify import verify


def run(root: Path, directory: Path) -> dict:
    os.environ["TZ"] = "UTC"
    time.tzset()
    import opm.io.deck  # noqa: F401
    from opm.io.ecl_state import EclipseState
    from opm.io.parser import ParseContext, Parser, action
    from opm.io.schedule import Schedule

    version = importlib.metadata.version("opm")
    if version != "2025.10":
        raise ValueError(f"General preparation requires OPM 2025.10, not {version}.")
    policy = AuthoringPolicy.model_validate_json((directory / "policy.json").read_text())
    # The child retains a CPU deadline if its controller exits unexpectedly.
    seconds = max(1, math.ceil(policy.parser_timeout_seconds))
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    reference = ArtifactRef.model_validate_json((directory / "request.json").read_text())
    models = GeneralModelService(ArrayService(SqliteWorkspaceStore.open(root), policy))
    service = GeneralCompilation(
        GeneralSchedules(GeneralWellModels(models)), GeneralPhysics(models), root
    )
    assembly = service.manifest(reference)
    render(service, assembly, directory)
    deck = Parser().parse(str(directory / "MODEL.DATA"), ParseContext([("*", action.throw)]))
    state = EclipseState(deck)
    schedule = Schedule(deck, state)
    return verify(service, assembly, deck, state, schedule, version).model_dump(mode="json")


def main() -> None:
    root, directory = (Path(value) for value in sys.argv[1:])
    try:
        payload = run(root, directory)
    except (
        ContractError,
        ValueError,
        RuntimeError,
        KeyError,
        IndexError,
        ImportError,
        OSError,
    ) as error:
        message = error.error.message if isinstance(error, ContractError) else str(error)
        payload = {"error": message[:4000]}
    (directory / "validation.json").write_text(json.dumps(payload))


if __name__ == "__main__":
    main()
