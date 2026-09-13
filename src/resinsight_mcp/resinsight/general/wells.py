"""Create native wells on authored grids and preserve verified connection arrays."""

from typing import Protocol

import numpy as np

from resinsight_mcp.contracts.errors import ErrorCode
from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.sessions import ObjectRef
from resinsight_mcp.contracts.workspace import ArtifactKind
from resinsight_mcp.models.general.arrays import fail, operation, value
from resinsight_mcp.models.general.connections import ConnectionStorage
from resinsight_mcp.models.general.records import NamedArray
from resinsight_mcp.models.general.wells import GeneralWellModels, WellGeometry, WellPlan
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess, ProjectMutation
from resinsight_mcp.resinsight.wells.rips import (
    GeneralCompletions,
    NativeGeometry,
)

from .service import GeneralGridService
from .well_records import (
    GeneralWellBinding,
    GeneralWellConnections,
    GeneralWellLoad,
    GeneralWellReceipt,
    GeneralWellState,
)


def address(access: ApplicationAccess, ref: ObjectRef) -> str:
    for native, item in zip(access.objects, access.project.objects, strict=True):
        if item.ref == ref:
            return native.address
    fail("The native reference is stale.", ErrorCode.STALE_OBJECT)


def references(access: ApplicationAccess) -> dict[str, ObjectRef]:
    return {
        native.address: item.ref
        for native, item in zip(access.objects, access.project.objects, strict=True)
    }


def require_geometry(actual: WellGeometry, expected: WellGeometry) -> None:
    if actual.name != expected.name:
        fail("The native well has another name.", ErrorCode.STALE_OBJECT)
    for first, second in (
        (actual.targets, expected.targets),
        (actual.intervals, expected.intervals),
    ):
        if len(first) != len(second) or not np.allclose(first, second, rtol=1e-7, atol=1e-6):
            fail(
                "Native targets or perforations differ from the authored plan.",
                ErrorCode.STALE_OBJECT,
            )


class GeometryBackend(Protocol):
    def create(
        self, access: ApplicationAccess, case_address: str, definition: WellGeometry
    ) -> NativeGeometry: ...
    def inspect(
        self, access: ApplicationAccess, well_address: str, sampling_distance: float
    ) -> NativeGeometry: ...
    def completions(
        self, access: ApplicationAccess, case_address: str, well_address: str
    ) -> GeneralCompletions: ...


class GeneralNativeWells:
    def __init__(
        self, plans: GeneralWellModels, grids: GeneralGridService, backend: GeometryBackend
    ) -> None:
        self.plans = plans
        self.grids = grids
        self.arrays = plans.arrays
        self.backend = backend

    def _ref(self, session: SessionId) -> ArtifactRef:
        return ArtifactRef(session_id=session, artifact_id=ArtifactId.new())

    @operation
    def load(self, request: GeneralWellLoad) -> GeneralWellState:
        plan = value(self.plans.inspect(request.plan))
        if plan.model != request.loaded.model:
            fail("The well plan must identify the loaded geological model.")
        geometry = self.plans.geometry(plan)
        fields = {
            f.name: self.arrays.descriptor(f.array)
            for f in self.plans.models.manifest(plan.model).fields
        }
        if not all(
            name in fields and fields[name].unit == "mD" for name in ("PERMX", "PERMY", "PERMZ")
        ):
            fail("Native completions require explicit PERMX, PERMY, and PERMZ fields in mD.")
        completed: GeneralWellState | None = None

        def change(access: ApplicationAccess) -> tuple[NativeGeometry, str, str]:
            case_address = address(access, request.loaded.case)
            view_address = address(access, request.loaded.view)
            self.grids.verify_access(access, request.loaded, case_address)
            native = self.backend.create(access, case_address, geometry)
            return native, case_address, view_address

        def finish(mutation: ProjectMutation[tuple[NativeGeometry, str, str]]) -> None:
            nonlocal completed
            native, case_address, view_address = mutation.value
            require_geometry(native.definition, geometry)
            refs = references(mutation.access)
            loaded = self.grids.refresh(request.loaded, refs[case_address], refs[view_address])
            trajectory = self.arrays.write(
                plan.model.session_id,
                np.asarray(native.trajectory, dtype=np.float64).ravel(),
                plan.length_unit,
            )
            receipt = GeneralWellReceipt(
                artifact=self._ref(plan.model.session_id),
                plan=plan.artifact,
                grid_receipt=loaded.receipt,
                trajectory=trajectory,
            )
            self.arrays.publish(receipt.artifact, receipt, ArtifactKind.METADATA)
            completed = GeneralWellState(
                binding=GeneralWellBinding(
                    loaded=loaded, well=refs[native.address], receipt=receipt.artifact
                ),
                plan=plan,
                trajectory=trajectory,
            )

        self.grids.sessions.mutate_project(request.loaded.case.context, change, validate=finish)
        assert completed is not None
        return completed

    def _stored(self, binding: GeneralWellBinding) -> tuple[GeneralWellReceipt, WellPlan]:
        with self.plans.models.store.open_artifact(binding.receipt) as stream:
            receipt = GeneralWellReceipt.model_validate_json(stream.read())
        if receipt.artifact != binding.receipt or receipt.grid_receipt != binding.loaded.receipt:
            fail("The saved well receipt identifies another native grid.")
        plan = value(self.plans.inspect(receipt.plan))
        if (
            plan.model != binding.loaded.model
            or receipt.trajectory.artifact.session_id != plan.model.session_id
        ):
            fail("The saved well receipt identifies another model or session.")
        return receipt, plan

    def _verify(
        self,
        access: ApplicationAccess,
        binding: GeneralWellBinding,
        receipt: GeneralWellReceipt,
        plan: WellPlan,
    ) -> None:
        # Object access resolves only requested objects, in request order.
        case_address, well_address = (item.address for item in access.objects)
        self.grids.verify_access(access, binding.loaded, case_address)
        geometry = self.plans.geometry(plan)
        actual = self.backend.inspect(access, well_address, plan.sampling_distance)
        require_geometry(actual.definition, geometry)
        expected = self.arrays.read(receipt.trajectory.artifact)
        samples = np.asarray(actual.trajectory).ravel()
        if samples.shape != expected.shape or not np.allclose(
            samples, expected, rtol=1e-7, atol=1e-6
        ):
            fail(
                "The sampled native trajectory differs from the saved receipt.",
                ErrorCode.STALE_OBJECT,
            )

    @operation
    def restore(self, binding: GeneralWellBinding) -> GeneralWellState:
        receipt, plan = self._stored(binding)
        with self.grids.sessions.access_objects((binding.loaded.case, binding.well)) as access:
            self._verify(access, binding, receipt, plan)
        return GeneralWellState(binding=binding, plan=plan, trajectory=receipt.trajectory)

    def _validate_connections(self, plan: WellPlan, native: GeneralCompletions) -> None:
        manifest = self.plans.models.manifest(plan.model)
        shape = manifest.shape
        active = self.arrays.read(manifest.actnum)
        geometry = self.plans.geometry(plan)
        if native.wellhead.i >= shape.nx or native.wellhead.j >= shape.ny:
            fail("The native wellhead falls outside the authored grid.")
        if len({c.cell for c in native.connections}) != len(native.connections):
            fail("The native export must aggregate connections by main-grid cell.")
        for c in native.connections:
            i, j, k = c.cell.i, c.cell.j, c.cell.k
            if (
                i >= shape.nx
                or j >= shape.ny
                or k >= shape.nz
                or not active[i + shape.nx * (j + shape.ny * k)]
            ):
                fail("A native connection does not identify an authored active cell.")
            if not all(
                any(start - 1e-5 <= depth <= end + 1e-5 for start, end, _, _ in geometry.intervals)
                for depth in (c.start_md, c.end_md)
            ):
                fail("A native connection falls outside the authored perforations.")

    @operation
    def export(self, binding: GeneralWellBinding) -> GeneralWellConnections:
        receipt, plan = self._stored(binding)
        with self.grids.sessions.access_objects((binding.loaded.case, binding.well)) as access:
            self._verify(access, binding, receipt, plan)
            native = self.backend.completions(
                access, access.objects[0].address, access.objects[1].address
            )
            self.arrays.policy.require_memory(len(native.connections) * 2048 / 1024**2)
            self._validate_connections(plan, native)
            rows = native.connections
            units = plan.length_unit
            convention = "ECLIPSE_METRIC_COMPDAT" if units == "m" else "ECLIPSE_FIELD_COMPDAT"
            data = (
                (
                    "cells",
                    "int64",
                    "zero_based_ijk",
                    [(r.cell.i, r.cell.j, r.cell.k) for r in rows],
                ),
                ("factor", "float64", convention, [r.factor for r in rows]),
                ("kh", "float64", f"mD*{units}", [r.kh for r in rows]),
                ("diameter", "float64", units, [r.diameter for r in rows]),
                ("skin", "float64", "1", [r.skin for r in rows]),
                ("direction", "int64", "X=1,Y=2,Z=3", ["XYZ".index(r.direction) + 1 for r in rows]),
                ("status", "int64", "SHUT=0,OPEN=1", [int(r.status == "OPEN") for r in rows]),
                ("measured_depth", "float64", units, [(r.start_md, r.end_md) for r in rows]),
            )
            columns = tuple(
                NamedArray(
                    name=name,
                    array=self.arrays.write(
                        plan.model.session_id, np.asarray(values, dtype=dtype).ravel(), unit
                    ),
                )
                for name, dtype, unit, values in data
            )
            result = GeneralWellConnections(
                artifact=self._ref(plan.model.session_id),
                well_receipt=binding.receipt,
                plan=plan.artifact,
                model=plan.model,
                wellhead=native.wellhead,
                length_unit=units,
                count=len(rows),
                columns=columns,
            )
            self.arrays.publish(result.artifact, result, ArtifactKind.METADATA)
            return result

    @operation
    def connections(self, ref: ArtifactRef) -> GeneralWellConnections:
        return ConnectionStorage(self.plans).read(ref)
