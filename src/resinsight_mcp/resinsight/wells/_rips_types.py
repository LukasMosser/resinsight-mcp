"""Supported generated RIPS methods used by the modeled well backend."""

from typing import Literal, Protocol


class PdmObject(Protocol):
    def address(self) -> int: ...
    def update(self) -> None: ...
    def delete(self) -> None: ...


class Vector(Protocol):
    x: float
    y: float
    z: float


class Dimensions(Protocol):
    i: int
    j: int
    k: int


class CellCorners(Protocol):
    c0: Vector
    c1: Vector
    c2: Vector
    c3: Vector
    c4: Vector
    c5: Vector
    c6: Vector
    c7: Vector


class CellInfo(Protocol):
    grid_index: int
    local_ijk: Dimensions


class Grid(Protocol):
    def dimensions(self) -> Dimensions: ...
    def cell_centers(self) -> list[Vector]: ...
    def cell_corners(self) -> list[CellCorners]: ...


class StringValues(Protocol):
    values: list[str]


class Case(PdmObject, Protocol):
    id: int

    def grid(self) -> Grid: ...
    def import_properties(self, file_names: list[str]) -> StringValues: ...
    def available_properties(self, property_type: str) -> list[str]: ...
    def active_cell_property(
        self, property_type: str, property_name: str, time_step: int
    ) -> list[float]: ...
    def cell_info_for_active_cells(self) -> list[CellInfo]: ...


class Target(PdmObject, Protocol):
    target_point: list[float]
    use_fixed_azimuth: bool
    use_fixed_inclination: bool


class Geometry(PdmObject, Protocol):
    use_auto_generated_target_at_sea_level: bool
    reference_point: list[float]
    md_at_first_target: float
    attached_to_parent_well: bool
    air_gap: float

    def append_well_target(self, coordinate: list[float], absolute: bool) -> Target: ...
    def well_path_targets(self) -> list[Target]: ...


class Perforation(PdmObject, Protocol):
    is_checked: bool
    start_measured_depth: float
    end_measured_depth: float
    diameter: float
    skin_factor: float

    def cell_filter(self) -> object | None: ...
    def valves(self) -> list[object]: ...


class Perforations(Protocol):
    is_checked: bool

    def perforations(self) -> list[Perforation]: ...


class Completions(Protocol):
    def perforations(self) -> Perforations | None: ...


class CompletionSettings(Protocol):
    reference_depth_for_export: float | Literal[""] | None
    well_name_for_export: str


class CompdatRow(Protocol):
    well_name: str
    grid_i: int
    grid_j: int
    upper_k: int
    lower_k: int
    open_shut_flag: str
    transmissibility: float
    diameter: float
    kh: float
    skin_factor: float
    direction: str
    start_md: float
    end_md: float
    grid_name: str


class WelspecsRow(Protocol):
    well_name: str
    grid_i: int
    grid_j: int
    grid_name: str


class CompletionTables(Protocol):
    compdat: list[CompdatRow]
    welspecs: list[WelspecsRow]


class Well(PdmObject, Protocol):
    name: str

    def descendants(self, cls: object) -> list[object]: ...

    def well_path_geometry(self) -> Geometry: ...
    def completions(self) -> Completions | None: ...
    def completion_settings(self) -> CompletionSettings | None: ...
    def append_perforation_interval(
        self, start_md: float, end_md: float, diameter: float, skin_factor: float
    ) -> Perforation: ...
    def trajectory_properties(self, resampling_interval: float) -> dict[str, list[float]]: ...
    def completion_data(self, case_id: int) -> CompletionTables: ...


class WellCollection(Protocol):
    def create_modeled_well_path_for_case(self, case_id: int, name: str) -> Well: ...


class Project(Protocol):
    def cases(self) -> list[Case]: ...
    def well_paths(self) -> list[Well]: ...
    def well_path_collection(self) -> WellCollection: ...
    def load_prepared_input_grid(self, path: str) -> Case: ...
