"""Immutable regional tables with explicit numeric columns and units."""

from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.records import NamedArray

type Keyword = Literal["PVTW", "ROCK", "DENSITY", "PVDG", "PVTO", "SWOF", "SGOF", "EQUIL", "RSVD"]
type RegionKeyword = Literal["PVTNUM", "SATNUM", "EQLNUM"]


class UniformRegion(Record):
    kind: Literal["uniform"] = "uniform"
    value: PositiveInt


class ArrayRegion(Record):
    kind: Literal["array"] = "array"
    array: ArtifactRef


class RegionAssignment(Record):
    keyword: RegionKeyword
    values: Annotated[UniformRegion | ArrayRegion, Field(discriminator="kind")]


class TableKey(Record):
    keyword: Keyword
    region: PositiveInt


class ColumnInput(Record):
    name: str
    array: ArtifactRef


class TableInput(TableKey):
    columns: tuple[ColumnInput, ...]


class TableInfo(TableKey):
    rows: PositiveInt
    columns: tuple[NamedArray, ...]


class PhysicsCreate(Record):
    model: ModelRef
    profile: Literal["black_oil_disgas_rsvd"]
    regions: tuple[RegionAssignment, ...]


class PhysicsEdit(Record):
    parent: ArtifactRef
    tables: tuple[TableInput, ...] = ()
    remove_tables: tuple[TableKey, ...] = ()
    regions: tuple[RegionAssignment, ...] | None = None


class RegionCoverage(Record):
    keyword: RegionKeyword
    required_regions: PositiveInt
    complete_regions: NonNegativeInt


class PhysicsInfo(Record):
    artifact: ArtifactRef
    version: Literal["general-physics-v1"] = "general-physics-v1"
    parent: ArtifactRef | None = None
    model: ModelRef
    profile: Literal["black_oil_disgas_rsvd"]
    unit_system: Literal["METRIC", "FIELD"]
    table_count: NonNegativeInt
    row_count: NonNegativeInt
    coverage: tuple[RegionCoverage, ...]
    complete: bool
    simulation_ready: Literal[False] = False


class PhysicsManifest(Record):
    info: PhysicsInfo
    regions: tuple[RegionAssignment, ...]
    tables: tuple[TableInfo, ...]


class TablePageRequest(Record):
    physics: ArtifactRef
    offset: NonNegativeInt = 0
    count: PositiveInt


class TablePage(Record):
    physics: ArtifactRef
    tables: tuple[TableInfo, ...]
    next_offset: NonNegativeInt | None


class PhysicsRegions(Record):
    physics: ArtifactRef
    regions: tuple[RegionAssignment, ...]


class SchemaRequest(Record):
    unit_system: Literal["METRIC", "FIELD"]


class ColumnSchema(Record):
    name: str
    unit: str
    dtype: Literal["float64", "int64"] = "float64"


class TableSchema(Record):
    keyword: Keyword
    region_keyword: RegionKeyword
    columns: tuple[ColumnSchema, ...]
    minimum_rows: PositiveInt
    single_row: bool
    rules: str


class PhysicsSchema(Record):
    profile: Literal["black_oil_disgas_rsvd"] = "black_oil_disgas_rsvd"
    unit_system: Literal["METRIC", "FIELD"]
    tables: tuple[TableSchema, ...]
    table_count_ceiling: None = None
    table_row_ceiling: None = None
    region_count_ceiling: None = None
