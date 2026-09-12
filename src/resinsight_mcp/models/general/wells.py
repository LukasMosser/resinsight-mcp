"""Immutable well inputs use the geological model's coordinate frame."""

from itertools import pairwise
from math import isclose
from typing import Literal, Self

import numpy as np
from pydantic import FiniteFloat, NonNegativeFloat, NonNegativeInt, PositiveFloat, model_validator

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import CellIndex, ModelRef
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.wells import WellStatus

from .arrays import fail, operation, value
from .service import GeneralModelService

type Point = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
type Sample = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
type Interval = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


class GeneralConnection(Record):
    cell: CellIndex
    status: WellStatus
    factor: PositiveFloat
    kh: PositiveFloat
    diameter: PositiveFloat
    skin: FiniteFloat
    direction: Literal["X", "Y", "Z"]
    start_md: NonNegativeFloat
    end_md: NonNegativeFloat

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.end_md <= self.start_md:
            raise ValueError("The connection end must exceed its start.")
        return self


class GeneralWellhead(Record):
    i: NonNegativeInt
    j: NonNegativeInt
    reference_depth: FiniteFloat | None = None


class WellGeometry(Record):
    """Expanded native inputs stay inside the configured working-memory budget."""

    name: Text
    targets: tuple[Point, ...]
    intervals: tuple[Interval, ...]
    sampling_distance: PositiveFloat

    @model_validator(mode="after")
    def check_geometry(self) -> Self:
        if len(self.targets) < 2 or not self.intervals:
            raise ValueError("A well requires two targets and one perforation interval.")
        if any(first == second for first, second in pairwise(self.targets)):
            raise ValueError("Adjacent targets must differ.")
        if any(
            start < 0 or end <= start or diameter <= 0 for start, end, diameter, _ in self.intervals
        ):
            raise ValueError(
                "Perforations require increasing nonnegative depths and positive diameter."
            )
        if any(first[1] > second[0] for first, second in pairwise(self.intervals)):
            raise ValueError("Perforations must increase without overlap.")
        return self

    def require_trajectory(self, samples: tuple[Sample, ...]) -> None:
        if len(samples) < 2 or any(a[3] >= b[3] for a, b in pairwise(samples)):
            raise ValueError("Native trajectory samples require increasing measured depths.")
        end = self.intervals[-1][1]
        beyond = end > samples[-1][3] and not isclose(
            end, samples[-1][3], rel_tol=1e-6, abs_tol=1e-6
        )
        if abs(samples[0][3]) > 1e-6 or beyond:
            raise ValueError(
                f"Perforation end {end} exceeds native length {samples[-1][3]}, "
                f"or native starting measured depth {samples[0][3]} differs from zero."
            )
        for target, sample in ((self.targets[0], samples[0]), (self.targets[-1], samples[-1])):
            if not all(
                isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
                for a, b in zip(target, sample[:3], strict=True)
            ):
                raise ValueError("Native endpoints differ from the authored targets.")


class WellPlanRequest(Record):
    model: ModelRef
    name: Text
    role: Literal["producer", "injector"]
    injection_phase: Literal["WATER", "GAS"] | None = None
    targets: ArtifactRef
    intervals: ArtifactRef
    skins: ArtifactRef
    sampling_distance: PositiveFloat
    parent: ArtifactRef | None = None

    @model_validator(mode="after")
    def check_ownership(self) -> Self:
        if (self.role == "injector") != (self.injection_phase is not None):
            raise ValueError("Only injectors require an explicit injection phase.")
        if any(
            ref.session_id != self.model.session_id
            for ref in (self.targets, self.intervals, self.skins)
        ):
            raise ValueError("Well arrays must belong to the model session.")
        if self.parent is not None and self.parent.session_id != self.model.session_id:
            raise ValueError("The parent well plan must belong to the model session.")
        return self


class WellPlan(WellPlanRequest):
    artifact: ArtifactRef
    version: Literal["general-well-v1"] = "general-well-v1"
    length_unit: Literal["m", "ft"]
    datum: Text


class GeneralWellModels:
    def __init__(self, models: GeneralModelService) -> None:
        self.models = models
        self.arrays = models.arrays

    def geometry(self, request: WellPlanRequest) -> WellGeometry:
        manifest = self.models.manifest(request.model)
        descriptors = [
            self.arrays.descriptor(ref)
            for ref in (request.targets, request.intervals, request.skins)
        ]
        targets, intervals, skins = descriptors
        if any(d.dtype != "float64" for d in descriptors) or (
            targets.unit != manifest.length_unit
            or intervals.unit != manifest.length_unit
            or skins.unit != "1"
        ):
            fail("Targets and intervals require model length units. Skins require float64 unit 1.")
        if targets.count % 3 or intervals.count != skins.count * 3:
            fail("Use target triples and start/end/diameter triples with one skin each.")
        self.arrays.policy.require_memory(sum(d.count for d in descriptors) * 128 / 1024**2)
        points = self.arrays.read(request.targets).reshape(-1, 3)
        depths = self.arrays.read(request.intervals).reshape(-1, 3)
        skin = self.arrays.read(request.skins)
        geometry = WellGeometry(
            name=request.name,
            targets=tuple(tuple(row) for row in points),
            intervals=tuple(tuple(row) for row in np.column_stack((depths, skin))),
            sampling_distance=request.sampling_distance,
        )
        distance = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
        self.arrays.policy.require_memory(
            (distance / request.sampling_distance + len(points)) * 512 / 1024**2
        )
        return geometry

    @operation
    def define(self, request: WellPlanRequest) -> WellPlan:
        self.geometry(request)
        if request.parent is not None:
            parent = value(self.inspect(request.parent))
            if (parent.model, parent.name, parent.role, parent.injection_phase) != (
                request.model,
                request.name,
                request.role,
                request.injection_phase,
            ):
                fail("A parent plan must identify the same model, well name, and role.")
        manifest = self.models.manifest(request.model)
        plan = WellPlan(
            **request.model_dump(),
            artifact=ArtifactRef(session_id=request.model.session_id, artifact_id=ArtifactId.new()),
            length_unit=manifest.length_unit,
            datum=manifest.datum,
        )
        self.arrays.publish(plan.artifact, plan)
        return plan

    @operation
    def inspect(self, ref: ArtifactRef) -> WellPlan:
        with self.models.store.open_artifact(ref) as stream:
            plan = WellPlan.model_validate_json(stream.read())
        if plan.artifact != ref or plan.model.session_id != ref.session_id:
            fail("The stored well plan has another ownership identity.")
        manifest = self.models.manifest(plan.model)
        if (plan.length_unit, plan.datum) != (manifest.length_unit, manifest.datum):
            fail("The stored well coordinate frame differs from the geological model.")
        return plan
