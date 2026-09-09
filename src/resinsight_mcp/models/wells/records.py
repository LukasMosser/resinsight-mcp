"""Typed boundaries between modeled paths and immutable FIELD schedules."""

from itertools import pairwise
from math import isclose
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    Field,
    FiniteFloat,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    model_validator,
)

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import (
    CellIndex,
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
)
from resinsight_mcp.contracts.errors import OperationResult
from resinsight_mcp.contracts.models import ArtifactRef, ModelRevision
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef
from resinsight_mcp.contracts.wells import WellControl, WellName, WellStatus


class TrajectoryPoint(Record):
    """Local coordinates use feet and positive-down depth."""

    x_ft: FiniteFloat
    y_ft: FiniteFloat
    depth_ft: FiniteFloat


class TrajectorySample(TrajectoryPoint):
    measured_depth_ft: NonNegativeFloat


class PerforationInterval(Record):
    """A measured-depth interval connects the path to intersected cells."""

    start_md_ft: NonNegativeFloat
    end_md_ft: NonNegativeFloat
    diameter_ft: PositiveFloat
    skin: NonNegativeFloat = 0.0

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.end_md_ft <= self.start_md_ft:
            raise ValueError("The interval end must exceed its start.")
        return self


class ModeledWellDefinition(Record):
    name: WellName
    coordinates: CoordinateFrame
    targets: Annotated[tuple[TrajectoryPoint, ...], Field(min_length=2, max_length=100)]
    perforations: Annotated[tuple[PerforationInterval, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def check_geometry(self) -> Self:
        if (
            self.coordinates.length_unit != Unit.FOOT
            or self.coordinates.depth_direction != DepthDirection.POSITIVE_DOWN
        ):
            raise ValueError("Modeled wells require feet and positive-down depth.")
        if any(first == second for first, second in pairwise(self.targets)):
            raise ValueError("Adjacent targets must differ.")
        if any(
            first.end_md_ft > second.start_md_ft for first, second in pairwise(self.perforations)
        ):
            raise ValueError("Perforations must have increasing, nonoverlapping measured depths.")
        return self

    def require_trajectory(self, trajectory: tuple[TrajectorySample, ...]) -> None:
        """Reject native samples that contradict the intended FIELD trajectory."""
        if len(trajectory) < 2:
            raise ValueError("A native trajectory requires at least two samples.")
        if any(
            first.measured_depth_ft >= second.measured_depth_ft
            for first, second in pairwise(trajectory)
        ):
            raise ValueError("Sampled measured depths must increase.")
        if self.perforations[-1].end_md_ft > trajectory[-1].measured_depth_ft:
            raise ValueError("Perforations must fit the observed trajectory length.")
        for target, sample in (
            (self.targets[0], trajectory[0]),
            (self.targets[-1], trajectory[-1]),
        ):
            if not all(
                isclose(expected, actual, rel_tol=1e-6, abs_tol=1e-6)
                for expected, actual in zip(
                    (target.x_ft, target.y_ft, target.depth_ft),
                    (sample.x_ft, sample.y_ft, sample.depth_ft),
                    strict=True,
                )
            ):
                raise ValueError("Sampled endpoints must match the positive-down targets.")


class PreparedCaseRequest(Record):
    context: ApplicationContext
    model: ModelRef

    @model_validator(mode="after")
    def check_session(self) -> Self:
        if self.context.session_id != self.model.session_id:
            raise ValueError("The application and model must belong to the same session.")
        return self


class PreparedCase(Record):
    """Only the native service can issue a trusted model and case binding."""

    model: ModelRef
    case: ObjectRef
    receipt: ArtifactRef

    @model_validator(mode="after")
    def check_case(self) -> Self:
        if (
            self.case.kind != ObjectKind.CASE
            or self.case.context.session_id != self.model.session_id
            or self.receipt.session_id != self.model.session_id
        ):
            raise ValueError("The prepared binding requires a case from the model session.")
        return self


class PreparedCaseReceipt(Record):
    """An immutable receipt identifies persistent sources and the verified native geometry."""

    artifact: ArtifactRef
    revision: ModelRevision
    directory: Path
    corners: Annotated[tuple[FiniteFloat, ...], Field(min_length=24)]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if self.artifact.session_id != self.revision.model.session_id:
            raise ValueError("The prepared receipt must belong to the model session.")
        if not self.directory.is_absolute() or len(self.corners) % 24:
            raise ValueError(
                "The receipt requires an absolute source path and eight corners per cell."
            )
        return self


class PreparedCaseLookupRequest(PreparedCaseRequest):
    """Find one current case through its immutable prepared source receipt."""

    receipt: ArtifactRef

    @model_validator(mode="after")
    def check_receipt_session(self) -> Self:
        if self.receipt.session_id != self.model.session_id:
            raise ValueError("The receipt and model must belong to the same session.")
        return self


class PreparedCaseRestoreRequest(PreparedCase):
    """Verify a current case against an explicitly selected immutable receipt."""


class WellAdoptRequest(Record):
    """Verify an existing modeled path before issuing a new version-zero lifetime."""

    binding: PreparedCase
    well: ObjectRef
    definition: ModeledWellDefinition
    trajectory: Annotated[tuple[TrajectorySample, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if self.well.kind != ObjectKind.WELL or self.well.context != self.binding.case.context:
            raise ValueError(
                "The adopted well and case must share the current application context."
            )
        self.definition.require_trajectory(self.trajectory)
        return self


class WellCreateRequest(Record):
    binding: PreparedCase
    definition: ModeledWellDefinition


class WellUpdateRequest(Record):
    well: ObjectRef
    expected_version: NonNegativeInt
    definition: ModeledWellDefinition

    @model_validator(mode="after")
    def check_kind(self) -> Self:
        if self.well.kind != ObjectKind.WELL:
            raise ValueError("The reference must identify a well.")
        return self


class WellExportRequest(Record):
    well: ObjectRef
    expected_version: NonNegativeInt

    @model_validator(mode="after")
    def check_kind(self) -> Self:
        if self.well.kind != ObjectKind.WELL:
            raise ValueError("The reference must identify a well.")
        return self


class ModeledWell(Record):
    binding: PreparedCase
    well: ObjectRef
    version: NonNegativeInt
    definition: ModeledWellDefinition
    trajectory: Annotated[tuple[TrajectorySample, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def check_identity_and_depth(self) -> Self:
        if self.well.kind != ObjectKind.WELL or self.well.context != self.binding.case.context:
            raise ValueError("The well and case must share their current application context.")
        self.definition.require_trajectory(self.trajectory)
        return self


class CompletionConnection(Record):
    """One active cell connection uses the FIELD COMPDAT convention."""

    cell: CellIndex
    status: WellStatus = WellStatus.OPEN
    compdat_factor_field: PositiveFloat
    permeability_length_md_ft: PositiveFloat
    diameter_ft: PositiveFloat
    skin: NonNegativeFloat
    direction: Literal["X", "Y", "Z"]
    start_md_ft: NonNegativeFloat
    end_md_ft: NonNegativeFloat

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.end_md_ft <= self.start_md_ft:
            raise ValueError("The connection end must exceed its start.")
        return self


class Wellhead(Record):
    """Indices are zero-based; a missing reference depth keeps the native default."""

    i: NonNegativeInt
    j: NonNegativeInt
    reference_depth_ft: FiniteFloat | None = None


class CompletionExport(Record):
    """An immutable service-issued snapshot retains exact model and well provenance."""

    artifact: ArtifactRef
    modeled_well: ModeledWell
    wellhead: Wellhead
    connections: Annotated[tuple[CompletionConnection, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_connections(self) -> Self:
        if self.artifact.session_id != self.modeled_well.binding.model.session_id:
            raise ValueError("The export artifact must belong to the model session.")
        cells = tuple(connection.cell for connection in self.connections)
        if len(set(cells)) != len(cells):
            raise ValueError("Each exported cell must appear once.")
        if any(
            connection.end_md_ft > self.modeled_well.trajectory[-1].measured_depth_ft
            for connection in self.connections
        ):
            raise ValueError("Exported intervals must fit the sampled trajectory.")
        return self


class ScheduledControl(Record):
    report_index: NonNegativeInt
    control: WellControl


class ScheduledWell(Record):
    """Replace one existing well's connections and selected report controls."""

    export: ArtifactRef
    controls: Annotated[tuple[ScheduledControl, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if any(
            first.report_index >= second.report_index for first, second in pairwise(self.controls)
        ):
            raise ValueError("Control report indices must increase without duplicates.")
        return self


class WellScheduleRequest(Record):
    """Edit requested existing wells while preserving every unrequested well."""

    parent: ModelRef
    wells: Annotated[tuple[ScheduledWell, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def check_exports(self) -> Self:
        exports = tuple(well.export for well in self.wells)
        if any(export.session_id != self.parent.session_id for export in exports):
            raise ValueError("Every export must belong to the parent session.")
        if len(set(exports)) != len(exports):
            raise ValueError("Each export must appear once.")
        return self


class CompletionSource(Protocol):
    def get_export(self, reference: ArtifactRef) -> OperationResult[CompletionExport]:
        """Resolve a service-issued snapshot and verify its stored artifact."""
        ...
