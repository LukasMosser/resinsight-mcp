"""Durable execution and result data preserve their meaning after serialization."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import (
    ActiveCellMap,
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    Dimension,
    Unit,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, GridId, SessionId
from resinsight_mcp.contracts.jobs import (
    DockerExecution,
    DockerMount,
    Job,
    JobSubmission,
    ResourceLimits,
    ResourcePolicy,
    Result,
)
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.results import (
    CellPropertySeries,
    GridGeometry,
    ResultDataset,
    ResultManifest,
    ResultOutput,
    ResultOutputRole,
    SummaryCurve,
)


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


def test_manifest_requires_complete_distinct_session_local_outputs(result: Result) -> None:
    manifest = manifest_for(result)
    complete = Result.model_validate({**result.model_dump(), "manifest": manifest})
    assert Result.model_validate_json(complete.model_dump_json()) == complete
    for outputs in (manifest.outputs[:-1], (*manifest.outputs[:-1], manifest.outputs[0])):
        with pytest.raises(ValidationError):
            ResultManifest.model_validate({**manifest.model_dump(), "outputs": outputs})
    for changes in (
        {"numerical_data": manifest.outputs[0].artifact},
        {"numerical_data": ArtifactRef(session_id=SessionId.new(), artifact_id=ArtifactId.new())},
        {"restart_report_steps": (2, 1)},
    ):
        with pytest.raises(ValidationError):
            ResultManifest.model_validate({**manifest.model_dump(), **changes})
    for changes in ({"grid_id": GridId.new()}, {"report_series": {"reports": ()}}):
        with pytest.raises(ValidationError):
            Result.model_validate({**complete.model_dump(), **changes})
    short = ResultManifest.model_validate(
        {**manifest.model_dump(), "restart_report_steps": (*manifest.restart_report_steps, 99)}
    )
    with pytest.raises(ValidationError):
        Result.model_validate({**complete.model_dump(), "manifest": short})


def test_dataset_preserves_units_active_order_and_rejects_shape_errors(result: Result) -> None:
    manifest = manifest_for(result)
    count = len(result.report_series.reports)
    pressure = CellPropertySeries(name="PRESSURE", unit=Unit.PSI, values=((100.0,),) * count)
    curve = SummaryCurve(
        scope="field",
        keyword="FOPR",
        unit=Unit.STOCK_TANK_BARREL_PER_DAY,
        values=(2.0,) * count,
    )
    geometry = GridGeometry(
        coordinates=CoordinateFrame(
            length_unit=Unit.FOOT,
            depth_direction=DepthDirection.POSITIVE_DOWN,
            datum="local",
        ),
        cell_corners=(
            (
                (1, 0, 0),
                (2, 0, 0),
                (1, 1, 0),
                (2, 1, 0),
                (1, 0, 1),
                (2, 0, 1),
                (1, 1, 1),
                (2, 1, 1),
            ),
        ),
    )
    dataset = ResultDataset(
        job_id=result.job_id,
        model=result.model,
        active_cells=manifest.active_cells,
        geometry=geometry,
        report_series=result.report_series,
        cell_properties=(pressure,),
        curves=(curve,),
    )
    assert ResultDataset.model_validate_json(dataset.model_dump_json()) == dataset
    assert dataset.active_cells.cell_at(0).index.i == 1
    assert curve.unit.dimension == Dimension.VOLUME_RATE
    for changes in (
        {"cell_properties": (pressure, pressure)},
        {"curves": (curve, curve)},
        {"cell_properties": (pressure.model_copy(update={"values": ((1.0, 2.0),) * count}),)},
        {"curves": (curve.model_copy(update={"values": ()}),)},
        {"geometry": {**geometry.model_dump(), "cell_corners": ()}},
        {"geometry": {**geometry.model_dump(), "cell_corners": (geometry.cell_corners[0][:-1],)}},
        {
            "geometry": {
                **geometry.model_dump(),
                "cell_corners": (((float("nan"), 0, 0), *geometry.cell_corners[0][1:]),),
            }
        },
    ):
        with pytest.raises(ValidationError):
            ResultDataset.model_validate({**dataset.model_dump(), **changes})
    with pytest.raises(ValidationError):
        SummaryCurve(scope="well", keyword="WBHP", unit=Unit.PSI, values=(100.0,))
    with pytest.raises(ValidationError):
        SummaryCurve(scope="field", keyword="FOPR", well_name="PROD", unit=Unit.ONE, values=())


def test_docker_submission_preserves_command_and_rejects_ambiguous_mounts(
    running_job: Job,
) -> None:
    execution = DockerExecution(
        image_digest="opm/flow@sha256:" + "a" * 64,
        platform="linux/arm64",
        container_name="owned-run",
        ownership_token="owner-token",
        program_version="2026.04",
        docker_client_version="28.0",
        docker_server_version="28.0",
        command=("flow", "/input/SPE1.DATA"),
        mounts=(DockerMount(source="/tmp/input", target="/input", read_only=True),),
        working_directory="/output",
    )
    submission = JobSubmission(
        limits=ResourceLimits(cpu_count=1, memory_mib=128, wall_time_seconds=60),
        resource_policy=ResourcePolicy.WALL_TIME_ONLY,
        argv=("/usr/local/bin/docker",),
        working_directory="/tmp/run",
        submitted_at=datetime.now(UTC),
        execution=execution,
    )
    assert JobSubmission.model_validate_json(submission.model_dump_json()) == submission
    for changes in (
        {"image_digest": "opm/flow:latest"},
        {"command": ()},
        {"mounts": (*execution.mounts, *execution.mounts)},
        {"working_directory": "relative"},
    ):
        with pytest.raises(ValidationError):
            DockerExecution.model_validate({**execution.model_dump(), **changes})
    with pytest.raises(ValidationError):
        JobSubmission.model_validate({**submission.model_dump(), "argv": (*submission.argv, "run")})
    with pytest.raises(ValidationError):
        Job.model_validate({**running_job.model_dump(), "container_id": "container"})


def test_older_result_and_job_records_remain_readable(result: Result, running_job: Job) -> None:
    assert Result.model_validate_json(result.model_dump_json(exclude={"manifest"})).manifest is None
    restored = Job.model_validate_json(running_job.model_dump_json(exclude={"container_id"}))
    assert restored.container_id is None
    assert restored.job_id == running_job.job_id
