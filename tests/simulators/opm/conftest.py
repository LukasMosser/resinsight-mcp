"""Validated inputs and explicit numerical reader fixtures for service tests."""

import shutil
from pathlib import Path

import pytest

from resinsight_mcp.contracts.identifiers import ArtifactId, GridId, ResultId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.results import ResultOutput, ResultOutputRole
from resinsight_mcp.jobs._common import require
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.simulators.opm.records import FlowRunRecord
from resinsight_mcp.workspaces import SqliteWorkspaceStore


@pytest.fixture
def run_record(tmp_path: Path) -> FlowRunRecord:
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = require(store.create_session(Session(session_id=SessionId.new(), name="Flow reader")))
    imports = OpmImportService(store)
    receipt = require(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=Path(__file__).resolve().parents[2] / "models/imports/data/spe1",
                entrypoint="SPE1.DATA",
                datum="SPE1 local depth datum",
            )
        )
    )
    with imports.materialize(receipt.prepared.revision.model) as materialized:
        shutil.copytree(materialized.directory, tmp_path / "inputs")
        inspection = materialized.inspection

    shutil.copytree(Path(__file__).parent / "data/reference", tmp_path / "outputs")

    def ref() -> ArtifactRef:
        return ArtifactRef(session_id=session.session_id, artifact_id=ArtifactId.new())

    return FlowRunRecord(
        model=receipt.prepared.revision.model,
        coordinates=receipt.prepared.revision.coordinates,
        result_id=ResultId.new(),
        grid_id=GridId.new(),
        directory=tmp_path,
        entrypoint="SPE1.DATA",
        inspection=inspection,
        outputs=tuple(ResultOutput(role=role, artifact=ref()) for role in ResultOutputRole),
        numerical_data=ref(),
        assessment_evidence=ref(),
        expected_program_version="flow 2026.04",
    )
