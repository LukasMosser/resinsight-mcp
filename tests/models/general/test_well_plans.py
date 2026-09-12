"""Verify scalable well inputs, model ownership, and immutable plan history."""

from pathlib import Path

import numpy as np
import pytest
from test_authoring import specification

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.general.arrays import ArrayService, AuthoringPolicy, value
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.models.general.wells import GeneralWellModels, WellGeometry, WellPlanRequest
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def setup(tmp_path: Path):
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = SessionId.new()
    value(store.create_session(Session(session_id=session, name="Wells")))
    models = GeneralModelService(ArrayService(store, AuthoringPolicy(request_values=64)))
    model = value(models.generate(specification(session, 2, 2, 2)))
    return GeneralWellModels(models), model.model


def request(plans, model, unit="m", name="UnrestrictedWellName"):
    arrays = plans.arrays
    points = np.column_stack((np.full(151, 10), np.full(151, 10), np.arange(151)))
    intervals = np.column_stack((np.arange(150), np.arange(150) + 0.5, np.full(150, 0.2)))
    return WellPlanRequest(
        model=model,
        name=name,
        role="producer",
        sampling_distance=0.1,
        targets=arrays.write(model.session_id, points.astype(np.float64).ravel(), unit).artifact,
        intervals=arrays.write(model.session_id, intervals.ravel(), unit).artifact,
        skins=arrays.write(model.session_id, np.full(150, -0.5), "1").artifact,
    )


def test_multipart_plans_have_no_fixed_target_interval_or_well_count(tmp_path):
    plans, model = setup(tmp_path)
    source = request(plans, model)
    for index in range(33):
        plan = value(plans.define(source.model_copy(update={"name": f"WELL_{index}"})))
        assert plan.model == model
    geometry = plans.geometry(plan)
    assert len(geometry.targets) == 151
    assert len(geometry.intervals) == 150
    assert geometry.intervals[0] == (0, 0.5, 0.2, -0.5)
    assert len(plans.arrays.descriptor(plan.targets).chunks) > 1
    reopened = GeneralWellModels(
        GeneralModelService(
            ArrayService(SqliteWorkspaceStore.open(tmp_path / "workspace"), plans.arrays.policy)
        )
    )
    assert value(reopened.inspect(plan.artifact)) == plan


def test_child_plan_preserves_parent_and_rejects_other_well(tmp_path):
    plans, model = setup(tmp_path)
    source = request(plans, model)
    parent = value(plans.define(source))
    child = value(
        plans.define(source.model_copy(update={"parent": parent.artifact, "sampling_distance": 1}))
    )
    assert child.artifact != parent.artifact
    assert child.parent == parent.artifact
    assert value(plans.inspect(parent.artifact)).sampling_distance == 0.1
    assert isinstance(
        plans.define(
            source.model_copy(update={"parent": parent.artifact, "name": "OTHER"})
        ).outcome,
        Failure,
    )


def test_wrong_units_and_foreign_model_fail_before_native_use(tmp_path):
    plans, model = setup(tmp_path)
    assert isinstance(plans.define(request(plans, model, unit="ft")).outcome, Failure)
    source = request(plans, model)
    foreign = model.model_copy(update={"session_id": SessionId.new()})
    with pytest.raises(ValueError, match="model session"):
        WellPlanRequest(**source.model_dump(exclude={"model"}), model=foreign)


@pytest.mark.parametrize(
    "intervals", [((0, 0, 0.2, 0),), ((0, 2, 0.2, 0), (1, 3, 0.2, 0)), ((-1, 2, 0.2, 0),)]
)
def test_invalid_interval_geometry_is_rejected(intervals):
    with pytest.raises(ValueError):
        WellGeometry(
            name="WELL", targets=((0, 0, 0), (0, 0, 5)), intervals=intervals, sampling_distance=1
        )


def test_native_samples_must_preserve_endpoints_and_measured_depth():
    geometry = WellGeometry(
        name="WELL",
        targets=((0, 0, 0), (0, 0, 5)),
        intervals=((0, 5, 0.2, 0),),
        sampling_distance=1,
    )
    geometry.require_trajectory(((0, 0, 0, 0), (0, 0, 5, 5)))
    for samples in (
        ((0, 0, 0, 0), (1, 0, 5, 5)),
        ((0, 0, 0, 1), (0, 0, 5, 6)),
        ((0, 0, 0, 0), (0, 0, 5, 4)),
    ):
        with pytest.raises(ValueError):
            geometry.require_trajectory(samples)
