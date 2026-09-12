"""Use the session's existing RIPS client for modeled FIELD wells."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import cast

import rips
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import CellIndex, CoordinateFrame
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.wells import WellStatus
from resinsight_mcp.models.general.wells import (
    GeneralConnection,
    GeneralWellhead,
    Sample,
    WellGeometry,
)
from resinsight_mcp.models.imports import MaterializedModel, ModelInspection
from resinsight_mcp.models.wells.records import (
    CompletionConnection,
    ModeledWellDefinition,
    PerforationInterval,
    TrajectoryPoint,
    TrajectorySample,
    Wellhead,
)
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication

from ._backend import NativeCompletions, NativeWell
from ._rips_types import Case, Geometry, PdmObject, Perforation, Project, Well


def _fail(message: str, code: ErrorCode = ErrorCode.INVALID_MODEL) -> ContractError:
    return ContractError(Error(code=code, message=message))


def _one[T: PdmObject](objects: Sequence[T], address: str) -> T:
    matches = [item for item in objects if str(item.address()) == address]
    if len(matches) != 1:
        raise _fail("The native object is absent or ambiguous.", ErrorCode.STALE_OBJECT)
    return matches[0]


def _application(access: ApplicationAccess) -> RipsApplication:
    if not isinstance(access.application, RipsApplication):
        raise _fail("The well backend requires the session's RipsApplication.")
    return access.application


def _project(application: RipsApplication) -> Project:
    return cast(Project, application.project())


def _values_match(actual: Sequence[float], expected: Sequence[float]) -> bool:
    return len(actual) == len(expected) and all(
        isclose(first, second, rel_tol=1e-6, abs_tol=1e-6)
        for first, second in zip(actual, expected, strict=True)
    )


def _corners(case: Case) -> tuple[float, ...]:
    return tuple(
        coordinate
        for cell in case.grid().cell_corners()
        for point in (cell.c0, cell.c1, cell.c2, cell.c3, cell.c4, cell.c5, cell.c6, cell.c7)
        for coordinate in (point.x, point.y, point.z)
    )


def _verify_values(case: Case, expected: ModelInspection) -> None:
    dims = case.grid().dimensions()
    if (dims.i, dims.j, dims.k) != expected.summary.dimensions:
        raise _fail(
            "The native grid dimensions differ from the fixed model.", ErrorCode.STALE_OBJECT
        )
    cells = case.cell_info_for_active_cells()
    if any(cell.grid_index != 0 for cell in cells):
        raise _fail("Prepared wells support the main grid only.")
    observed_cells = tuple(
        CellIndex(i=cell.local_ijk.i, j=cell.local_ijk.j, k=cell.local_ijk.k) for cell in cells
    )
    if observed_cells != expected.active_cells:
        raise _fail("The native active cells differ from the fixed model.", ErrorCode.STALE_OBJECT)
    checks = (
        ("depths", [point.z for point in case.grid().cell_centers()], expected.cell_depths_ft),
        (
            "volumes",
            case.active_cell_property("STATIC_NATIVE", "riCELLVOLUME", 0),
            expected.cell_volumes_ft3,
        ),
    )
    for label, observed, wanted in checks:
        if not _values_match(observed, wanted):
            raise _fail(
                f"The native cell {label} differ from the fixed model.", ErrorCode.STALE_OBJECT
            )
    for name, wanted in expected.properties.keyword_arrays():
        category = "STATIC_NATIVE" if name in {"DX", "DY", "DZ"} else "INPUT_PROPERTY"
        if name not in case.available_properties(category):
            raise _fail(
                f"The prepared case has no {category} property {name}.", ErrorCode.STALE_OBJECT
            )
        if not _values_match(case.active_cell_property(category, name, 0), wanted):
            raise _fail(
                f"The native {name} values differ from the fixed model.", ErrorCode.STALE_OBJECT
            )


def _perforations(well: Well) -> list[Perforation]:
    completions = well.completions()
    collection = None if completions is None else completions.perforations()
    if collection is None or not collection.is_checked:
        raise _fail(
            "The modeled well has no enabled perforation collection.", ErrorCode.STALE_OBJECT
        )
    return collection.perforations()


def _geometry(well: Well) -> Geometry:
    geometry = well.well_path_geometry()
    if (
        geometry.use_auto_generated_target_at_sea_level
        or geometry.attached_to_parent_well
        or geometry.md_at_first_target != 0.0
        or geometry.air_gap != 0.0
        or geometry.reference_point != [0.0, 0.0, 0.0]
    ):
        raise _fail(
            "The modeled well geometry settings changed outside this service.",
            ErrorCode.STALE_OBJECT,
        )
    return geometry


@dataclass(frozen=True)
class NativeGeometry:
    address: str
    definition: WellGeometry
    trajectory: tuple[Sample, ...]


@dataclass(frozen=True)
class GeneralCompletions:
    wellhead: GeneralWellhead
    connections: tuple[GeneralConnection, ...]


def _inspect(well: Well, sampling_distance: float) -> NativeGeometry:
    if not isinstance(well, rips.ModeledWellPath):
        raise _fail("The native path is not a modeled well.", ErrorCode.STALE_OBJECT)
    geometry = _geometry(well)
    if well.descendants(rips.WellPathFracture) or well.descendants(rips.Fishbones):
        raise _fail(
            "Fractures and fishbones are outside this well service.", ErrorCode.STALE_OBJECT
        )
    targets = geometry.well_path_targets()
    if any(target.use_fixed_azimuth or target.use_fixed_inclination for target in targets):
        raise _fail("Fixed target angles are outside this well service.", ErrorCode.STALE_OBJECT)
    perforations = _perforations(well)
    if any(
        not item.is_checked or item.cell_filter() is not None or item.valves()
        for item in perforations
    ):
        raise _fail(
            "The native perforations contain unsupported filters, valves, or disabled intervals.",
            ErrorCode.STALE_OBJECT,
        )
    settings = well.completion_settings()
    if settings is None or settings.well_name_for_export not in {"", well.name}:
        raise _fail(
            "The native simulator well name differs from the modeled well.", ErrorCode.STALE_OBJECT
        )
    definition = WellGeometry(
        name=well.name,
        targets=tuple(
            (item.target_point[0], item.target_point[1], item.target_point[2]) for item in targets
        ),
        intervals=tuple(
            (item.start_measured_depth, item.end_measured_depth, item.diameter, item.skin_factor)
            for item in perforations
        ),
        sampling_distance=sampling_distance,
    )
    arrays = well.trajectory_properties(resampling_interval=sampling_distance)
    samples = tuple(
        zip(
            arrays["coordinate_x"],
            arrays["coordinate_y"],
            arrays["coordinate_z"],
            arrays["measured_depth"],
            strict=True,
        )
    )
    definition.require_trajectory(samples)
    return NativeGeometry(str(well.address()), definition, samples)


def _set_definition(well: Well, definition: WellGeometry) -> NativeGeometry:
    geometry = well.well_path_geometry()
    geometry.use_auto_generated_target_at_sea_level = False
    geometry.reference_point = [0.0, 0.0, 0.0]
    geometry.md_at_first_target = 0.0
    geometry.update()
    for target in geometry.well_path_targets():
        target.delete()
    for interval in _perforations(well):
        interval.delete()
    for target in definition.targets:
        geometry.append_well_target(coordinate=list(target), absolute=True)
    for start, end, diameter, skin in definition.intervals:
        well.append_perforation_interval(
            start_md=start,
            end_md=end,
            diameter=diameter,
            skin_factor=skin,
        )
    return _inspect(well, definition.sampling_distance)


def _mutate[T](application: RipsApplication, action: Callable[[], T]) -> T:
    try:
        return application.call(action, mutation=True)
    except ContractError as error:
        raise ContractError(
            error.error.model_copy(update={"effect": MutationEffect.UNKNOWN})
        ) from error
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise ContractError(
            Error(
                code=ErrorCode.EXECUTION_FAILED,
                message=f"The native well operation may be incomplete: {error}",
                effect=MutationEffect.UNKNOWN,
            )
        ) from error


def _read[T](application: RipsApplication, action: Callable[[], T]) -> T:
    try:
        return application.call(action)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise _fail(
            f"The native well inspection returned invalid data: {error}",
            ErrorCode.EXECUTION_FAILED,
        ) from error


class RipsGeometryBackend:
    def load(self, access: ApplicationAccess, materialized: MaterializedModel) -> str:
        application = _application(access)
        project = _project(application)

        def change() -> str:
            grid = materialized.directory.parent / "grid.EGRID"
            project.export_prepared_input_grid(
                path=str(materialized.entrypoint), output_path=str(grid)
            )
            case = project.load_case(path=str(grid), grid_only=True)
            loaded = case.import_properties(file_names=[str(materialized.property_file)])
            if set(loaded.values) != {
                name for name, _ in materialized.inspection.properties.keyword_arrays()
            }:
                raise _fail("The native case did not import every prepared property.")
            _verify_values(case, materialized.inspection)
            case.create_view()
            return str(case.address())

        return _mutate(application, change)

    def verify_case(
        self,
        access: ApplicationAccess,
        address: str,
        materialized: MaterializedModel,
        corners: tuple[float, ...],
    ) -> None:
        actual = self.case_geometry(access, address, materialized)
        if not _values_match(actual, corners):
            raise _fail("The prepared native corner geometry changed.", ErrorCode.STALE_OBJECT)

    def case_geometry(
        self, access: ApplicationAccess, address: str, materialized: MaterializedModel
    ) -> tuple[float, ...]:
        application = _application(access)

        def inspect() -> tuple[float, ...]:
            case = _one(_project(application).cases(), address)
            grid = materialized.directory.parent / "grid.EGRID"
            if case.file_path is None or Path(case.file_path) != grid:
                raise _fail("The native case uses another source file.", ErrorCode.STALE_OBJECT)
            if grid.resolve() != grid or not grid.is_file():
                raise _fail("The prepared grid source is unavailable.", ErrorCode.STALE_OBJECT)
            _verify_values(case, materialized.inspection)
            corners = _corners(case)
            if len(corners) != 24 * len(materialized.inspection.cell_depths_ft):
                raise _fail(
                    "The native case did not return every cell corner.", ErrorCode.STALE_OBJECT
                )
            return corners

        return _read(application, inspect)

    def create(
        self, access: ApplicationAccess, case_address: str, definition: WellGeometry
    ) -> NativeGeometry:
        application = _application(access)
        project = _project(application)
        case = _read(application, lambda: _one(project.cases(), case_address))
        if _read(
            application, lambda: any(well.name == definition.name for well in project.well_paths())
        ):
            raise _fail("The native project already contains that well name.", ErrorCode.CONFLICT)
        return _mutate(
            application,
            lambda: _set_definition(
                project.well_path_collection().create_modeled_well_path_for_case(
                    case_id=case.id, name=definition.name
                ),
                definition,
            ),
        )

    def update(
        self,
        access: ApplicationAccess,
        case_address: str,
        well_address: str,
        definition: WellGeometry,
    ) -> NativeGeometry:
        application = _application(access)
        project = _project(application)
        _read(application, lambda: _one(project.cases(), case_address))
        well = _read(application, lambda: _one(project.well_paths(), well_address))
        if well.name != definition.name:
            raise _fail("A modeled well update cannot rename the prepared well.")
        return _mutate(application, lambda: _set_definition(well, definition))

    def inspect(
        self, access: ApplicationAccess, well_address: str, sampling_distance: float
    ) -> NativeGeometry:
        application = _application(access)
        return _read(
            application,
            lambda: _inspect(
                _one(_project(application).well_paths(), well_address), sampling_distance
            ),
        )

    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> GeneralCompletions:
        application = _application(access)

        def read() -> GeneralCompletions:
            project = _project(application)
            case = _one(project.cases(), case_address)
            well = _one(project.well_paths(), well_address)
            settings = well.completion_settings()
            if settings is None:
                raise _fail("The native well has no completion settings.")
            tables = well.completion_data(case_id=case.id)
            if len(tables.welspecs) != 1 or tables.welspecs[0].well_name != well.name:
                raise _fail("Native WELSPECS does not identify this single modeled well.")
            head = tables.welspecs[0]
            if head.grid_name or head.grid_i < 1 or head.grid_j < 1:
                raise _fail("The native wellhead must identify a main-grid cell.")
            connections = []
            for row in tables.compdat:
                if row.well_name != well.name or row.grid_name or row.upper_k != row.lower_k:
                    raise _fail(
                        "Each native connection must identify one cell in this well's main grid."
                    )
                connections.append(
                    GeneralConnection.model_validate(
                        {
                            "cell": CellIndex(
                                i=row.grid_i - 1, j=row.grid_j - 1, k=row.upper_k - 1
                            ),
                            "status": WellStatus(row.open_shut_flag),
                            "factor": row.transmissibility,
                            "kh": row.kh,
                            "diameter": row.diameter,
                            "skin": row.skin_factor,
                            "direction": row.direction,
                            "start_md": row.start_md,
                            "end_md": row.end_md,
                        }
                    )
                )
            if not connections:
                raise _fail("The native well has no active reservoir connections.")
            reference_depth = settings.reference_depth_for_export
            return GeneralCompletions(
                GeneralWellhead(
                    i=head.grid_i - 1,
                    j=head.grid_j - 1,
                    reference_depth=None if reference_depth == "" else reference_depth,
                ),
                tuple(connections),
            )

        return _read(application, read)


def _general_definition(definition: ModeledWellDefinition) -> WellGeometry:
    return WellGeometry(
        name=definition.name,
        targets=tuple((p.x_ft, p.y_ft, p.depth_ft) for p in definition.targets),
        intervals=tuple(
            (p.start_md_ft, p.end_md_ft, p.diameter_ft, p.skin) for p in definition.perforations
        ),
        sampling_distance=50.0,
    )


def _field_well(native: NativeGeometry, coordinates: CoordinateFrame) -> NativeWell:
    return NativeWell(
        native.address,
        ModeledWellDefinition(
            name=native.definition.name,
            coordinates=coordinates,
            targets=tuple(
                TrajectoryPoint(x_ft=x, y_ft=y, depth_ft=z) for x, y, z in native.definition.targets
            ),
            perforations=tuple(
                PerforationInterval(
                    start_md_ft=start, end_md_ft=end, diameter_ft=diameter, skin=skin
                )
                for start, end, diameter, skin in native.definition.intervals
            ),
        ),
        tuple(
            TrajectorySample(x_ft=x, y_ft=y, depth_ft=z, measured_depth_ft=md)
            for x, y, z, md in native.trajectory
        ),
    )


class RipsWellBackend:
    """Preserve the existing FIELD contract through the shared native adapter."""

    def __init__(self) -> None:
        self.geometry = RipsGeometryBackend()

    load = RipsGeometryBackend.load
    verify_case = RipsGeometryBackend.verify_case
    case_geometry = RipsGeometryBackend.case_geometry

    def create(
        self, access: ApplicationAccess, case_address: str, definition: ModeledWellDefinition
    ) -> NativeWell:
        return _field_well(
            self.geometry.create(access, case_address, _general_definition(definition)),
            definition.coordinates,
        )

    def update(
        self,
        access: ApplicationAccess,
        case_address: str,
        well_address: str,
        definition: ModeledWellDefinition,
    ) -> NativeWell:
        return _field_well(
            self.geometry.update(
                access, case_address, well_address, _general_definition(definition)
            ),
            definition.coordinates,
        )

    def inspect(
        self, access: ApplicationAccess, well_address: str, coordinates: CoordinateFrame
    ) -> NativeWell:
        return _field_well(self.geometry.inspect(access, well_address, 50.0), coordinates)

    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> NativeCompletions:
        def convert() -> NativeCompletions:
            native = self.geometry.completions(access, case_address, well_address)
            return NativeCompletions(
                Wellhead(
                    i=native.wellhead.i,
                    j=native.wellhead.j,
                    reference_depth_ft=native.wellhead.reference_depth,
                ),
                tuple(
                    CompletionConnection(
                        cell=c.cell,
                        status=c.status,
                        compdat_factor_field=c.factor,
                        permeability_length_md_ft=c.kh,
                        diameter_ft=c.diameter,
                        skin=c.skin,
                        direction=c.direction,
                        start_md_ft=c.start_md,
                        end_md_ft=c.end_md,
                    )
                    for c in native.connections
                ),
            )

        return _read(_application(access), convert)
