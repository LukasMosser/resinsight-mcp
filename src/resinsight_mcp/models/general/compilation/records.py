"""Compact assembly and preparation receipts preserve exact source identities."""

from typing import Literal

from pydantic import NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.models import ArtifactRef


class DissolutionLimit(Record):
    value: NonNegativeFloat
    unit: Literal["sm3/sm3/day", "Mscf/stb/day"]


class AssemblyRequest(Record):
    schedule: ArtifactRef
    physics: ArtifactRef
    group: Text
    dissolution_limit: DissolutionLimit
    write_restart: bool
    parent: ArtifactRef | None = None
    exports: tuple[ArtifactRef, ...] = ()
    remove_exports: tuple[Text, ...] = ()
    omitted_fields: tuple[Text, ...] = ()


class AssemblyInfo(Record):
    artifact: ArtifactRef
    version: Literal["general-simulation-assembly-v1"] = "general-simulation-assembly-v1"
    model: ModelRef
    schedule: ArtifactRef
    physics: ArtifactRef
    parent: ArtifactRef | None
    well_count: NonNegativeInt
    connection_count: NonNegativeInt
    missing_exports: NonNegativeInt
    physics_complete: bool


class ConnectionBinding(Record):
    well: Text
    plan: ArtifactRef
    export: ArtifactRef
    count: PositiveInt


class AssemblyManifest(Record):
    info: AssemblyInfo
    source: AssemblyRequest
    connections: tuple[ConnectionBinding, ...]


class AssemblyPageRequest(Record):
    assembly: ArtifactRef
    offset: NonNegativeInt = 0
    count: PositiveInt


class AssemblyPage(Record):
    assembly: ArtifactRef
    connections: tuple[ConnectionBinding, ...]
    next_offset: NonNegativeInt | None


class CompiledFile(Record):
    name: Text
    artifact: ArtifactRef


class ValidationSummary(Record):
    parser_version: Text
    clock: Literal["UTC"] = "UTC"
    unit_system: Literal["METRIC", "FIELD"]
    global_cells: PositiveInt
    active_cells: PositiveInt
    wells: NonNegativeInt
    connections: NonNegativeInt
    reports: PositiveInt
    control_events: NonNegativeInt
    verified_array_values: PositiveInt
    verified_table_rows: PositiveInt


class ValidationMetrics(Record):
    elapsed_seconds: NonNegativeFloat
    peak_worker_memory_mib: NonNegativeFloat
    staged_disk_mib: NonNegativeFloat
    memory_limit_mib: PositiveInt
    timeout_seconds: PositiveFloat
    disk_limit_mib: PositiveInt


class PreparedSimulation(Record):
    artifact: ArtifactRef
    version: Literal["general-prepared-simulation-v1"] = "general-prepared-simulation-v1"
    assembly: ArtifactRef
    model: ModelRef
    schedule: ArtifactRef
    physics: ArtifactRef
    validation: ValidationSummary
    metrics: ValidationMetrics
    files: tuple[CompiledFile, ...]
    simulation_executed: Literal[False] = False
