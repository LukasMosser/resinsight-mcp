"""Controlled native operations use real session identity and workspace storage."""

from dataclasses import dataclass
from math import dist
from pathlib import Path

import pytest
from sessions._support import ApplicationDouble, FactoryDouble, value

from resinsight_mcp.contracts.engineering import CellIndex, CoordinateFrame
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import AttachRequest, ObjectKind
from resinsight_mcp.models.imports import (
    ImportRequest,
    MaterializedModel,
    OpmImportService,
)
from resinsight_mcp.models.wells.records import (
    CompletionConnection,
    ModeledWell,
    ModeledWellDefinition,
    PerforationInterval,
    PreparedCase,
    PreparedCaseRequest,
    TrajectoryPoint,
    TrajectorySample,
    WellCreateRequest,
    Wellhead,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import (
    ApplicationAccess,
    NativeObject,
    ProjectSnapshot,
)
from resinsight_mcp.resinsight.wells._backend import NativeCompletions, NativeWell
from resinsight_mcp.resinsight.wells.service import ResInsightWellService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


class ControlledBackend:
    def __init__(self, application: ApplicationDouble) -> None:
        self.application = application
        self.loaded: MaterializedModel | None = None
        self.wells: dict[str, NativeWell] = {}
        self.changed_case = False
        self.reverse_depth = False
        self.invalid_cell = False
        self.unknown_update = False
        self.mutations = 0
        self.checks = 0

    def load(self, access: ApplicationAccess, materialized: MaterializedModel) -> str:
        assert access.application is self.application
        self.loaded = materialized
        (materialized.directory.parent / "grid.EGRID").write_text("Controlled grid source.")
        self.application.project = ProjectSnapshot(
            "root",
            (
                NativeObject(ObjectKind.CASE, "prepared", "Prepared"),
                *(
                    item
                    for item in self.application.project.objects
                    if item.kind == ObjectKind.WELL
                ),
            ),
        )
        self.mutations += 1
        return "prepared"

    def verify_case(
        self,
        access: ApplicationAccess,
        address: str,
        materialized: MaterializedModel,
        corners: tuple[float, ...],
    ) -> None:
        assert corners == self.case_geometry(access, address, materialized)

    def case_geometry(
        self, access: ApplicationAccess, address: str, materialized: MaterializedModel
    ) -> tuple[float, ...]:
        assert self.loaded is not None and materialized.inspection == self.loaded.inspection
        assert access.application is self.application and address == "prepared"
        self.checks += 1
        if self.changed_case:
            raise ContractError(
                Error(code=ErrorCode.STALE_OBJECT, message="Native geometry changed.")
            )
        return (0.0,) * (24 * len(materialized.inspection.cell_depths_ft))

    def create(
        self, access: ApplicationAccess, case_address: str, definition: ModeledWellDefinition
    ) -> NativeWell:
        address = f"well-{definition.name}"
        if address in self.wells:
            raise ContractError(Error(code=ErrorCode.CONFLICT, message="Duplicate well."))
        native = self._native(address, definition)
        self.wells[address] = native
        self.application.project = ProjectSnapshot(
            "root",
            (
                *self.application.project.objects,
                NativeObject(ObjectKind.WELL, address, definition.name),
            ),
        )
        self.mutations += 1
        return native

    def update(
        self,
        access: ApplicationAccess,
        case_address: str,
        well_address: str,
        definition: ModeledWellDefinition,
    ) -> NativeWell:
        self.mutations += 1
        if self.unknown_update:
            raise ContractError(
                Error(
                    code=ErrorCode.LOST_CONNECTION,
                    message="The update response was lost.",
                    effect=MutationEffect.UNKNOWN,
                )
            )
        native = self._native(well_address, definition)
        self.wells[well_address] = native
        return native

    def inspect(
        self, access: ApplicationAccess, well_address: str, coordinates: CoordinateFrame
    ) -> NativeWell:
        return self.wells[well_address]

    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> NativeCompletions:
        cell = CellIndex(i=100 if self.invalid_cell else 4, j=4, k=0)
        return NativeCompletions(
            Wellhead(i=4, j=4),
            (
                CompletionConnection(
                    cell=cell,
                    compdat_factor_field=10.0,
                    permeability_length_md_ft=9500.0,
                    diameter_ft=0.5,
                    skin=0.0,
                    direction="Z",
                    start_md_ft=8326.0,
                    end_md_ft=8345.0,
                ),
            ),
        )

    def _native(self, address: str, definition: ModeledWellDefinition) -> NativeWell:
        measured_depth = 0.0
        previous: TrajectoryPoint | None = None
        samples = []
        for point in definition.targets:
            if previous is not None:
                measured_depth += dist(
                    (previous.x_ft, previous.y_ft, previous.depth_ft),
                    (point.x_ft, point.y_ft, point.depth_ft),
                )
            samples.append(
                TrajectorySample(
                    x_ft=point.x_ft,
                    y_ft=point.y_ft,
                    depth_ft=-point.depth_ft if self.reverse_depth else point.depth_ft,
                    measured_depth_ft=measured_depth,
                )
            )
            previous = point
        return NativeWell(address, definition, tuple(samples))


@dataclass
class Harness:
    store: SqliteWorkspaceStore
    sessions: ResInsightSessionService
    service: ResInsightWellService
    backend: ControlledBackend
    binding: PreparedCase

    def definition(self, name: str = "PROD", end: float = 8430.0) -> ModeledWellDefinition:
        assert self.backend.loaded is not None
        return ModeledWellDefinition(
            name=name,
            coordinates=self.backend.loaded.revision.coordinates,
            targets=(
                TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=0.0),
                TrajectoryPoint(x_ft=4500.0, y_ft=4500.0, depth_ft=end),
            ),
            perforations=(
                PerforationInterval(start_md_ft=8326.0, end_md_ft=8424.0, diameter_ft=0.5),
            ),
        )

    def create(self) -> ModeledWell:
        return value(
            self.service.create(
                WellCreateRequest(binding=self.binding, definition=self.definition())
            )
        )


@pytest.fixture
def harness(tmp_path: Path):
    store = SqliteWorkspaceStore.create(tmp_path / "workspace")
    session = value(store.create_session(Session(session_id=SessionId.new(), name="Wells")))
    imports = OpmImportService(store)
    receipt = value(
        imports.import_model(
            ImportRequest(
                session_id=session.session_id,
                source_root=Path(__file__).parents[2] / "models" / "imports" / "data" / "spe1",
                entrypoint="SPE1.DATA",
                datum="Local",
            )
        )
    )
    factory = FactoryDouble()
    application = factory.apps[50051]
    application.project = ProjectSnapshot("root", ())
    sessions = ResInsightSessionService(store, factory)
    connection = value(
        sessions.attach(AttachRequest(session_id=session.session_id, endpoint=application.endpoint))
    )
    backend = ControlledBackend(application)
    service = ResInsightWellService(
        store, sessions, imports, backend, source_root=tmp_path / "native-sources"
    )
    binding = value(
        service.load(
            PreparedCaseRequest(context=connection.context, model=receipt.prepared.revision.model)
        )
    )
    yield Harness(store, sessions, service, backend, binding)
    service.close()
