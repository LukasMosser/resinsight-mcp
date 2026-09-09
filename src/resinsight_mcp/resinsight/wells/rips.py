"""Use the session's existing RIPS client for modeled FIELD wells."""

from collections.abc import Callable, Sequence
from math import isclose
from typing import cast

import rips
from pydantic import ValidationError

from resinsight_mcp.contracts.engineering import CellIndex, CoordinateFrame
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.sessions import ProcessIdentity
from resinsight_mcp.contracts.wells import WellStatus
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


def _inspect(well: Well, coordinates: CoordinateFrame) -> NativeWell:
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
    definition = ModeledWellDefinition(
        name=well.name,
        coordinates=coordinates,
        targets=tuple(
            TrajectoryPoint(
                x_ft=item.target_point[0], y_ft=item.target_point[1], depth_ft=item.target_point[2]
            )
            for item in targets
        ),
        perforations=tuple(
            PerforationInterval(
                start_md_ft=item.start_measured_depth,
                end_md_ft=item.end_measured_depth,
                diameter_ft=item.diameter,
                skin=item.skin_factor,
            )
            for item in perforations
        ),
    )
    arrays = well.trajectory_properties(resampling_interval=50.0)
    samples = tuple(
        TrajectorySample(x_ft=x, y_ft=y, depth_ft=z, measured_depth_ft=md)
        for x, y, z, md in zip(
            arrays["coordinate_x"],
            arrays["coordinate_y"],
            arrays["coordinate_z"],
            arrays["measured_depth"],
            strict=True,
        )
    )
    definition.require_trajectory(samples)
    return NativeWell(str(well.address()), definition, samples)


def _set_definition(well: Well, definition: ModeledWellDefinition) -> NativeWell:
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
        geometry.append_well_target(
            coordinate=[target.x_ft, target.y_ft, target.depth_ft], absolute=True
        )
    for interval in definition.perforations:
        well.append_perforation_interval(
            start_md=interval.start_md_ft,
            end_md=interval.end_md_ft,
            diameter=interval.diameter_ft,
            skin_factor=interval.skin,
        )
    return _inspect(well, definition.coordinates)


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


class RipsWellBackend:
    def __init__(self) -> None:
        self._loaded_geometry: dict[tuple[ProcessIdentity, str], tuple[float, ...]] = {}

    def load(self, access: ApplicationAccess, materialized: MaterializedModel) -> str:
        application = _application(access)
        project = _project(application)

        def change() -> str:
            case = project.load_prepared_input_grid(path=str(materialized.entrypoint))
            loaded = case.import_properties(file_names=[str(materialized.property_file)])
            if set(loaded.values) != {
                name for name, _ in materialized.inspection.properties.keyword_arrays()
            }:
                raise _fail("The native case did not import every prepared property.")
            _verify_values(case, materialized.inspection)
            address = str(case.address())
            self._loaded_geometry[(application.process, address)] = _corners(case)
            return address

        return _mutate(application, change)

    def verify_case(
        self, access: ApplicationAccess, address: str, expected: ModelInspection
    ) -> None:
        application = _application(access)
        baseline = self._loaded_geometry.get((application.process, address))
        if baseline is None:
            raise _fail("The case was not loaded by this well backend.", ErrorCode.STALE_OBJECT)

        def inspect() -> None:
            case = _one(_project(application).cases(), address)
            _verify_values(case, expected)
            if not _values_match(_corners(case), baseline):
                raise _fail("The prepared native corner geometry changed.", ErrorCode.STALE_OBJECT)

        _read(application, inspect)

    def create(
        self, access: ApplicationAccess, case_address: str, definition: ModeledWellDefinition
    ) -> NativeWell:
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
        definition: ModeledWellDefinition,
    ) -> NativeWell:
        application = _application(access)
        project = _project(application)
        _read(application, lambda: _one(project.cases(), case_address))
        well = _read(application, lambda: _one(project.well_paths(), well_address))
        if well.name != definition.name:
            raise _fail("A modeled well update cannot rename the prepared well.")
        return _mutate(application, lambda: _set_definition(well, definition))

    def inspect(
        self, access: ApplicationAccess, well_address: str, coordinates: CoordinateFrame
    ) -> NativeWell:
        application = _application(access)
        return _read(
            application,
            lambda: _inspect(_one(_project(application).well_paths(), well_address), coordinates),
        )

    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> NativeCompletions:
        application = _application(access)

        def read() -> NativeCompletions:
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
                    CompletionConnection.model_validate(
                        {
                            "cell": CellIndex(
                                i=row.grid_i - 1, j=row.grid_j - 1, k=row.upper_k - 1
                            ),
                            "status": WellStatus(row.open_shut_flag),
                            "compdat_factor_field": row.transmissibility,
                            "permeability_length_md_ft": row.kh,
                            "diameter_ft": row.diameter,
                            "skin": row.skin_factor,
                            "direction": row.direction,
                            "start_md_ft": row.start_md,
                            "end_md_ft": row.end_md,
                        }
                    )
                )
            if not connections:
                raise _fail("The native well has no active reservoir connections.")
            reference_depth = settings.reference_depth_for_export
            return NativeCompletions(
                Wellhead(
                    i=head.grid_i - 1,
                    j=head.grid_j - 1,
                    reference_depth_ft=None if reference_depth == "" else reference_depth,
                ),
                tuple(connections),
            )

        return _read(application, read)
