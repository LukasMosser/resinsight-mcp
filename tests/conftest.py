"""Small engineering records shared by the public contract examples."""

from datetime import date

import pytest

from resinsight_mcp.contracts.engineering import ModelRef, ReportSeries, ReportTime
from resinsight_mcp.contracts.identifiers import (
    ConnectionId,
    GridId,
    JobId,
    ResultId,
    RevisionId,
    SessionId,
)
from resinsight_mcp.contracts.jobs import Job, JobState, Result
from resinsight_mcp.contracts.models import Backend
from resinsight_mcp.contracts.sessions import ApplicationContext


@pytest.fixture
def model() -> ModelRef:
    return ModelRef(session_id=SessionId.new(), revision_id=RevisionId.new())


@pytest.fixture
def context(model: ModelRef) -> ApplicationContext:
    return ApplicationContext(
        session_id=model.session_id, connection_id=ConnectionId.new(), project_generation=1
    )


@pytest.fixture
def running_job(model: ModelRef) -> Job:
    return Job(job_id=JobId.new(), model=model, backend=Backend.OPM_FLOW, state=JobState.RUNNING)


@pytest.fixture
def result(running_job: Job) -> Result:
    return Result(
        result_id=ResultId.new(),
        job_id=running_job.job_id,
        model=running_job.model,
        grid_id=GridId.new(),
        report_series=ReportSeries(
            reports=(
                ReportTime(index=0, elapsed_days=0.0, calendar_date=date(2015, 1, 1)),
                ReportTime(index=120, elapsed_days=3650.0, calendar_date=date(2024, 12, 29)),
            )
        ),
    )
