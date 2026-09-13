"""Resolve compatible immutable inputs and publish validated simulator bundles."""

from pathlib import Path
from tempfile import TemporaryDirectory

from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.workspace import Artifact, ArtifactKind
from resinsight_mcp.models.deck import deck_text
from resinsight_mcp.models.general.arrays import fail, operation, value
from resinsight_mcp.models.general.connections import ConnectionStorage
from resinsight_mcp.models.general.physics.service import GeneralPhysics
from resinsight_mcp.models.general.schedules.service import GeneralSchedules

from .records import (
    AssemblyInfo,
    AssemblyManifest,
    AssemblyPage,
    AssemblyPageRequest,
    AssemblyRequest,
    CompiledFile,
    ConnectionBinding,
    PreparedSimulation,
)
from .runner import validate

INPUT_FILES = ("MODEL.DATA", "GRID.INC", "PHYSICS.INC", "SCHEDULE.INC")


class GeneralCompilation:
    def __init__(self, schedules: GeneralSchedules, physics: GeneralPhysics, root: Path) -> None:
        self.schedules, self.physics, self.root = schedules, physics, root
        self.storage = schedules.storage
        self.plans, self.models, self.arrays = self.storage.plans, physics.models, physics.arrays
        self.policy = self.arrays.policy
        self.connections = ConnectionStorage(self.plans)

    def manifest(self, reference: ArtifactRef) -> AssemblyManifest:
        with self.arrays.store.open_artifact(reference) as stream:
            manifest = AssemblyManifest.model_validate_json(stream.read())
        info, source = manifest.info, manifest.source
        refs = [
            source.schedule,
            source.physics,
            *(c.export for c in manifest.connections),
            *(c.plan for c in manifest.connections),
        ]
        if source.parent is not None:
            refs.append(source.parent)
        if (
            info.artifact != reference
            or info.model.session_id != reference.session_id
            or any(ref.session_id != reference.session_id for ref in refs)
        ):
            fail("The simulation assembly identifies another artifact or session.")
        if (source.schedule, source.physics, source.parent) != (
            info.schedule,
            info.physics,
            info.parent,
        ):
            fail("The assembly sources differ from their summary.")
        self.policy.require_memory((len(manifest.connections) + info.well_count) * 8192 / 1024**2)
        self.models.manifest(info.model)
        return manifest

    @operation
    def define(self, request: AssemblyRequest) -> AssemblyInfo:
        if (
            len(request.exports) + len(request.remove_exports) + len(request.omitted_fields)
            > self.policy.request_records
        ):
            fail("The assembly edit exceeds the configured request record budget.")
        schedule = self.storage.manifest(request.schedule)
        physics = self.physics.manifest(request.physics)
        if physics.info.model != schedule.info.model:
            fail("Physics and schedule must identify the exact same geological model.")
        deck_text(request.group)
        unit = "sm3/sm3/day" if physics.info.unit_system == "METRIC" else "Mscf/stb/day"
        if request.dissolution_limit.unit != unit:
            fail(f"The dissolved gas rate limit requires {unit}.")
        wells = {well.name: well for well in schedule.wells}
        bindings = self._bindings(request)
        for name, binding in bindings.items():
            if name not in wells or wells[name].plan != binding.plan:
                fail(
                    "A retained connection export has a removed or changed well plan. "
                    "Remove or replace it explicitly."
                )
            export = self.connections.read(binding.export)
            if export.model != schedule.info.model:
                fail("Every connection export must identify the exact geological model.")
        info = AssemblyInfo(
            artifact=ArtifactRef(
                session_id=schedule.info.model.session_id, artifact_id=ArtifactId.new()
            ),
            model=schedule.info.model,
            schedule=request.schedule,
            physics=request.physics,
            parent=request.parent,
            well_count=len(wells),
            connection_count=sum(b.count for b in bindings.values()),
            missing_exports=len(wells) - len(bindings),
            physics_complete=physics.info.complete,
        )
        self.arrays.publish(
            info.artifact,
            AssemblyManifest(
                info=info,
                source=request,
                connections=tuple(bindings[name] for name in sorted(bindings)),
            ),
        )
        return info

    def _bindings(self, request: AssemblyRequest) -> dict[str, ConnectionBinding]:
        bindings = {}
        if request.parent is not None:
            parent = self.manifest(request.parent)
            if parent.info.artifact.session_id != request.schedule.session_id:
                fail("The parent assembly must belong to the schedule session.")
            bindings = {binding.well: binding for binding in parent.connections}
        removed = set(request.remove_exports)
        if len(removed) != len(request.remove_exports) or not removed <= bindings.keys():
            fail("Removed exports must identify unique wells in the parent assembly.")
        for name in removed:
            del bindings[name]
        replaced = set()
        for reference in request.exports:
            if reference.session_id != request.schedule.session_id:
                fail("Connection exports must belong to the schedule session.")
            export = self.connections.read(reference)
            plan = value(self.plans.inspect(export.plan))
            if plan.name in replaced or plan.name in removed:
                fail("An assembly edit must not repeat or remove a replaced export.")
            replaced.add(plan.name)
            bindings[plan.name] = ConnectionBinding(
                well=plan.name, plan=export.plan, export=reference, count=export.count
            )
        return bindings

    @operation
    def inspect(self, reference: ArtifactRef) -> AssemblyInfo:
        return self.manifest(reference).info

    @operation
    def exports(self, request: AssemblyPageRequest) -> AssemblyPage:
        manifest = self.manifest(request.assembly)
        end = self.storage.page_end(request.offset, request.count, len(manifest.connections))
        return AssemblyPage(
            assembly=request.assembly,
            connections=manifest.connections[request.offset : end],
            next_offset=end if end < len(manifest.connections) else None,
        )

    @operation
    def prepare(self, reference: ArtifactRef) -> PreparedSimulation:
        assembly = self.manifest(reference)
        if assembly.info.missing_exports or not assembly.info.physics_complete:
            fail(
                "Preparation requires complete physics and native exports for every scheduled well."
            )
        with TemporaryDirectory(prefix="resinsight-general-compile-") as temporary:
            directory = Path(temporary)
            (directory / "request.json").write_text(reference.model_dump_json())
            (directory / "policy.json").write_text(self.policy.model_dump_json())
            summary, metrics = validate(self.root, directory, self.policy)
            files = []
            for name in (*INPUT_FILES, "validation.log"):
                ref = ArtifactRef(session_id=reference.session_id, artifact_id=ArtifactId.new())
                with (directory / name).open("rb") as stream:
                    value(
                        self.arrays.store.write_artifact(
                            Artifact(
                                ref=ref,
                                relative_path=f"general/{ref.artifact_id}/{name}",
                                kind=ArtifactKind.INPUT
                                if name in INPUT_FILES
                                else ArtifactKind.METADATA,
                            ),
                            stream,
                        )
                    )
                files.append(CompiledFile(name=name, artifact=ref))
            prepared = PreparedSimulation(
                artifact=ArtifactRef(session_id=reference.session_id, artifact_id=ArtifactId.new()),
                assembly=reference,
                model=assembly.info.model,
                schedule=assembly.info.schedule,
                physics=assembly.info.physics,
                validation=summary,
                metrics=metrics,
                files=tuple(files),
            )
            self.arrays.publish(prepared.artifact, prepared, ArtifactKind.METADATA)
            return prepared

    @operation
    def prepared(self, reference: ArtifactRef) -> PreparedSimulation:
        with self.arrays.store.open_artifact(reference) as stream:
            prepared = PreparedSimulation.model_validate_json(stream.read())
        refs = [
            prepared.assembly,
            prepared.schedule,
            prepared.physics,
            *(f.artifact for f in prepared.files),
        ]
        if (
            prepared.artifact != reference
            or prepared.model.session_id != reference.session_id
            or any(ref.session_id != reference.session_id for ref in refs)
        ):
            fail("The prepared input receipt belongs to another artifact or session.")
        assembly = self.manifest(prepared.assembly)
        if (prepared.model, prepared.schedule, prepared.physics) != (
            assembly.info.model,
            assembly.info.schedule,
            assembly.info.physics,
        ):
            fail("The prepared receipt differs from its source assembly.")
        return prepared
