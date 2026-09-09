"""Queries expose useful values and reject mismatched scenario identities."""

import json
from pathlib import Path
from typing import cast

import pytest

from resinsight_mcp.contracts.engineering import CellIndex
from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import JobId, RevisionId
from resinsight_mcp.results import CellQuery, CurveQuery, ResultRef, ResultsService
from resinsight_mcp.results._common import value
from resinsight_mcp.results.service import Bindings, ResultBackend, Sessions

from ._support import FixtureVerifier


def service(store, tmp_path: Path) -> ResultsService:
    return ResultsService(
        store,
        cast(Sessions, None),
        cast(Bindings, None),
        cast(ResultBackend, None),
        tmp_path / "bundles",
        FixtureVerifier(store),
    )


def reference(result):
    return ResultRef(session_id=result.model.session_id, result_id=result.result_id)


def cell(result):
    return CellQuery(
        result=reference(result), property="PRESSURE", report_time=result.report_series.reports[0]
    )


def curve(result):
    return CurveQuery(result=reference(result), scope="well", keyword="WBHP", well_name="PROD")


def test_queries_and_known_scenario_difference(store, publish, tmp_path):
    baseline, _, _ = publish()
    scenario, _, _ = publish(
        offset=10, model_ref=baseline.model.model_copy(update={"revision_id": RevisionId.new()})
    )
    results = service(store, tmp_path)
    comparison = value(results.compare_cells(cell(baseline), cell(scenario)))
    assert comparison.differences == (10, 10)
    assert comparison.legend.minimum == 100
    assert comparison.legend.maximum == 210
    assert comparison.baseline.result == baseline
    assert comparison.scenario.result == scenario
    assert baseline.grid_id != scenario.grid_id
    assert comparison.baseline.geometry == comparison.scenario.geometry
    assert value(results.compare_curves(curve(baseline), curve(scenario))).differences == (10,)
    assert value(results.curve(curve(baseline))).well_name == "PROD"
    assert value(results.cell_property(cell(baseline))).unit.value == "psi"


@pytest.mark.parametrize("changed", ["cells", "time", "geometry"])
def test_comparison_rejects_misalignment(store, publish, tmp_path, changed):
    baseline, _, _ = publish()
    options = {
        "cells": {"cells": (CellIndex(i=1, j=0, k=0), CellIndex(i=0, j=0, k=0))},
        "time": {"report_days": 2},
        "geometry": {"geometry_shift": 0.01},
    }[changed]
    scenario, _, _ = publish(
        model_ref=baseline.model.model_copy(update={"revision_id": RevisionId.new()}), **options
    )
    assert isinstance(
        service(store, tmp_path).compare_cells(cell(baseline), cell(scenario)).outcome, Failure
    )


def test_missing_property_and_wrong_well_are_clear_failures(store, publish, tmp_path):
    result, _, _ = publish()
    results = service(store, tmp_path)
    assert isinstance(
        results.cell_property(cell(result).model_copy(update={"property": "SOIL"})).outcome, Failure
    )
    assert isinstance(
        results.curve(curve(result).model_copy(update={"well_name": "OTHER"})).outcome, Failure
    )


def test_bundles_persist_and_reject_replaced_links(store, publish, tmp_path):
    result, _, _ = publish()
    first = value(service(store, tmp_path).materialize(reference(result)))
    reopened = value(service(store, tmp_path).materialize(reference(result)))
    assert reopened.egrid == first.egrid
    assert json.loads(reopened.egrid.read_text())["role"] == "EGRID"
    reopened.egrid.unlink()
    reopened.egrid.symlink_to(reopened.smspec)
    outcome = service(store, tmp_path).materialize(reference(result)).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code.value == "invalid_path"


@pytest.mark.parametrize("role", ["EGRID", "INIT", "UNRST", "SMSPEC", "UNSMRY"])
def test_reused_bundle_requires_fresh_semantic_verification(store, publish, tmp_path, role):
    result, _, _ = publish()
    results = service(store, tmp_path)
    bundle = value(results.materialize(reference(result)))
    path = bundle.directory / f"CASE.{role}"
    document = json.loads(path.read_text())
    document["values"] = [3, 4]
    path.write_text(json.dumps(document))
    outcome = results.materialize(reference(result)).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code.value == "invalid_model"


@pytest.mark.parametrize("difference", ["identity", "values"])
def test_verifier_cannot_return_another_dataset(store, publish, tmp_path, difference):
    result, _, dataset = publish()
    verifier = FixtureVerifier(store)
    if difference == "identity":
        verifier.replacement = dataset.model_copy(update={"job_id": JobId.new()})
    else:
        prop = dataset.cell_properties[0].model_copy(update={"values": ((101, 201),)})
        verifier.replacement = dataset.model_copy(
            update={"cell_properties": (prop, *dataset.cell_properties[1:])}
        )
    results = ResultsService(
        store,
        cast(Sessions, None),
        cast(Bindings, None),
        cast(ResultBackend, None),
        tmp_path / "bundles",
        verifier,
    )
    assert isinstance(results.materialize(reference(result)).outcome, Failure)
