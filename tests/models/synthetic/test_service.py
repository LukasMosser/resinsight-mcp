"""Generated models preserve typed inputs and pass the existing import profile."""

import json
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.errors import (
    Error,
    ErrorCode,
    Failure,
    MutationEffect,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Backend, PreparationRequest, Session
from resinsight_mcp.contracts.wells import WellStatus
from resinsight_mcp.contracts.workspace import Artifact
from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.models.synthetic.deck import read_grid_id, read_specification
from resinsight_mcp.models.synthetic.records import (
    SyntheticModelRequest,
    SyntheticModelSpec,
)
from resinsight_mcp.models.synthetic.reference import reference_specification
from resinsight_mcp.models.synthetic.service import SyntheticModelService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump_json()
    return result.outcome.value


def test_generated_revision_preserves_specification_and_prepares_after_reopen(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    store = SqliteWorkspaceStore.create(workspace)
    session = value(store.create_session(Session(session_id=SessionId.new(), name="Generated")))
    specification = reference_specification()
    receipt = value(
        SyntheticModelService(store).create_model(
            SyntheticModelRequest(
                session_id=session.session_id, datum="SPE1 local datum", specification=specification
            )
        )
    )
    assert receipt.imported.summary.dimensions == (10, 10, 3)
    assert receipt.imported.summary.active_cells == 300
    assert set(receipt.imported.summary.wells) == {"PROD", "INJ"}
    assert receipt.imported.summary.elapsed_days == 2
    assert receipt.active_cells.cell_at(299).index == specification.wells[0].cell
    assert receipt.active_cells.cell_at(0).index == specification.wells[1].cell
    with store.open_artifact(receipt.specification_source) as source:
        text = source.read().decode("utf-8")
        restored = read_specification(text)
    assert restored == specification
    assert read_grid_id(text) == receipt.active_cells.grid_id
    saved_deck = tmp_path / "saved.DATA"
    saved_deck.write_text(text)
    parsed = subprocess.run(
        [sys.executable, "-I", "-c", CONNECTIONS, str(saved_deck)],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed_model = json.loads(parsed.stdout)
    assert parsed_model["connections"] == {"PROD": [[9, 9, 2]], "INJ": [[0, 0, 0]]}
    assert parsed_model["cells"] == [
        [cell.i, cell.j, cell.k] for cell in receipt.active_cells.cells
    ]
    reopened = SqliteWorkspaceStore.open(workspace)
    assert (
        value(
            OpmImportService(reopened).prepare(
                PreparationRequest(
                    revision=receipt.imported.prepared.revision, backend=Backend.OPM_FLOW
                )
            )
        )
        == receipt.imported.prepared
    )


def test_unknown_session_does_not_publish_inputs(tmp_path: Path) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    result = SyntheticModelService(store).create_model(
        SyntheticModelRequest(
            session_id=SessionId.new(), datum="local datum", specification=reference_specification()
        )
    )
    assert isinstance(result.outcome, Failure)


@pytest.mark.parametrize(
    "change", ["same_name", "same_cell", "outside", "two_producers", "too_long"]
)
def test_invalid_complete_model_is_rejected(change: str) -> None:
    specification = reference_specification().model_dump()
    wells = list(specification["wells"])
    if change == "same_name":
        wells[1] = wells[1] | {"name": wells[0]["name"]}
    elif change == "same_cell":
        wells[1] = wells[1] | {"cell": wells[0]["cell"]}
    elif change == "outside":
        wells[1] = wells[1] | {"cell": {"i": 10, "j": 0, "k": 0}}
    elif change == "two_producers":
        wells[1] = wells[1] | {"control": wells[0]["control"]}
    else:
        specification["report_intervals_days"] = (3661,)
    specification["wells"] = tuple(wells)
    with pytest.raises(ValidationError):
        SyntheticModelSpec.model_validate(specification)


CONNECTIONS = """
import json
import sys
from opm.io.parser import Parser
from opm.io.ecl_state import EclipseState
from opm.io.schedule import Schedule
p = Parser().parse(sys.argv[1])
state = EclipseState(p)
s = Schedule(p, state)
g = state.grid()
print(json.dumps({
    "connections": {w.name: [[c.i, c.j, c.k] for c in w.connections()]
                    for w in s.get_wells(len(s.reportsteps) - 1)},
    "cells": [g.getIJK(index) for index in range(g.nactive)],
}))
"""


@pytest.mark.parametrize("source", ["", "-- synthetic-specification: {}\n" * 2])
def test_metadata_reader_rejects_missing_or_repeated_specifications(source: str) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        read_specification(source)


@pytest.mark.parametrize("variant", ["pressure", "shut", "water"])
def test_generated_controls_preserve_supported_modes(tmp_path: Path, variant: str) -> None:
    specification = reference_specification().model_dump()
    producer, injector = specification["wells"]
    if variant == "pressure":
        producer["control"] |= {"mode": "BHP", "oil_rate": None}
        injector["control"] |= {"mode": "BHP", "surface_rate": None}
    elif variant == "shut":
        producer["control"] |= {"status": WellStatus.SHUT}
        producer["control"]["oil_rate"]["value"] = 0
        injector["control"] |= {"status": WellStatus.SHUT}
        injector["control"]["surface_rate"]["value"] = 0
    else:
        injector["control"] |= {
            "phase": "WATER",
            "surface_rate": {"value": 100, "unit": "stb/day"},
        }
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="Controls")))
    receipt = value(
        SyntheticModelService(store).create_model(
            SyntheticModelRequest(
                session_id=session.session_id,
                datum="local datum",
                specification=SyntheticModelSpec.model_validate(specification),
            )
        )
    )
    source = tmp_path / "controls.DATA"
    with store.open_artifact(receipt.specification_source) as stream:
        source.write_text(stream.read().decode("utf-8"))
    parsed = subprocess.run(
        [sys.executable, "-I", "-c", CONTROLS, str(source)],
        capture_output=True,
        text=True,
        check=True,
    )
    controls = json.loads(parsed.stdout)
    assert controls["WCONPROD"]["CMODE"] == producer["control"]["mode"]
    assert controls["WCONINJE"]["CMODE"] == injector["control"]["mode"]
    assert controls["WCONINJE"]["TYPE"] == injector["control"]["phase"]
    assert controls["WCONPROD"]["STATUS"] == producer["control"]["status"]
    assert controls["WCONINJE"]["STATUS"] == injector["control"]["status"]
    if variant == "pressure":
        assert "ORAT" not in controls["WCONPROD"]
        assert "RATE" not in controls["WCONINJE"]
    else:
        assert controls["WCONPROD"]["ORAT"] == producer["control"]["oil_rate"]["value"]
        assert controls["WCONINJE"]["RATE"] == injector["control"]["surface_rate"]["value"]


CONTROLS = """
import json
import sys
import opm.io.deck
from opm.io.parser import Parser
p = Parser().parse(sys.argv[1])
print(json.dumps({name: {item.name(): item.value for item in p[name][0]
                        if item.valid and not item.defaulted}
                  for name in ('WCONPROD', 'WCONINJE')}))
"""


def test_import_publication_failure_retains_its_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="Failure")))

    def fail_write(artifact: Artifact, source: BinaryIO) -> OperationResult[Artifact]:
        return OperationResult(
            outcome=Failure(
                error=Error(code=ErrorCode.STORAGE_FAILED, message="Storage unavailable.")
            )
        )

    monkeypatch.setattr(store, "write_artifact", fail_write)
    result = SyntheticModelService(store).create_model(
        SyntheticModelRequest(
            session_id=session.session_id,
            datum="local datum",
            specification=reference_specification(),
        )
    )
    assert isinstance(result.outcome, Failure)
    assert result.outcome.error.code == ErrorCode.STORAGE_FAILED
    assert result.outcome.error.effect == MutationEffect.UNKNOWN
    assert "Storage unavailable" in result.outcome.error.message
    assert "publication may be incomplete" in result.outcome.error.message
    assert not value(store.list_jobs(session.session_id))
