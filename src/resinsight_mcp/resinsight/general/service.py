"""Load persisted GRDECL inputs and verify native values before rendering."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import numpy as np
import rips

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.observations import Camera
from resinsight_mcp.contracts.sessions import ObjectRef
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.models.general.arrays import fail, operation, value
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication
from resinsight_mcp.resinsight.views._camera import camera_matches, read_camera, view_matrix
from resinsight_mcp.resinsight.views._capture import capture_image
from resinsight_mcp.resinsight.views.rips import _Case, _Grid, _View
from resinsight_mcp.resinsight.wells._rips_types import StringValues

from .records import (
    EditedGrid,
    GridEdit,
    GridLoadRequest,
    GridObservation,
    GridRenderRequest,
    GridRestoreRequest,
    GridVerification,
    GridVerifyRequest,
    LoadedGrid,
    VerifiedCell,
)


class _Count(Protocol):
    active_cell_count: int
    reservoir_cell_count: int


class _Chunk(Protocol):
    values: list[float]


class _Point(Protocol):
    x: float
    y: float
    z: float


class _Corners(Protocol):
    c0: _Point
    c1: _Point
    c2: _Point
    c3: _Point
    c4: _Point
    c5: _Point
    c6: _Point
    c7: _Point


class _CornerChunk(Protocol):
    cells: list[_Corners]


class _NativeGrid(_Grid, Protocol):
    def cell_corners_async(self) -> Iterator[_CornerChunk]: ...


class _GridCase(_Case, Protocol):
    file_path: str

    def grid(self, index: int) -> _NativeGrid: ...

    def cell_count(self) -> _Count: ...
    def grid_unit_system(self) -> StringValues: ...
    def create_view(self) -> _View: ...
    def active_cell_property_async(
        self, property_type: str, property_name: str, time_step: int
    ) -> Iterator[_Chunk]: ...


class _Project(Protocol):
    def load_case(self, path: str) -> _GridCase: ...
    def cases(self) -> list[_GridCase]: ...
    def views(self) -> list[_View]: ...


def application(access: ApplicationAccess) -> RipsApplication:
    if not isinstance(access.application, RipsApplication):
        fail("Geological display requires the configured native RipsApplication.")
    return access.application


class GeneralGridService:
    def __init__(
        self, models: GeneralModelService, sessions: ResInsightSessionService, root: Path
    ) -> None:
        self.models = models
        self.sessions = sessions
        self.root = root
        self._loaded: dict[str, LoadedGrid] = {}

    def require_loaded(self, loaded: LoadedGrid) -> None:
        if self._loaded.get(loaded.case.object_id) != loaded:
            fail("Load or restore the exact geological binding first.", ErrorCode.STALE_OBJECT)

    def refresh(self, loaded: LoadedGrid, case: ObjectRef, view: ObjectRef) -> LoadedGrid:
        refreshed = LoadedGrid(**loaded.model_dump(exclude={"case", "view"}), case=case, view=view)
        self._loaded[case.object_id] = refreshed
        return refreshed

    def verify_access(
        self, access: ApplicationAccess, loaded: LoadedGrid, case_address: str
    ) -> None:
        self.require_loaded(loaded)
        app = application(access)
        case = next(
            c for c in cast(_Project, app.project()).cases() if str(c.address()) == case_address
        )
        if not hasattr(case, "grid_unit_system"):
            fail(
                "General wells require the native grid-unit query and matching RIPS client.",
                ErrorCode.UNSUPPORTED_OPERATION,
            )
        expected = "METRIC" if self.models.manifest(loaded.model).length_unit == "m" else "FIELD"
        if app.call(case.grid_unit_system).values != [expected]:
            fail("The native case unit system differs from the authored model.")
        app.call(lambda: self.verify(case, loaded))

    def verify(self, case: _GridCase, loaded: LoadedGrid) -> float:
        model = value(self.models.inspect(loaded.model))
        shape = model.shape
        dimensions = case.grid(0).dimensions()
        counts = case.cell_count()
        if (dimensions.i, dimensions.j, dimensions.k) != (shape.nx, shape.ny, shape.nz) or (
            counts.reservoir_cell_count,
            counts.active_cell_count,
        ) != (shape.cells, model.active_cells):
            fail("Native dimensions or active cell counts differ from the authored model.")
        if Path(case.file_path) != loaded.source:
            fail("The native case source differs from the authored model.")
        manifest = self.models.manifest(loaded.model)
        active = self.models.arrays.read(manifest.actnum) != 0
        maximum_error = 0.0
        for field in manifest.fields:
            expected = self.models.arrays.read(field.array)[active]
            offset = 0
            for chunk in case.active_cell_property_async("INPUT_PROPERTY", field.name, 0):
                actual = np.asarray(chunk.values, dtype=np.float64)
                end = offset + len(actual)
                if end > len(expected) or not np.allclose(
                    actual, expected[offset:end], rtol=1e-6, atol=1e-8
                ):
                    fail(f"Native active property {field.name} differs from the authored values.")
                maximum_error = max(
                    maximum_error, float(np.max(np.abs(actual - expected[offset:end]), initial=0))
                )
                offset = end
            if offset != len(expected):
                fail(f"Native active property {field.name} has a different value count.")
        return maximum_error

    @operation
    def load(self, request: GridLoadRequest) -> LoadedGrid:
        if request.model.session_id != request.context.session_id:
            fail("The model and native context must belong to the same session.")
        model = value(self.models.inspect(request.model))
        directory = self.root / "geological-sources" / str(request.model.revision_id) / str(uuid4())
        if directory.resolve() != directory:
            fail("Native sources require an owned canonical directory.", ErrorCode.INVALID_PATH)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "model.GRDECL"
        with path.open("x") as stream:
            self.models.export_grdecl(request.model, stream)

        def change(access: ApplicationAccess) -> tuple[str, str]:
            app = application(access)

            def native() -> tuple[str, str]:
                project = cast(_Project, app.project())
                case = project.load_case(str(path))
                view = case.create_view()
                return str(case.address()), str(view.address())

            return app.call(native, mutation=True)

        mutation = self.sessions.mutate_project(request.context, change)
        refs = {
            native.address: item.ref
            for native, item in zip(
                mutation.access.objects, mutation.access.project.objects, strict=True
            )
        }
        loaded = LoadedGrid(
            receipt=ArtifactRef(session_id=request.model.session_id, artifact_id=ArtifactId.new()),
            model=request.model,
            case=refs[mutation.value[0]],
            view=refs[mutation.value[1]],
            source=path,
            global_cells=model.shape.cells,
            active_cells=model.active_cells,
            verified_properties=tuple(
                field.name for field in self.models.manifest(request.model).fields
            ),
        )
        app = application(mutation.access)
        try:
            case = next(
                case
                for case in cast(_Project, app.project()).cases()
                if str(case.address()) == mutation.value[0]
            )
            app.call(lambda: self.verify(case, loaded))
        except Exception as error:
            raise ContractError(
                Error(
                    code=ErrorCode.EXECUTION_FAILED,
                    message=f"The loaded geological grid could not be verified: {error}",
                    effect=MutationEffect.UNKNOWN,
                )
            ) from error
        self.models.arrays.publish(loaded.receipt, loaded, ArtifactKind.METADATA)
        self._loaded[loaded.case.object_id] = loaded
        return loaded

    def _validate_render(self, request: GridRenderRequest) -> None:
        if self._loaded.get(request.loaded.case.object_id) != request.loaded:
            fail(
                "Load the exact geological model in this service before rendering.",
                ErrorCode.STALE_OBJECT,
            )
        model = value(self.models.inspect(request.loaded.model))
        if request.property not in request.loaded.verified_properties:
            fail("The property must be an authored cell field.")
        if request.slice_j is not None and request.slice_j >= model.shape.ny:
            fail("The section index exceeds the model's J dimension.")
        self.models.arrays.policy.require_memory(request.width * request.height * 16 / 1024**2)

    @operation
    def render(self, request: GridRenderRequest) -> EditedGrid:
        self._validate_render(request)
        with self.sessions.access_objects((request.loaded.case, request.loaded.view)) as access:
            app = application(access)
            project = cast(_Project, app.project())
            case = next(c for c in project.cases() if str(c.address()) == access.objects[0].address)
            view = next(v for v in project.views() if str(v.address()) == access.objects[1].address)
            if view.case().address() != case.address():
                fail("The view belongs to another native case.", ErrorCode.STALE_OBJECT)
            maximum_error = app.call(lambda: self.verify(case, request.loaded))
            try:
                view = app.call(lambda: self._apply(project, view, request), mutation=True)
                actual = app.call(
                    lambda: read_camera(
                        view.camera_matrix,
                        view.camera_point_of_interest,
                        view.perspective_projection,
                        view.actual_camera_field_of_view_y_degrees,
                        view.actual_camera_parallel_projection_height,
                    )
                )
                if not camera_matches(request.camera, actual):
                    raise ContractError(
                        Error(
                            code=ErrorCode.RENDER_FAILED,
                            message="The native camera differs from the requested view.",
                            effect=MutationEffect.UNKNOWN,
                        )
                    )
            except Exception as error:
                raise ContractError(
                    Error(
                        code=ErrorCode.EXECUTION_FAILED,
                        message=f"The native view edit could not be confirmed: {error}",
                        effect=MutationEffect.UNKNOWN,
                    )
                ) from error
            edit = GridEdit(request=request, native_camera=actual, applied_at=datetime.now(UTC))
            return EditedGrid(
                edit=edit, observation=self._capture(app, view, request, actual, maximum_error)
            )

    @operation
    def _capture(
        self,
        app: RipsApplication,
        view: _View,
        request: GridRenderRequest,
        actual: Camera,
        maximum_error: float,
    ) -> GridObservation:
        image = capture_image(
            self.models.store,
            request.loaded.model.session_id,
            request.width,
            request.height,
            lambda folder, width, height: app.call(
                lambda: view.export_snapshot(
                    prefix="geology", export_folder=str(folder), width=width, height=height
                )
            ),
        )
        observation = GridObservation(
            artifact=ArtifactRef(
                session_id=request.loaded.model.session_id, artifact_id=ArtifactId.new()
            ),
            request=request,
            image=image,
            captured_at=datetime.now(UTC),
            native_camera=actual,
            maximum_property_error=maximum_error,
        )
        self.models.arrays.publish(observation.artifact, observation, ArtifactKind.METADATA)
        return observation

    def _apply(self, project: _Project, view: _View, request: GridRenderRequest) -> _View:
        view.validate_view_controls()
        colors = view.cell_result()
        colors.result_type = "INPUT_PROPERTY"
        colors.result_variable = request.property
        colors.porosity_model_type = "MATRIX_MODEL"
        colors.update()
        filters = view.range_filters()
        for item in filters.cell_filters():
            item.delete()
        filters.active = True
        filters.combine_filter_mode = "AND"
        filters.update()
        if request.slice_j is not None:
            shape = self.models.manifest(request.loaded.model).shape
            item = filters.add_new_object(rips.CellRangeFilter, "CellFilters")
            item.is_checked = True
            item.grid_index = 0
            item.filter_type = "INCLUDE"
            item.start_index_i, item.start_index_j, item.start_index_k = 1, request.slice_j + 1, 1
            item.cell_count_i, item.cell_count_j, item.cell_count_k = shape.nx, 1, shape.nz
            item.update()
        view.grid_z_scale = request.vertical_exaggeration
        view.update()
        view.set_camera_projection(
            perspective=request.camera.projection == "perspective",
            field_of_view_y_degrees=request.camera.field_of_view_degrees or 40,
            parallel_projection_height=2 * (request.camera.parallel_scale or 1),
        )
        address = view.address()
        view = next(item for item in project.views() if item.address() == address)
        view.camera_matrix = view_matrix(request.camera)
        view.camera_point_of_interest = list(request.camera.target)
        view.update()
        return next(item for item in project.views() if item.address() == address)

    @operation
    def inspect_native(self, request: GridVerifyRequest) -> GridVerification:
        loaded = request.loaded
        if self._loaded.get(loaded.case.object_id) != loaded:
            fail("Load this geological model before native verification.", ErrorCode.STALE_OBJECT)
        expected = self.models.cell_corners(loaded.model, request.global_indices)
        with self.sessions.access_objects((loaded.case,)) as access:
            app = application(access)
            case = next(
                c
                for c in cast(_Project, app.project()).cases()
                if str(c.address()) == access.objects[0].address
            )
            property_error = app.call(lambda: self.verify(case, loaded))

            def inspect() -> tuple[VerifiedCell, ...]:
                cells = []
                index = 0
                for chunk in case.grid(0).cell_corners_async():
                    for cell in chunk.cells:
                        if index in expected:
                            actual = tuple(
                                (point.x, point.y, point.z)
                                for point in (
                                    cell.c0,
                                    cell.c1,
                                    cell.c2,
                                    cell.c3,
                                    cell.c4,
                                    cell.c5,
                                    cell.c6,
                                    cell.c7,
                                )
                            )
                            error = float(np.max(np.abs(np.array(actual) - expected[index])))
                            if not np.allclose(actual, expected[index], rtol=1e-7, atol=1e-6):
                                fail(f"Native corners differ for global cell {index}.")
                            cells.append(
                                VerifiedCell(
                                    global_index=index,
                                    corners=actual,
                                    maximum_coordinate_error=error,
                                )
                            )
                        index += 1
                    if index > max(expected):
                        break
                if len(cells) != len(expected):
                    fail("Native corner data ended before every selected cell was read.")
                return tuple(cells)

            return GridVerification(
                loaded=loaded,
                cells=app.call(inspect),
                maximum_property_error=property_error,
                coordinate_unit=self.models.manifest(loaded.model).length_unit,
            )

    @operation
    def restore(self, request: GridRestoreRequest) -> LoadedGrid:
        with self.models.store.open_artifact(request.receipt) as stream:
            stored = LoadedGrid.model_validate_json(stream.read())
        if stored.receipt != request.receipt or any(
            ref.context.session_id != stored.model.session_id
            for ref in (request.case, request.view)
        ):
            fail("The saved geological receipt belongs to a different session.")
        loaded = stored.model_copy(update={"case": request.case, "view": request.view})
        with self.sessions.access_objects((request.case, request.view)) as access:
            app = application(access)
            project = cast(_Project, app.project())
            case = next(c for c in project.cases() if str(c.address()) == access.objects[0].address)
            view = next(v for v in project.views() if str(v.address()) == access.objects[1].address)
            if view.case().address() != case.address():
                fail("The restored view belongs to a different case.", ErrorCode.STALE_OBJECT)
            app.call(lambda: self.verify(case, loaded))
            self._loaded[loaded.case.object_id] = loaded
            return loaded
