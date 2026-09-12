"""Verify array ranges, geological geometry, ownership, and durable authoring."""

import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.general.arrays import (
    ArrayJoinRequest,
    ArrayRangeRequest,
    ArrayService,
    ArrayWriteRequest,
    AuthoringPolicy,
    value,
)
from resinsight_mcp.models.general.records import CornerPointRequest, GeologicalRequest
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def specification(
    session: SessionId, nx: int = 20, ny: int = 30, nz: int = 20
) -> GeologicalRequest:
    return GeologicalRequest.model_validate_json(
        json.dumps(
            {
                "session_id": str(session),
                "name": "Faulted layers",
                "shape": {"nx": nx, "ny": ny, "nz": nz},
                "extent_x": 2000,
                "extent_y": 3000,
                "top_depth": 1500,
                "thickness": 200,
                "length_unit": "m",
                "datum": "Local positive-down datum",
                "faults": [{"intercept": 1000, "throw": 75}],
                "bands": [
                    {"bottom_fraction": 0.5, "porosity": 0.2, "permeability_md": 1000},
                    {"bottom_fraction": 1, "porosity": 0.1, "permeability_md": 10},
                ],
            }
        )
    )


@pytest.fixture
def models(tmp_path: Path) -> GeneralModelService:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    value(store.create_session(Session(session_id=SessionId.new(), name="Authoring")))
    return GeneralModelService(ArrayService(store, AuthoringPolicy(request_values=1000)))


def session(models: GeneralModelService) -> SessionId:
    return value(models.store.list_sessions())[0].session_id


def test_range_reads_only_intersecting_chunks(models: GeneralModelService, monkeypatch) -> None:
    arrays = models.arrays
    array = arrays.write(session(models), np.arange(3001, dtype=np.float64), "m")
    descriptor = arrays.descriptor(array.artifact)
    opened = []
    original = models.store.open_artifact

    @contextmanager
    def tracked(ref):
        opened.append(ref)
        with original(ref) as stream:
            yield stream

    monkeypatch.setattr(models.store, "open_artifact", tracked)
    result = value(arrays.query(ArrayRangeRequest(array=array.artifact, offset=998, count=5)))
    assert result.values == (998, 999, 1000, 1001, 1002)
    assert result.next_offset == 1003
    assert descriptor.chunks[0].artifact in opened
    assert descriptor.chunks[1].artifact in opened
    assert descriptor.chunks[2].artifact not in opened
    assert descriptor.chunks[3].artifact not in opened


def test_join_reuses_parts_and_reopens(models: GeneralModelService, tmp_path: Path) -> None:
    arrays = models.arrays
    first = value(
        arrays.upload(
            ArrayWriteRequest(
                session_id=session(models), dtype="int64", unit="1", values=(1.0, 0.0, 1.0)
            )
        )
    )
    joined = value(
        arrays.join(
            ArrayJoinRequest(session_id=session(models), parts=(first.artifact, first.artifact))
        )
    )
    reopened = ArrayService(SqliteWorkspaceStore.open(tmp_path / "workspace"), arrays.policy)
    assert value(
        reopened.query(ArrayRangeRequest(array=joined.artifact, offset=2, count=4))
    ).values == (1, 1, 0, 1)
    assert {chunk.artifact for chunk in arrays.descriptor(joined.artifact).chunks} == {
        chunk.artifact for chunk in arrays.descriptor(first.artifact).chunks
    }


def test_fault_throw_layer_order_and_explicit_inputs(models: GeneralModelService) -> None:
    generated = value(models.generate(specification(session(models))))
    assert generated.shape.cells == 12000
    assert generated.active_cells == 12000
    corners = models.cell_corners(generated.model, (9, 10, 6000))
    assert corners[10][0][2] - corners[9][1][2] == 75
    assert corners[6000][0][2] == 1600
    manifest = models.manifest(generated.model)
    cloned = value(
        models.create(
            CornerPointRequest.model_validate(
                manifest.model_dump(exclude={"version", "source", "active_cells"})
            )
        )
    )
    assert cloned.model != generated.model
    assert models.cell_corners(cloned.model, (9, 10, 6000)) == corners
    permeability = next(field.array for field in manifest.fields if field.name == "PERMX")
    assert value(
        models.arrays.query(ArrayRangeRequest(array=permeability, offset=5999, count=2))
    ).values == (1000, 10)


def test_fold_channel_and_inactive_boundary(models: GeneralModelService) -> None:
    request = specification(session(models)).model_dump(mode="json")
    request.update(
        active_ellipse=True,
        thickness_variation=0.2,
        folds=[dict(amplitude=100, wavelength_x=2000, wavelength_y=3000)],
        channel=dict(
            center_y=1500,
            amplitude=300,
            wavelength=2000,
            width=200,
            permeability_multiplier=4,
            porosity_increment=0.03,
        ),
    )
    model = value(models.generate(GeologicalRequest.model_validate_json(json.dumps(request))))
    assert 0 < model.active_cells < model.shape.cells
    assert next(item.array for item in model.arrays if item.name == "PERMX").maximum > 1000
    assert next(item.array for item in model.arrays if item.name == "PORO").maximum > 0.2
    depths = models.cell_corners(model.model, (5, 15))
    assert depths[5][0][2] != depths[15][0][2] - 75


def test_memory_policy_rejects_before_publication(models: GeneralModelService) -> None:
    limited = GeneralModelService(ArrayService(models.store, AuthoringPolicy(working_memory_mib=1)))
    result = limited.generate(specification(session(models)))
    assert isinstance(result.outcome, Failure)
    assert "configured budget" in result.outcome.error.message
    assert value(models.store.list_artifacts(session(models))) == ()


def test_cross_session_arrays_and_invalid_geometry_are_rejected(
    models: GeneralModelService,
) -> None:
    generated = value(models.generate(specification(session(models), 2, 2, 2)))
    manifest = models.manifest(generated.model)
    request = CornerPointRequest.model_validate(
        manifest.model_dump(exclude={"version", "source", "active_cells"})
    )
    other = Session(session_id=SessionId.new(), name="Other")
    value(models.store.create_session(other))
    foreign = models.arrays.write(other.session_id, np.ones(8, dtype=np.int64), "1")
    assert isinstance(
        models.create(request.model_copy(update={"actnum": foreign.artifact})).outcome, Failure
    )
    inverted = models.arrays.write(request.session_id, -models.arrays.read(request.zcorn), "m")
    result = models.create(request.model_copy(update={"zcorn": inverted.artifact}))
    assert isinstance(result.outcome, Failure)
    assert "bottoms" in result.outcome.error.message


def test_policy_limits_messages_but_not_total_array_size(models: GeneralModelService) -> None:
    arrays = models.arrays
    first = arrays.write(session(models), np.arange(10000, dtype=np.float64), "m")
    refused = arrays.query(ArrayRangeRequest(array=first.artifact, offset=0, count=4097))
    assert isinstance(refused.outcome, Failure)
    assert (
        value(
            arrays.query(ArrayRangeRequest(array=first.artifact, offset=9999, count=1))
        ).next_offset
        is None
    )
