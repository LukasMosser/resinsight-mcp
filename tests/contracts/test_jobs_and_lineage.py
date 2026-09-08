"""Execution evidence must not be replaced by intent or unrelated results."""

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode
from resinsight_mcp.contracts.identifiers import ArtifactId, JobId, RevisionId, SessionId
from resinsight_mcp.contracts.jobs import (
    Job,
    JobState,
    NumericalAssessment,
    Result,
    ResultImportRequest,
)
from resinsight_mcp.contracts.models import ModelInputs, ModelRevision
from resinsight_mcp.contracts.sessions import ApplicationContext


def test_request_cancel_preserves_execution_until_confirmation(running_job: Job) -> None:
    requested = running_job.request_cancel()
    assert requested.state == JobState.RUNNING
    assert requested.cancel_requested and not requested.termination_confirmed
    assert not running_job.cancel_requested
    with pytest.raises(ValidationError):
        requested.transition(JobState.CANCELED)
    canceled = requested.transition(JobState.CANCELED, termination_confirmed=True)
    assert canceled.state == JobState.CANCELED
    assert canceled.cancel_requested and canceled.termination_confirmed
    assert Job.model_validate_json(canceled.model_dump_json()) == canceled


def test_lost_execution_evidence_remains_unknown_until_reconciled(running_job: Job) -> None:
    unknown = running_job.transition(JobState.UNKNOWN).request_cancel()
    assert unknown.state == JobState.UNKNOWN and unknown.exit_code is None
    assert unknown.transition(JobState.RUNNING).cancel_requested
    completed = unknown.transition(JobState.SUCCEEDED, exit_code=0)
    assert completed.cancel_requested
    assert completed.state == JobState.SUCCEEDED
    with pytest.raises(ValidationError):
        running_job.transition(JobState.UNKNOWN, exit_code=0)


@pytest.mark.parametrize("state", [JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELED])
def test_terminal_jobs_cannot_restart_or_receive_cancellation(
    running_job: Job, state: JobState
) -> None:
    if state == JobState.SUCCEEDED:
        terminal = running_job.transition(state, exit_code=0)
    elif state == JobState.FAILED:
        terminal = running_job.transition(
            state,
            error=Error(code=ErrorCode.EXECUTION_FAILED, message="Flow reported invalid input"),
            exit_code=1,
        )
    else:
        terminal = running_job.transition(state, termination_confirmed=True)
    with pytest.raises(ContractError) as transition:
        terminal.transition(JobState.RUNNING)
    assert transition.value.error.code == ErrorCode.INVALID_TRANSITION
    with pytest.raises(ContractError) as cancel:
        terminal.request_cancel()
    assert cancel.value.error.code == ErrorCode.INVALID_TRANSITION


def test_terminal_claims_require_outcome_evidence(running_job: Job) -> None:
    with pytest.raises(ValidationError):
        running_job.transition(JobState.SUCCEEDED)
    with pytest.raises(ValidationError):
        running_job.transition(JobState.SUCCEEDED, exit_code=1)
    with pytest.raises(ValidationError):
        running_job.transition(JobState.FAILED)


def test_result_import_keeps_exact_job_revision_and_separate_numerical_assessment(
    running_job: Job, result: Result, context: ApplicationContext
) -> None:
    succeeded = running_job.transition(JobState.SUCCEEDED, exit_code=0)
    request = ResultImportRequest(context=context, job=succeeded, result=result)
    restored = ResultImportRequest.model_validate_json(request.model_dump_json())
    assert restored.result.model == running_job.model
    assert restored.result.assessment == NumericalAssessment.NOT_ASSESSED
    with pytest.raises(ValidationError):
        ResultImportRequest(context=context, job=running_job, result=result)
    for change in (
        {"job_id": JobId.new()},
        {"model": ModelRef(session_id=result.model.session_id, revision_id=RevisionId.new())},
        {"model": ModelRef(session_id=SessionId.new(), revision_id=result.model.revision_id)},
    ):
        unrelated = Result.model_validate({**result.model_dump(), **change})
        with pytest.raises(ValidationError):
            ResultImportRequest(context=context, job=succeeded, result=unrelated)


def test_revision_lineage_is_immutable_and_session_local(model: ModelRef) -> None:
    original_input = ArtifactId.new()
    original = ModelRevision(
        model=model,
        inputs=ModelInputs(artifacts=(original_input,), entrypoint=original_input),
        unit_system=UnitSystem.FIELD,
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum="SPE1 local origin",
        ),
    )
    new_input = ArtifactId.new()
    revised = ModelRevision(
        model=ModelRef(session_id=model.session_id, revision_id=RevisionId.new()),
        inputs=ModelInputs(artifacts=(new_input,), entrypoint=new_input),
        unit_system=original.unit_system,
        coordinates=original.coordinates,
        parent=model,
    )
    assert original.inputs.entrypoint == original_input
    assert revised.parent == original.model
    assert ModelRevision.model_validate_json(revised.model_dump_json()) == revised
    for parent in (model, ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new())):
        with pytest.raises(ValidationError):
            ModelRevision.model_validate({**original.model_dump(), "parent": parent})
    with pytest.raises(ValidationError) as immutable:
        original.inputs = revised.inputs  # ty: ignore[invalid-assignment]  # Exercise runtime rejection.
    assert immutable.value.errors()[0]["type"] == "frozen_instance"


def test_model_entrypoint_must_identify_one_unique_input() -> None:
    artifact = ArtifactId.new()
    with pytest.raises(ValidationError):
        ModelInputs(artifacts=(artifact,), entrypoint=ArtifactId.new())
    with pytest.raises(ValidationError):
        ModelInputs(artifacts=(artifact, artifact), entrypoint=artifact)


def test_interrupted_launch_can_be_unknown_without_claiming_it_never_started(
    running_job: Job,
) -> None:
    queued = Job.model_validate({**running_job.model_dump(), "state": JobState.QUEUED})
    uncertain = queued.transition(JobState.UNKNOWN)
    assert uncertain.state == JobState.UNKNOWN
    assert uncertain.exit_code is None and not uncertain.termination_confirmed
    assert uncertain.transition(JobState.RUNNING).job_id == queued.job_id
