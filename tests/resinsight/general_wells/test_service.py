"""Exercise well publication and failures with real session and workspace ownership."""

from dataclasses import replace

import numpy as np
import pytest
from sessions._support import FactoryDouble

from resinsight_mcp.contracts.engineering import CellIndex
from resinsight_mcp.contracts.errors import ErrorCode, Failure, MutationEffect
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef, Session
from resinsight_mcp.contracts.sessions import AttachRequest, ObjectKind
from resinsight_mcp.contracts.wells import WellStatus
from resinsight_mcp.models.general.arrays import (
    ArrayRangeRequest,
    ArrayService,
    AuthoringPolicy,
    value,
)
from resinsight_mcp.models.general.records import GeologicalRequest
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.models.general.wells import (
    GeneralConnection,
    GeneralWellhead,
    GeneralWellModels,
    WellPlanRequest,
)
from resinsight_mcp.resinsight.general.records import LoadedGrid
from resinsight_mcp.resinsight.general.service import GeneralGridService
from resinsight_mcp.resinsight.general.well_records import GeneralWellBinding, GeneralWellLoad
from resinsight_mcp.resinsight.general.wells import GeneralNativeWells
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import NativeObject, ProjectSnapshot
from resinsight_mcp.resinsight.wells.rips import GeneralCompletions, NativeGeometry
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class GridDouble(GeneralGridService):
    def verify_access(self, access, loaded, case_address):
        self.require_loaded(loaded)
        assert case_address == "case-0"


class BackendDouble:
    def __init__(self, application):
        self.application = application
        self.wells = {}
        self.bad_created_geometry = False
        self.cell = CellIndex(i=0, j=0, k=0)
        self.end_md = 90

    def create(self, access, case_address, definition):
        address = f"well-{definition.name}"
        samples = ((*definition.targets[0], 0), (*definition.targets[-1], 100))
        observed = (
            definition.model_copy(update={"name": "WRONG"})
            if self.bad_created_geometry
            else definition
        )
        native = NativeGeometry(address, observed, samples)
        self.wells[address] = native
        self.application.project = ProjectSnapshot(
            "root",
            (
                *self.application.project.objects,
                NativeObject(ObjectKind.WELL, address, definition.name),
            ),
        )
        return native

    def inspect(self, access, well_address, sampling_distance):
        return self.wells[well_address]

    def completions(self, access, case_address, well_address):
        return GeneralCompletions(
            GeneralWellhead(i=0, j=0),
            (
                GeneralConnection(
                    cell=self.cell,
                    status=WellStatus.OPEN,
                    factor=10,
                    kh=1000,
                    diameter=0.2,
                    skin=0,
                    direction="Z",
                    start_md=10,
                    end_md=self.end_md,
                ),
            ),
        )


@pytest.fixture
def setup(tmp_path):
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = SessionId.new()
    value(store.create_session(Session(session_id=session, name="General wells")))
    factory = FactoryDouble()
    app = factory.apps[50051]
    app.project = ProjectSnapshot(
        "root", (*app.project.objects, NativeObject(ObjectKind.VIEW, "view-0", "View"))
    )
    sessions = ResInsightSessionService(store, factory)
    value(sessions.attach(AttachRequest(session_id=session, endpoint=app.endpoint)))
    arrays = ArrayService(store, AuthoringPolicy())
    models = GeneralModelService(arrays)
    model = value(
        models.generate(
            GeologicalRequest.model_validate(
                {
                    "session_id": session,
                    "name": "Grid",
                    "shape": {"nx": 2, "ny": 2, "nz": 2},
                    "extent_x": 200,
                    "extent_y": 200,
                    "thickness": 200,
                    "top_depth": 1500,
                    "length_unit": "m",
                    "datum": "Local depth",
                    "bands": ({"bottom_fraction": 1, "porosity": 0.2, "permeability_md": 100},),
                }
            )
        )
    )
    project = value(sessions.inspect_project(session))
    loaded = LoadedGrid(
        receipt=ArtifactRef(session_id=session, artifact_id=ArtifactId.new()),
        model=model.model,
        case=project.objects[0].ref,
        view=project.objects[1].ref,
        source=tmp_path / "model.GRDECL",
        global_cells=8,
        active_cells=8,
        verified_properties=("PERMX", "PERMY", "PERMZ"),
    )
    grids = GridDouble(models, sessions, tmp_path)
    loaded = grids.refresh(loaded, loaded.case, loaded.view)
    plans = GeneralWellModels(models)
    plan = value(
        plans.define(
            WellPlanRequest(
                model=model.model,
                name="PRODUCER",
                role="producer",
                sampling_distance=10,
                targets=arrays.write(
                    session, np.array([50, 50, 1500, 50, 50, 1600], dtype=np.float64), "m"
                ).artifact,
                intervals=arrays.write(session, np.array([0, 100, 0.2]), "m").artifact,
                skins=arrays.write(session, np.array([0.0]), "1").artifact,
            )
        )
    )
    backend = BackendDouble(app)
    return GeneralNativeWells(plans, grids, backend), backend, loaded, plan


def test_public_well_load_export_and_restore_retain_lineage(setup):
    service, backend, loaded, plan = setup
    state = value(service.load(GeneralWellLoad(loaded=loaded, plan=plan.artifact)))
    assert (
        state.binding.loaded.case.context.project_generation
        > loaded.case.context.project_generation
    )
    exported = value(service.export(state.binding))
    assert exported.model == plan.model and exported.plan == plan.artifact
    assert exported.well_receipt == state.binding.receipt
    cells = next(c.array for c in exported.columns if c.name == "cells")
    assert value(
        service.arrays.query(ArrayRangeRequest(array=cells.artifact, offset=0, count=3))
    ).values == (0, 0, 0)
    assert value(service.connections(exported.artifact)) == exported
    new_service = GeneralNativeWells(service.plans, service.grids, backend)
    assert value(new_service.restore(state.binding)) == state
    backend.wells["well-PRODUCER"] = replace(
        backend.wells["well-PRODUCER"], trajectory=((50, 50, 1500, 0), (51, 50, 1600, 100))
    )
    failed = new_service.restore(state.binding).outcome
    assert isinstance(failed, Failure) and failed.error.code == ErrorCode.STALE_OBJECT


def test_foreign_plan_and_stale_grid_do_not_create_native_wells(setup):
    service, backend, loaded, plan = setup
    wrong = loaded.model_copy(
        update={"model": loaded.model.model_copy(update={"revision_id": RevisionId.new()})}
    )
    assert isinstance(
        service.load(GeneralWellLoad(loaded=wrong, plan=plan.artifact)).outcome, Failure
    )
    assert not backend.wells
    state = value(service.load(GeneralWellLoad(loaded=loaded, plan=plan.artifact)))
    assert isinstance(
        service.load(GeneralWellLoad(loaded=loaded, plan=plan.artifact)).outcome, Failure
    )
    assert len(backend.wells) == 1
    assert value(service.restore(state.binding)).plan == plan


def test_mutated_native_result_reports_unknown_effect(setup):
    service, backend, loaded, plan = setup
    backend.bad_created_geometry = True
    failed = service.load(GeneralWellLoad(loaded=loaded, plan=plan.artifact)).outcome
    assert isinstance(failed, Failure)
    assert failed.error.effect == MutationEffect.UNKNOWN
    assert backend.wells


def test_invalid_cells_and_perforation_bounds_fail_export(setup):
    service, backend, loaded, plan = setup
    state = value(service.load(GeneralWellLoad(loaded=loaded, plan=plan.artifact)))
    backend.cell = CellIndex(i=2, j=0, k=0)
    assert isinstance(service.export(state.binding).outcome, Failure)
    backend.cell = CellIndex(i=0, j=0, k=0)
    backend.end_md = 120
    assert isinstance(service.export(state.binding).outcome, Failure)
    with pytest.raises(ValueError, match="current native context"):
        GeneralWellBinding(loaded=loaded, well=state.binding.well, receipt=state.binding.receipt)


@pytest.mark.parametrize("native_units", [None, "FIELD"])
def test_native_unit_guard_rejects_missing_or_wrong_units(setup, native_units):
    from types import SimpleNamespace

    from resinsight_mcp.contracts.errors import ContractError
    from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
    from resinsight_mcp.resinsight.sessions.rips import RipsApplication

    service, _, loaded, _ = setup
    case = SimpleNamespace(address=lambda: "case-0")
    if native_units is not None:
        case.grid_unit_system = lambda: SimpleNamespace(values=[native_units])

    class UnitApplication(RipsApplication):
        def __init__(self):
            pass

        def project(self):
            return SimpleNamespace(cases=lambda: [case])

        def call(self, action, *, mutation=False):
            assert not mutation
            return action()

    grids = GeneralGridService(service.plans.models, service.grids.sessions, service.grids.root)
    grids.refresh(loaded, loaded.case, loaded.view)
    project = value(grids.sessions.inspect_project(loaded.model.session_id))
    access = ApplicationAccess(UnitApplication(), project, ())
    with pytest.raises(ContractError) as error:
        grids.verify_access(access, loaded, "case-0")
    assert error.value.error.code == (
        ErrorCode.UNSUPPORTED_OPERATION if native_units is None else ErrorCode.INVALID_MODEL
    )
    assert error.value.error.effect == MutationEffect.NOT_APPLIED
