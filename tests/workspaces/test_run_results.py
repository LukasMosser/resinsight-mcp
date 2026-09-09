"""Workspace publication checks result evidence and durable container ownership."""

import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resinsight_mcp.contracts.engineering import ActiveCellMap, CellIndex
from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.identifiers import (
    ArtifactId,
    CheckpointId,
    JobId,
    ResultId,
    RevisionId,
)
from resinsight_mcp.contracts.jobs import (
    DockerExecution,
    Job,
    JobRef,
    JobState,
    JobSubmission,
    NumericalAssessment,
    ResourceLimits,
    ResourcePolicy,
    Result,
)
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.results import ResultManifest, ResultOutput, ResultOutputRole
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind, ProjectCheckpoint
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from ._support import value


def manifest_for(result: Result) -> ResultManifest:
    def ref() -> ArtifactRef:
        return ArtifactRef(session_id=result.model.session_id, artifact_id=ArtifactId.new())

    return ResultManifest(
        outputs=tuple(ResultOutput(role=role, artifact=ref()) for role in ResultOutputRole),
        active_cells=ActiveCellMap(
            model=result.model,
            grid_id=result.grid_id,
            dimensions=(2, 1, 1),
            cells=(CellIndex(i=1, j=0, k=0),),
        ),
        restart_report_steps=tuple(range(len(result.report_series.reports))),
        numerical_data=ref(),
        assessment_evidence=ref(),
    )


def write_artifact(store: SqliteWorkspaceStore, ref: ArtifactRef, kind: ArtifactKind) -> None:
    value(
        store.write_artifact(
            Artifact(ref=ref, relative_path=f"{ref.artifact_id}.json", kind=kind),
            io.BytesIO(b'{"evidence": "observed"}'),
        )
    )


def completed(store: SqliteWorkspaceStore, job: Job) -> Job:
    running = value(store.save_job(job.transition(JobState.RUNNING), expected=job))
    return value(
        store.save_job(running.transition(JobState.SUCCEEDED, exit_code=0), expected=running)
    )


def test_result_manifest_requires_existing_artifacts_with_correct_kinds(
    store: SqliteWorkspaceStore, queued_job: Job, result: Result, tmp_path: Path
) -> None:
    completed(store, queued_job)
    manifest = manifest_for(result)
    candidate = Result.model_validate({**result.model_dump(), "manifest": manifest})
    missing = store.save_result(candidate).outcome
    assert isinstance(missing, Failure) and missing.error.code == ErrorCode.NOT_FOUND
    for output in manifest.outputs:
        write_artifact(store, output.artifact, ArtifactKind.OUTPUT)
    for ref in (manifest.numerical_data, manifest.assessment_evidence):
        write_artifact(store, ref, ArtifactKind.METADATA)
    assert value(store.save_result(candidate)) == candidate
    payload = tmp_path / "result.json"
    payload.write_text(candidate.model_dump_json())
    observed = subprocess.run(
        [
            sys.executable,
            "-m",
            "workspaces.worker",
            "reopen-result",
            str(tmp_path / "workspace"),
            str(payload),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    restored = json.loads(observed.stdout)["outcome"]["value"]
    assert Result.model_validate_json(json.dumps(restored)) == candidate
    altered = candidate.model_copy(update={"assessment": NumericalAssessment.ACCEPTED})
    rejected = store.save_result(altered).outcome
    assert isinstance(rejected, Failure) and rejected.error.code == ErrorCode.CONFLICT


@pytest.mark.parametrize("wrong_role", ["output", "metadata"])
def test_result_manifest_rejects_wrong_artifact_kinds(
    store: SqliteWorkspaceStore, queued_job: Job, result: Result, wrong_role: str
) -> None:
    completed(store, queued_job)
    manifest = manifest_for(result)
    for output in manifest.outputs:
        kind = ArtifactKind.LOG if wrong_role == "output" else ArtifactKind.OUTPUT
        write_artifact(store, output.artifact, kind)
    for ref in (manifest.numerical_data, manifest.assessment_evidence):
        kind = ArtifactKind.LOG if wrong_role == "metadata" else ArtifactKind.METADATA
        write_artifact(store, ref, kind)
    candidate = Result.model_validate({**result.model_dump(), "manifest": manifest})
    rejected = store.save_result(candidate).outcome
    assert isinstance(rejected, Failure) and rejected.error.code == ErrorCode.INVALID_MODEL


def test_container_identity_is_append_once_and_submission_is_immutable(
    store: SqliteWorkspaceStore, queued_job: Job, tmp_path: Path
) -> None:
    metadata = ArtifactRef(session_id=queued_job.model.session_id, artifact_id=ArtifactId.new())
    write_artifact(store, metadata, ArtifactKind.METADATA)
    execution = DockerExecution(
        image_digest="opm/flow@sha256:" + "a" * 64,
        platform="linux/arm64",
        container_name="owned-run",
        ownership_token="owner-token",
        program_version="2026.04",
        docker_client_version="28.0",
        docker_server_version="28.0",
        command=("flow",),
        mounts=(),
        working_directory="/run",
    )
    submission = JobSubmission(
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=60),
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        argv=("/usr/local/bin/docker",),
        working_directory="/tmp/run",
        submitted_at=datetime.now(UTC),
        execution=execution,
        run_metadata=metadata,
    )
    queued = Job.model_validate(
        {**queued_job.model_dump(), "job_id": JobId.new(), "submission": submission}
    )
    value(store.save_job(queued))
    owned = Job.model_validate({**queued.model_dump(), "container_id": "container-one"})
    assert value(store.save_job(owned, expected=queued)) == owned
    payload = tmp_path / "job.json"
    payload.write_text(
        JobRef(session_id=owned.model.session_id, job_id=owned.job_id).model_dump_json()
    )
    observed = subprocess.run(
        [
            sys.executable,
            "-m",
            "workspaces.worker",
            "reopen-job",
            str(tmp_path / "workspace"),
            str(payload),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    restored = json.loads(observed.stdout)["outcome"]["value"]
    assert Job.model_validate_json(json.dumps(restored)) == owned
    for changes in (
        {"container_id": None},
        {"container_id": "container-two"},
        {
            "submission": submission.model_copy(
                update={"execution": execution.model_copy(update={"ownership_token": "other"})}
            )
        },
    ):
        candidate = Job.model_validate({**owned.model_dump(), **changes})
        rejected = store.save_job(candidate, expected=owned).outcome
        assert isinstance(rejected, Failure) and rejected.error.code == ErrorCode.INVALID_MODEL


def test_comparison_checkpoint_keeps_results_from_multiple_revisions(
    store: SqliteWorkspaceStore, queued_job: Job, result: Result
) -> None:
    completed(store, queued_job)
    value(store.save_result(result))
    child = value(store.clone_revision(result.model, RevisionId.new()))
    project = ArtifactRef(session_id=result.model.session_id, artifact_id=ArtifactId.new())
    write_artifact(store, project, ArtifactKind.PROJECT)
    checkpoint = ProjectCheckpoint(
        checkpoint_id=CheckpointId.new(),
        name="Parent and child comparison",
        model=child.model,
        project=project,
        result_ids=(result.result_id,),
    )
    assert value(store.save_checkpoint(checkpoint)).result_ids == (result.result_id,)
    missing = ProjectCheckpoint.model_validate(
        {
            **checkpoint.model_dump(),
            "checkpoint_id": CheckpointId.new(),
            "result_ids": (ResultId.new(),),
        }
    )
    rejected = store.save_checkpoint(missing).outcome
    assert isinstance(rejected, Failure) and rejected.error.code == ErrorCode.NOT_FOUND
