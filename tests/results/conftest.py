"""Store small semantic result sets through the public workspace API."""

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from resinsight_mcp.contracts.engineering import (
    ActiveCellMap,
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    ReportSeries,
    ReportTime,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, GridId, JobId, ResultId
from resinsight_mcp.contracts.jobs import Job, JobState, NumericalAssessment, Result
from resinsight_mcp.contracts.models import (
    ArtifactRef,
    Backend,
    ModelInputs,
    ModelRevision,
    Session,
)
from resinsight_mcp.contracts.results import (
    CellCorners,
    CellPropertySeries,
    GridGeometry,
    ResultDataset,
    ResultManifest,
    ResultOutput,
    ResultOutputRole,
    SummaryCurve,
)
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.results._common import value
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@pytest.fixture
def store(tmp_path: Path, model: ModelRef) -> SqliteWorkspaceStore:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    value(store.create_session(Session(session_id=model.session_id, name="Result study")))
    return store


@pytest.fixture
def publish(store: SqliteWorkspaceStore, model: ModelRef):
    default_cells = (CellIndex(i=0, j=0, k=0), CellIndex(i=1, j=0, k=0))

    def make(
        *,
        offset: float = 0,
        model_ref: ModelRef = model,
        cells=default_cells,
        report_days: float = 1,
        geometry_shift: float = 0,
    ):
        def artifact(name, kind, text):
            record = Artifact(
                ref=ArtifactRef(session_id=model.session_id, artifact_id=ArtifactId.new()),
                relative_path=name,
                kind=kind,
            )
            value(store.write_artifact(record, BytesIO(text.encode())))
            return record.ref

        result_id = ResultId.new()
        grid_id = GridId.new()
        coordinates = CoordinateFrame(
            length_unit=Unit.FOOT, depth_direction=DepthDirection.POSITIVE_DOWN, datum="local"
        )
        source = artifact(f"{result_id}/CASE.DATA", ArtifactKind.INPUT, "FIELD model")
        value(
            store.save_revision(
                ModelRevision(
                    model=model_ref,
                    inputs=ModelInputs(
                        artifacts=(source.artifact_id,), entrypoint=source.artifact_id
                    ),
                    unit_system=UnitSystem.FIELD,
                    coordinates=coordinates,
                )
            )
        )
        job = Job(
            job_id=JobId.new(),
            model=model_ref,
            backend=Backend.OPM_FLOW,
            state=JobState.QUEUED,
        )
        value(store.save_job(job))
        running = job.transition(JobState.RUNNING)
        value(store.save_job(running, expected=job))
        job = running.transition(JobState.SUCCEEDED, exit_code=0)
        value(store.save_job(job, expected=running))
        active = ActiveCellMap(model=model_ref, grid_id=grid_id, dimensions=(2, 1, 1), cells=cells)
        reports = ReportSeries(
            reports=(ReportTime(index=1, elapsed_days=report_days, calendar_date=date(2015, 1, 2)),)
        )
        dataset = ResultDataset(
            job_id=job.job_id,
            model=model_ref,
            active_cells=active,
            geometry=GridGeometry(
                coordinates=coordinates,
                cell_corners=tuple(
                    cast(
                        CellCorners,
                        tuple(
                            (cell.i + i + geometry_shift, cell.j + j, 100.0 + cell.k + k)
                            for k in (0, 1)
                            for j in (0, 1)
                            for i in (0, 1)
                        ),
                    )
                    for cell in cells
                ),
            ),
            report_series=reports,
            cell_properties=(
                CellPropertySeries(
                    name="PRESSURE", unit=Unit.PSI, values=((100 + offset, 200 + offset),)
                ),
                CellPropertySeries(name="SWAT", unit=Unit.ONE, values=((0.2, 0.3),)),
            ),
            curves=(
                SummaryCurve(
                    scope="well",
                    keyword="WBHP",
                    well_name="PROD",
                    unit=Unit.PSI,
                    values=(95 + offset,),
                ),
            ),
        )
        manifest = ResultManifest(
            active_cells=active,
            restart_report_steps=(1,),
            numerical_data=artifact(
                f"{result_id}/data.json", ArtifactKind.METADATA, dataset.model_dump_json()
            ),
            assessment_evidence=artifact(
                f"{result_id}/assessment.json", ArtifactKind.METADATA, '{"accepted":true}'
            ),
            outputs=tuple(
                ResultOutput(
                    role=role,
                    artifact=artifact(
                        f"{result_id}/CASE.{role.value}",
                        ArtifactKind.OUTPUT,
                        json.dumps({"role": role.value, "unit_system": "FIELD", "values": [1, 2]}),
                    ),
                )
                for role in ResultOutputRole
            ),
        )
        result = Result(
            result_id=result_id,
            job_id=job.job_id,
            model=model_ref,
            grid_id=grid_id,
            report_series=reports,
            assessment=NumericalAssessment.ACCEPTED,
            manifest=manifest,
        )
        value(store.save_result(result))
        return result, job, dataset

    return make
