"""Collect real preserved outputs without starting a simulator or Docker daemon."""

import io
import shutil
from datetime import UTC, datetime
from typing import BinaryIO

import numpy as np
import pytest

from resinsight_mcp.contracts.errors import Failure, MutationEffect
from resinsight_mcp.contracts.identifiers import ArtifactId, JobId
from resinsight_mcp.contracts.jobs import (
    DockerExecution,
    Job,
    JobRef,
    JobState,
    JobSubmission,
    NumericalAssessment,
    ResourceLimits,
    ResourcePolicy,
)
from resinsight_mcp.contracts.models import ArtifactRef, Backend
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.jobs._common import require
from resinsight_mcp.simulators.opm import OpmFlowService
from resinsight_mcp.simulators.opm.records import FlowRunRecord

from ._support import rewrite


@pytest.fixture
def completed(
    run_record: FlowRunRecord, request: pytest.FixtureRequest
) -> tuple[OpmFlowService, JobRef, FlowRunRecord]:
    service = OpmFlowService(run_record.directory / "workspace")
    directory = service.runtime / "preserved"
    shutil.copytree(run_record.directory / "inputs", directory / "inputs")
    shutil.copytree(run_record.directory / "outputs", directory / "outputs")
    version, platform = getattr(request, "param", ("flow 2026.04", "linux/arm64"))
    run = run_record.model_copy(
        update={"directory": directory, "expected_program_version": version}
    )
    metadata = ArtifactRef(session_id=run.model.session_id, artifact_id=ArtifactId.new())
    require(
        service.store.write_artifact(
            Artifact(ref=metadata, kind=ArtifactKind.METADATA, relative_path="run.json"),
            io.BytesIO(run.model_dump_json().encode()),
        )
    )
    job = Job(
        job_id=JobId.new(),
        model=run.model,
        backend=Backend.OPM_FLOW,
        state=JobState.QUEUED,
        submission=JobSubmission(
            limits=ResourceLimits(cpu_count=2, memory_mib=2048, wall_time_seconds=60),
            resource_policy=ResourcePolicy.ENFORCE,
            argv=(str(service.configuration.docker),),
            working_directory=str(directory),
            submitted_at=datetime.now(UTC),
            run_metadata=metadata,
            execution=DockerExecution(
                image_digest=service.configuration.image,
                platform=platform,
                container_name="preserved-fixture",
                ownership_token="preserved-fixture",
                program_version=version,
                docker_client_version="fixture",
                docker_server_version="fixture",
                command=("flow", "/input/SPE1.DATA"),
                mounts=(),
                working_directory="/output",
            ),
        ),
    )
    require(service.store.save_job(job))
    running = job.transition(JobState.RUNNING)
    require(service.store.save_job(running, expected=job))
    log = ArtifactRef(session_id=run.model.session_id, artifact_id=ArtifactId.new())
    require(
        service.store.write_artifact(
            Artifact(ref=log, kind=ArtifactKind.LOG, relative_path="flow.log"),
            io.BytesIO(f"This is {version}\n".encode()),
        )
    )
    succeeded = running.transition(JobState.SUCCEEDED, exit_code=0, termination_confirmed=True)
    succeeded = succeeded.model_copy(update={"logs": (log,)})
    require(service.store.save_job(succeeded, expected=running))
    return service, JobRef(session_id=run.model.session_id, job_id=job.job_id), run


def test_collection_survives_reopen_and_verifies_outputs(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord],
) -> None:
    service, job, run = completed
    result = require(service.collect(job))
    assert result.assessment == NumericalAssessment.ACCEPTED
    assert result.manifest is not None and len(result.manifest.outputs) == 5
    assert result.grid_id == run.grid_id
    reopened = OpmFlowService(service.workspace)
    assert require(reopened.collect(job)) == result
    dataset = require(reopened.verify_outputs(result, run.directory / "outputs"))
    assert dataset.job_id == job.job_id and dataset.model == run.model
    assert dataset.active_cells.grid_id == result.grid_id


@pytest.mark.parametrize("extension,keyword", [("EGRID", "COORD"), ("INIT", "TRANX")])
def test_verifier_rejects_changed_geometry_and_static_data(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord], extension: str, keyword: str
) -> None:
    service, job, run = completed
    result = require(service.collect(job))
    rewrite(
        run.directory / "outputs" / f"SPE1.{extension}",
        lambda name, values: values + np.float32(100) if name == keyword else values,
    )
    outcome = service.verify_outputs(result, run.directory / "outputs").outcome
    assert isinstance(outcome, Failure)
    assert "semantics differ" in outcome.error.message


def test_collection_rejects_missing_output(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord],
) -> None:
    service, job, run = completed
    (run.directory / "outputs/SPE1.UNRST").unlink()
    assert isinstance(service.collect(job).outcome, Failure)
    assert isinstance(service.store.get_result(job.session_id, run.result_id).outcome, Failure)


@pytest.mark.parametrize("change_geometry", [False, True])
def test_partial_publication_retry_preserves_consistency(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord],
    monkeypatch: pytest.MonkeyPatch,
    change_geometry: bool,
) -> None:
    service, job, run = completed
    original = service.store.write_artifact
    count = 0

    def fail_third(artifact: Artifact, source: BinaryIO):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("Injected storage failure")
        return original(artifact, source)

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "write_artifact", fail_third)
        outcome = service.collect(job).outcome
    assert isinstance(outcome, Failure) and outcome.error.effect == MutationEffect.UNKNOWN
    if not change_geometry:
        result = require(service.collect(job))
        assert result.result_id == run.result_id
        require(service.verify_outputs(result, run.directory / "outputs"))
        return
    rewrite(
        run.directory / "outputs/SPE1.EGRID",
        lambda name, values: values + np.float32(100) if name == "COORD" else values,
    )
    outcome = service.collect(job).outcome
    assert isinstance(outcome, Failure) and outcome.error.effect == MutationEffect.UNKNOWN
    assert "Published output semantics differ" in outcome.error.message
    assert isinstance(service.store.get_result(job.session_id, run.result_id).outcome, Failure)


@pytest.mark.parametrize("changed_field", ["grid", "outputs"])
def test_verifier_rejects_canonical_result_with_unrelated_identity(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord],
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    from resinsight_mcp.contracts.identifiers import GridId
    from resinsight_mcp.contracts.jobs import Result

    service, job, run = completed
    save = service.store.save_result

    def save_unrelated(result: Result):
        assert result.manifest is not None
        manifest = result.manifest
        if changed_field == "grid":
            grid_id = GridId.new()
            manifest = manifest.model_copy(
                update={
                    "active_cells": manifest.active_cells.model_copy(update={"grid_id": grid_id})
                }
            )
            result = result.model_copy(update={"grid_id": grid_id, "manifest": manifest})
        else:
            outputs = list(manifest.outputs)
            first, second = outputs[:2]
            outputs[0] = first.model_copy(update={"artifact": second.artifact})
            outputs[1] = second.model_copy(update={"artifact": first.artifact})
            result = result.model_copy(
                update={"manifest": manifest.model_copy(update={"outputs": tuple(outputs)})}
            )
        return save(result)

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "save_result", save_unrelated)
        unrelated = require(service.collect(job))
    assert require(service.store.get_result(job.session_id, unrelated.result_id)) == unrelated
    outcome = service.verify_outputs(unrelated, run.directory / "outputs").outcome
    assert isinstance(outcome, Failure)
    assert "identity or manifest differs" in outcome.error.message


@pytest.mark.parametrize(
    "completed",
    [("flow 2026.04-extra", "linux/arm64"), ("flow 2026.04", "linux/amd64")],
    indirect=True,
)
def test_collection_rejects_runtime_outside_pinned_configuration(
    completed: tuple[OpmFlowService, JobRef, FlowRunRecord],
) -> None:
    service, job, run = completed
    outcome = service.collect(job).outcome
    assert isinstance(outcome, Failure)
    assert "recorded job identity" in outcome.error.message
    assert isinstance(service.store.get_result(job.session_id, run.result_id).outcome, Failure)
