"""Discover owned views without adopting unsupported native display settings."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

import pytest

from resinsight_mcp.contracts.errors import ErrorCode, Failure
from resinsight_mcp.contracts.identifiers import GridId, ResultId
from resinsight_mcp.contracts.jobs import LoadedResult, Result
from resinsight_mcp.contracts.observations import Camera, Projection, RenderRequest, ViewContext
from resinsight_mcp.contracts.sessions import AttachRequest, Endpoint, ObjectKind, ProcessIdentity
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import NativeObject, ProjectSnapshot
from resinsight_mcp.resinsight.sessions.rips import RipsApplication
from resinsight_mcp.resinsight.views import ResInsightViewService
from resinsight_mcp.resinsight.views._backend import NativeViewState
from resinsight_mcp.resinsight.views._camera import view_matrix
from resinsight_mcp.resinsight.views.rips import RipsViewBackend

from ._support import ControlledFactory
from .conftest import value


@dataclass
class Case:
    identifier: int
    name: str = "Same name"

    def address(self) -> int:
        return self.identifier


@dataclass
class View:
    identifier: int
    owner: Case
    camera: Camera
    grid_z_scale: float
    name: str = "Same name"

    @property
    def camera_matrix(self) -> list[float]:
        return view_matrix(self.camera)

    @property
    def camera_point_of_interest(self) -> list[float]:
        return list(self.camera.target)

    @property
    def perspective_projection(self) -> bool:
        return self.camera.projection == Projection.PERSPECTIVE

    @property
    def actual_camera_field_of_view_y_degrees(self) -> float:
        return self.camera.field_of_view_degrees or 40.0

    @property
    def actual_camera_parallel_projection_height(self) -> float:
        return 2 * (self.camera.parallel_scale or 1.0)

    def address(self) -> int:
        return self.identifier

    def case(self) -> Case:
        return self.owner

    def cell_result(self) -> None:
        raise AssertionError("Discovery must not inspect or adopt native properties.")

    def range_filters(self) -> None:
        raise AssertionError("Discovery must not inspect or adopt native filters.")


@dataclass
class Project:
    case_rows: list[Case]
    view_rows: list[View]
    root_address: str = "project"
    on_read: Callable[[], None] | None = None

    def cases(self) -> list[Case]:
        return self.case_rows

    def views(self) -> list[View]:
        if self.on_read is not None:
            self.on_read()
        return self.view_rows

    def well_paths(self) -> list[Any]:
        return []


class Application(RipsApplication):
    """Use local supported-method fixtures without creating a native client channel."""

    def __init__(self, native: Project) -> None:
        self.native = native
        self._endpoint = Endpoint(port=50051)
        self._process = ProcessIdentity(pid=1234, start_marker=uuid4().hex)
        self.mutations = 0

    def project(self) -> Any:
        return self.native

    def verify_process(self) -> ProcessIdentity:
        return self.process

    def snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            root_address=self.native.root_address,
            objects=tuple(
                NativeObject(kind=kind, address=str(item.address()), name=item.name)
                for kind, rows in (
                    (ObjectKind.CASE, self.native.case_rows),
                    (ObjectKind.VIEW, self.native.view_rows),
                )
                for item in rows
            ),
        )

    def call[T](self, action: Callable[[], T], *, mutation: bool = False) -> T:
        self.mutations += int(mutation)
        return action()

    def disconnect(self) -> None:
        pass


@dataclass
class Discovery:
    service: ResInsightViewService
    sessions: ResInsightSessionService
    backend: RipsViewBackend
    application: Application
    loaded: LoadedResult
    context: ViewContext


@pytest.fixture
def discovery(store, view_context: ViewContext, result: Result) -> Discovery:
    first, second = Case(10), Case(20)
    orthographic = Camera(
        position=(0, 0, 10),
        target=(0, 0, 0),
        up=(0, 1, 0),
        projection=Projection.ORTHOGRAPHIC,
        parallel_scale=1000,
    )
    perspective = Camera(
        position=(10, 0, 0),
        target=(0, 0, 0),
        up=(0, 0, 1),
        projection=Projection.PERSPECTIVE,
        field_of_view_degrees=45,
    )
    native = Project(
        [first, second],
        [
            View(11, first, orthographic, 2),
            View(21, second, orthographic, 8),
            View(12, first, perspective, 5),
        ],
    )
    application = Application(native)
    factory = ControlledFactory(cast(Any, application))
    sessions = ResInsightSessionService(store, factory)
    value(
        sessions.attach(
            AttachRequest(session_id=result.model.session_id, endpoint=application.endpoint)
        )
    )
    project = value(sessions.inspect_project(result.model.session_id))
    case = project.objects[0].ref
    view = project.objects[2].ref
    loaded = LoadedResult(case=case, result=result)
    backend = RipsViewBackend()
    service = ResInsightViewService(store, sessions, backend)
    context = view_context.model_copy(
        update={"case": case, "view": view, "scene_version": 0, "selected_wells": ()}
    )
    return Discovery(service, sessions, backend, application, loaded, context)


def test_discovery_filters_actual_case_ownership_and_preserves_camera(discovery: Discovery):
    value(discovery.service.bind_result(discovery.loaded))
    before = discovery.application.snapshot()
    settings = [(view.camera, view.grid_z_scale) for view in discovery.application.native.view_rows]
    rows = value(discovery.service.list_views(discovery.loaded))
    assert len(rows) == 2
    assert [row.camera for row in rows] == [
        discovery.application.native.view_rows[index].camera for index in (0, 2)
    ]
    assert [row.vertical_exaggeration for row in rows] == [2, 5]
    assert all(row.loaded == discovery.loaded and row.scene_version == 0 for row in rows)
    with discovery.sessions.access_objects(tuple(row.view for row in rows)) as access:
        assert [item.address for item in access.objects] == ["11", "12"]
    assert discovery.application.snapshot() == before
    assert [
        (view.camera, view.grid_z_scale) for view in discovery.application.native.view_rows
    ] == settings
    assert discovery.application.mutations == 0
    rendered = discovery.service.render(
        RenderRequest(
            result=discovery.loaded.result, context=discovery.context, width=64, height=48
        )
    )
    assert isinstance(rendered.outcome, Failure)
    assert rendered.outcome.error.code == ErrorCode.STALE_OBJECT


def test_discovery_requires_trusted_binding(discovery: Discovery):
    outcome = discovery.service.list_views(discovery.loaded).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.STALE_OBJECT


@pytest.mark.parametrize("changed", ["stored_result", "other_result", "project"])
def test_discovery_rejects_stale_or_cross_result_identity(discovery: Discovery, store, changed):
    value(discovery.service.bind_result(discovery.loaded))
    supplied = discovery.loaded
    if changed == "stored_result":
        supplied = supplied.model_copy(
            update={"result": supplied.result.model_copy(update={"grid_id": GridId.new()})}
        )
    elif changed == "other_result":
        result = value(
            store.save_result(supplied.result.model_copy(update={"result_id": ResultId.new()}))
        )
        supplied = supplied.model_copy(update={"result": result})
    else:
        discovery.application.native.root_address = "replaced-project"
    outcome = discovery.service.list_views(supplied).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.STALE_OBJECT


@pytest.mark.parametrize("addresses", [("11", "11"), ("not-issued",)])
def test_discovery_rejects_duplicate_or_unissued_native_addresses(
    discovery: Discovery, monkeypatch, addresses
):
    value(discovery.service.bind_result(discovery.loaded))
    camera = discovery.application.native.view_rows[0].camera
    monkeypatch.setattr(
        discovery.backend,
        "list_views",
        lambda access, case_address: tuple(
            NativeViewState(address=address, camera=camera, vertical_exaggeration=1)
            for address in addresses
        ),
    )
    outcome = discovery.service.list_views(discovery.loaded).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.STALE_OBJECT


def test_discovery_rejects_observable_project_change_during_read(discovery: Discovery):
    value(discovery.service.bind_result(discovery.loaded))

    def replace_project():
        discovery.application.native.root_address = "changed-during-read"

    discovery.application.native.on_read = replace_project
    outcome = discovery.service.list_views(discovery.loaded).outcome
    assert isinstance(outcome, Failure)
    assert outcome.error.code == ErrorCode.STALE_OBJECT


def test_discovery_holds_session_access_during_native_read(discovery: Discovery):
    value(discovery.service.bind_result(discovery.loaded))
    attempts = []
    discovery.application.native.on_read = lambda: attempts.append(
        discovery.sessions.inspect_project(discovery.loaded.result.model.session_id)
    )
    assert len(value(discovery.service.list_views(discovery.loaded))) == 2
    assert len(attempts) == 1 and isinstance(attempts[0].outcome, Failure)
    assert attempts[0].outcome.error.code == ErrorCode.BUSY
