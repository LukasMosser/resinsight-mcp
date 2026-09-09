"""Native well operations use resolved addresses only while sessions hold their lock."""

from dataclasses import dataclass
from typing import Protocol

from resinsight_mcp.contracts.engineering import CoordinateFrame
from resinsight_mcp.models.imports import MaterializedModel
from resinsight_mcp.models.wells.records import (
    CompletionConnection,
    ModeledWellDefinition,
    TrajectorySample,
    Wellhead,
)
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess


@dataclass(frozen=True)
class NativeWell:
    address: str
    definition: ModeledWellDefinition
    trajectory: tuple[TrajectorySample, ...]


@dataclass(frozen=True)
class NativeCompletions:
    wellhead: Wellhead
    connections: tuple[CompletionConnection, ...]


class WellBackend(Protocol):
    def load(self, access: ApplicationAccess, materialized: MaterializedModel) -> str:
        """Load and verify fixed input geometry and properties, returning its native address."""
        ...

    def verify_case(
        self,
        access: ApplicationAccess,
        address: str,
        materialized: MaterializedModel,
        corners: tuple[float, ...],
    ) -> None: ...

    def case_geometry(
        self, access: ApplicationAccess, address: str, materialized: MaterializedModel
    ) -> tuple[float, ...]:
        """Verify the file identity and model values before returning every native corner."""
        ...

    def create(
        self, access: ApplicationAccess, case_address: str, definition: ModeledWellDefinition
    ) -> NativeWell: ...

    def update(
        self,
        access: ApplicationAccess,
        case_address: str,
        well_address: str,
        definition: ModeledWellDefinition,
    ) -> NativeWell: ...

    def inspect(
        self, access: ApplicationAccess, well_address: str, coordinates: CoordinateFrame
    ) -> NativeWell: ...

    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> NativeCompletions: ...
