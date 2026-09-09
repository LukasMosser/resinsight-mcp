"""Trusted loading binds current references and restores saved result provenance."""

from io import BytesIO
from typing import cast

from PIL import Image

from resinsight_mcp.contracts.errors import (
    ContractError,
    Error,
    ErrorCode,
    Failure,
    OperationResult,
    Success,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, CheckpointId, RevisionId
from resinsight_mcp.contracts.jobs import ResultImportRequest
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import AttachRequest, Endpoint, ObjectKind, ProcessIdentity
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind, ProjectCheckpoint
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import NativeObject, ProjectSnapshot
from resinsight_mcp.results import ResultsService, SummaryObservation, SummaryPlotRequest
from resinsight_mcp.results._common import value

from ._support import FixtureVerifier
from .test_queries import curve


class ApplicationDouble:
    endpoint = Endpoint(port=50051)
    process = ProcessIdentity(pid=50051, start_marker="result-fixture")

    def __init__(self):
        self.project = ProjectSnapshot("empty", ())

    def verify_process(self):
        return self.process

    def snapshot(self):
        return self.project

    def open_project(self, path):
        raise AssertionError("This fixture does not open project files.")

    def save_project(self, path):
        raise AssertionError("This fixture does not save project files.")

    def close_project(self):
        raise AssertionError("This fixture does not close projects.")

    def disconnect(self):
        pass

    def terminate(self):
        raise AssertionError("This fixture does not terminate processes.")


class FactoryDouble:
    def __init__(self):
        self.apps = {50051: ApplicationDouble()}

    def launch(self, executable):
        raise AssertionError("This fixture does not launch processes.")

    def attach(self, endpoint):
        return self.apps[endpoint.port]


class BindingDouble:
    def __init__(self):
        self.loaded = []

    def bind_result(self, loaded):
        self.loaded.append(loaded)
        return OperationResult(outcome=Success(value=loaded))


class BackendDouble:
    mismatch = False
    export = True

    def load(self, access, bundle, dataset):
        app = cast(ApplicationDouble, access.application)
        address = str(bundle.result.result_id)
        app.project = ProjectSnapshot(
            "loaded",
            app.project.objects
            + (
                NativeObject(
                    ObjectKind.CASE, address, "Result", (("file_path", str(bundle.egrid)),)
                ),
            ),
        )
        return address

    def verify(self, access, case_address, bundle, dataset):
        if self.mismatch:
            raise ContractError(
                Error(code=ErrorCode.INVALID_MODEL, message="Changed native values.")
            )

    def show_curve(self, access, bundle, dataset, curve, folder, width, height):
        if self.export:
            Image.new("RGB", (width, height), "white").save(folder / "plot.png")
        return "summary-plot"


def setup(store, result, tmp_path):
    factory = FactoryDouble()
    sessions = ResInsightSessionService(store, factory)
    connection = value(
        sessions.attach(
            AttachRequest(session_id=result.model.session_id, endpoint=Endpoint(port=50051))
        )
    )
    bindings, backend = BindingDouble(), BackendDouble()
    results = ResultsService(
        store, sessions, bindings, backend, tmp_path / "bundles", FixtureVerifier(store)
    )
    return results, sessions, factory, bindings, backend, connection.context


def test_load_and_reopen_issue_new_bindings(store, publish, tmp_path):
    result, job, _ = publish()
    results, sessions, factory, bindings, _, context = setup(store, result, tmp_path)
    loaded = value(results.load(ResultImportRequest(context=context, job=job, result=result)))
    assert loaded.result == result
    assert bindings.loaded == [loaded]
    project_artifact = Artifact(
        ref=ArtifactRef(session_id=result.model.session_id, artifact_id=ArtifactId.new()),
        relative_path="saved/project.rsp",
        kind=ArtifactKind.PROJECT,
    )
    value(store.write_artifact(project_artifact, BytesIO(b"Saved native project fixture")))
    checkpoint = ProjectCheckpoint(
        checkpoint_id=CheckpointId.new(),
        name="Saved result",
        model=result.model,
        project=project_artifact.ref,
        result_ids=(result.result_id,),
    )
    value(store.save_checkpoint(checkpoint))
    app = factory.apps[50051]
    app.project = ProjectSnapshot("reopened", app.project.objects)
    current = value(sessions.inspect_project(result.model.session_id))
    restored = value(results.restore(current.context, checkpoint.checkpoint_id))
    assert restored[0].result == result
    assert restored[0].case != loaded.case
    assert restored[0].case.context == current.context


def test_wrong_native_values_do_not_bind(store, publish, tmp_path):
    result, job, _ = publish()
    results, _, _, bindings, backend, context = setup(store, result, tmp_path)
    backend.mismatch = True
    assert isinstance(
        results.load(ResultImportRequest(context=context, job=job, result=result)).outcome, Failure
    )
    assert bindings.loaded == []


def test_rebinds_two_unsaved_results_after_loading_scenario(store, publish, tmp_path):
    baseline, job, _ = publish()
    scenario, scenario_job, _ = publish(
        model_ref=baseline.model.model_copy(update={"revision_id": RevisionId.new()}), offset=10
    )
    results, sessions, _, _, _, context = setup(store, baseline, tmp_path)
    first = value(results.load(ResultImportRequest(context=context, job=job, result=baseline)))
    second = value(
        results.load(
            ResultImportRequest(context=first.case.context, job=scenario_job, result=scenario)
        )
    )
    rebound = value(results.rebind(second.case.context, (baseline.result_id, scenario.result_id)))
    assert tuple(item.result for item in rebound) == (baseline, scenario)
    assert rebound[0].case != first.case
    assert all(item.case.context == second.case.context for item in rebound)
    assert isinstance(sessions.resolve_object(first.case).outcome, Failure)


def test_summary_image_persists_exact_numerical_provenance(store, publish, tmp_path):
    result, _, _ = publish()
    results, _, _, _, _, context = setup(store, result, tmp_path)
    observation = value(
        results.show_curve(
            SummaryPlotRequest(context=context, query=curve(result), width=80, height=60)
        )
    )
    assert observation.curve.result == result
    assert observation.curve.values == (95,)
    with store.open_artifact(observation.provenance) as source:
        assert SummaryObservation.model_validate_json(source.read()) == observation
    with store.open_artifact(observation.image.artifact) as source:
        with Image.open(source) as image:
            assert image.size == (80, 60)


def test_missing_fresh_summary_image_reports_changed_state(store, publish, tmp_path):
    result, _, _ = publish()
    results, _, _, _, backend, context = setup(store, result, tmp_path)
    backend.export = False
    outcome = results.show_curve(
        SummaryPlotRequest(context=context, query=curve(result), width=80, height=60)
    ).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.effect.value == "unknown"
