"""Publish and inspect durable general geological model revisions."""

from collections.abc import Iterator
from typing import TextIO

import numpy as np

from resinsight_mcp.contracts.engineering import (
    CoordinateFrame,
    DepthDirection,
    ModelRef,
    Unit,
    UnitSystem,
)
from resinsight_mcp.contracts.identifiers import ArtifactId, RevisionId
from resinsight_mcp.contracts.models import ArtifactRef, ModelInputs, ModelRevision

from .arrays import ArrayService, fail, operation, value
from .generator import generate
from .records import (
    CellField,
    CornerPointRequest,
    GeneralCapabilities,
    GeologicalModel,
    GeologicalRequest,
    GeometryManifest,
    NamedArray,
)


class GeneralModelService:
    def __init__(self, arrays: ArrayService) -> None:
        self.arrays = arrays
        self.store = arrays.store

    @operation
    def capabilities(self) -> GeneralCapabilities:
        return GeneralCapabilities(policy=self.arrays.policy)

    def manifest(self, model: ModelRef) -> GeometryManifest:
        revision = value(self.store.get_revision(model))
        ref = ArtifactRef(session_id=model.session_id, artifact_id=revision.inputs.entrypoint)
        with self.store.open_artifact(ref) as stream:
            return GeometryManifest.model_validate_json(stream.read())

    @staticmethod
    def references(request: CornerPointRequest) -> Iterator[tuple[str, ArtifactRef]]:
        yield "COORD", request.coord
        yield "ZCORN", request.zcorn
        yield "ACTNUM", request.actnum
        for field in request.fields:
            yield field.name, field.array

    def validate(self, request: CornerPointRequest) -> int:
        shape = request.shape
        names = [name for name, _ in self.references(request)]
        if len(set(names)) != len(names) or any(
            name in {"SPECGRID", "GRIDUNIT", "MAPAXES"} for name in names
        ):
            fail("Geometry and field names must be unique and cannot replace grid metadata.")
        expected = {"COORD": 6 * (shape.nx + 1) * (shape.ny + 1), "ZCORN": 8 * shape.cells}
        for name, ref in self.references(request):
            if ref.session_id != request.session_id:
                fail("Every model array must belong to the same session.")
            info = self.arrays.descriptor(ref)
            if info.count != expected.get(name, shape.cells):
                fail(
                    f"{name}: {info.count} values supplied, "
                    f"{expected.get(name, shape.cells)} required."
                )
            if name == "ACTNUM" and (info.dtype != "int64" or info.unit != "1"):
                fail("ACTNUM requires an integer array with dimensionless units.")
            if name in {"COORD", "ZCORN"} and info.unit != request.length_unit:
                fail("Coordinate array units must match the declared length unit.")
        self.arrays.policy.require_memory(shape.cells * 160 / 1024**2)
        active = self.arrays.read(request.actnum)
        if np.any((active != 0) & (active != 1)) or not active.any():
            fail("ACTNUM must contain zero or one, with at least one active cell.")
        depths = self.arrays.read(request.zcorn).reshape(2 * shape.nz, 2 * shape.ny, 2 * shape.nx)
        thickness = depths[1::2] - depths[::2]
        active_corners = (
            active.reshape(shape.nz, shape.ny, shape.nx).repeat(2, axis=1).repeat(2, axis=2)
        )
        if np.any(thickness[active_corners != 0] <= 0):
            fail("Active cell bottoms must be deeper than their corresponding tops.")
        pillars = self.arrays.read(request.coord).reshape(-1, 2, 3)
        if np.any(pillars[:, 1, 2] <= pillars[:, 0, 2]):
            fail("Corner-point pillars must increase in depth.")
        return int(np.count_nonzero(active))

    def publish(
        self, request: CornerPointRequest, source: ArtifactRef | None = None
    ) -> GeologicalModel:
        active_cells = self.validate(request)
        if request.parent is not None:
            if request.parent.session_id != request.session_id:
                fail("The parent must belong to the same session.")
            value(self.store.get_revision(request.parent))
        ref = ArtifactRef(session_id=request.session_id, artifact_id=ArtifactId.new())
        manifest = GeometryManifest(
            **request.model_dump(), source=source, active_cells=active_cells
        )
        self.arrays.publish(ref, manifest)
        artifacts = {ref.artifact_id}
        if source:
            artifacts.add(source.artifact_id)
        for _, array in self.references(request):
            descriptor = self.arrays.descriptor(array)
            artifacts.add(array.artifact_id)
            artifacts.update(c.artifact.artifact_id for c in descriptor.chunks)
        revision = ModelRevision(
            model=ModelRef(session_id=request.session_id, revision_id=RevisionId.new()),
            inputs=ModelInputs(
                artifacts=tuple(sorted(artifacts, key=str)), entrypoint=ref.artifact_id
            ),
            coordinates=CoordinateFrame(
                length_unit=Unit(request.length_unit),
                depth_direction=DepthDirection.POSITIVE_DOWN,
                datum=request.datum,
            ),
            unit_system=UnitSystem.METRIC if request.length_unit == "m" else UnitSystem.FIELD,
            parent=request.parent,
        )
        value(self.store.save_revision(revision))
        return self.describe(revision, manifest, active_cells)

    def describe(
        self, revision: ModelRevision, manifest: GeometryManifest, active_cells: int
    ) -> GeologicalModel:
        return GeologicalModel(
            model=revision.model,
            name=manifest.name,
            shape=manifest.shape,
            active_cells=active_cells,
            source=manifest.source,
            arrays=tuple(
                NamedArray(name=name, array=self.arrays.descriptor(ref).info())
                for name, ref in self.references(manifest)
            ),
        )

    @operation
    def create(self, request: CornerPointRequest) -> GeologicalModel:
        return self.publish(request)

    @operation
    def generate(self, request: GeologicalRequest) -> GeologicalModel:
        self.arrays.policy.require_memory(request.shape.cells * 320 / 1024**2)
        value(self.store.get_session(request.session_id))
        generated = generate(request)
        refs = {}
        for name, array in generated.items():
            unit = (
                request.length_unit
                if name in {"COORD", "ZCORN"}
                else "mD"
                if name.startswith("PERM")
                else "1"
            )
            refs[name] = self.arrays.write(request.session_id, array, unit).artifact
        source = ArtifactRef(session_id=request.session_id, artifact_id=ArtifactId.new())
        self.arrays.publish(source, request)
        return self.publish(
            CornerPointRequest(
                session_id=request.session_id,
                name=request.name,
                shape=request.shape,
                coord=refs["COORD"],
                zcorn=refs["ZCORN"],
                actnum=refs["ACTNUM"],
                fields=tuple(
                    CellField(name=name, array=refs[name])
                    for name in generated
                    if name not in {"COORD", "ZCORN", "ACTNUM"}
                ),
                length_unit=request.length_unit,
                datum=request.datum,
                parent=request.parent,
            ),
            source,
        )

    @operation
    def inspect(self, model: ModelRef) -> GeologicalModel:
        revision = value(self.store.get_revision(model))
        manifest = self.manifest(model)
        return self.describe(revision, manifest, manifest.active_cells)

    def export_grdecl(self, model: ModelRef, stream: TextIO) -> None:
        manifest = self.manifest(model)
        shape = manifest.shape
        stream.write(f"SPECGRID\n {shape.nx} {shape.ny} {shape.nz} 1 F /\n")
        stream.write(f"GRIDUNIT\n '{'METRES' if manifest.length_unit == 'm' else 'FEET'}' /\n")
        for name, ref in self.references(manifest):
            stream.write(f"{name}\n")
            for part in self.arrays.chunks(ref):
                for offset in range(0, len(part), 6):
                    stream.write(
                        " ".join(format(float(item), ".17g") for item in part[offset : offset + 6])
                        + "\n"
                    )
            stream.write("/\n")

    def cell_corners(
        self, model: ModelRef, indices: tuple[int, ...]
    ) -> dict[int, tuple[tuple[float, float, float], ...]]:
        manifest = self.manifest(model)
        shape = manifest.shape
        if not indices or len(indices) * 24 > self.arrays.policy.response_values:
            fail("The cell query exceeds the configured response size.")
        if any(index < 0 or index >= shape.cells for index in indices):
            fail("A requested cell falls outside the main grid.")
        self.arrays.policy.require_memory(shape.cells * 100 / 1024**2)
        coord = self.arrays.read(manifest.coord).reshape(shape.ny + 1, shape.nx + 1, 2, 3)
        zcorn = self.arrays.read(manifest.zcorn).reshape(2 * shape.nz, 2 * shape.ny, 2 * shape.nx)
        corners = {}
        for index in indices:
            k, remainder = divmod(index, shape.nx * shape.ny)
            j, i = divmod(remainder, shape.nx)
            points = []
            for dk in (0, 1):
                for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    depth = zcorn[2 * k + dk, 2 * j + dj, 2 * i + di]
                    top, bottom = coord[j + dj, i + di]
                    fraction = (depth - top[2]) / (bottom[2] - top[2])
                    point = top + fraction * (bottom - top)
                    points.append((float(point[0]), float(point[1]), float(depth)))
            corners[index] = tuple(points)
        return corners
