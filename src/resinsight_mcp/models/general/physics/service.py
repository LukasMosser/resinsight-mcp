"""Store explicit regional inputs independently from native tools and simulators."""

from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import fail, operation
from resinsight_mcp.models.general.records import GeometryManifest, NamedArray
from resinsight_mcp.models.general.service import GeneralModelService

from .records import (
    ArrayRegion,
    PhysicsCreate,
    PhysicsEdit,
    PhysicsInfo,
    PhysicsManifest,
    PhysicsRegions,
    PhysicsSchema,
    RegionAssignment,
    RegionCoverage,
    SchemaRequest,
    TableInfo,
    TableInput,
    TablePage,
    TablePageRequest,
    UniformRegion,
)
from .schema import GROUPS, schema
from .validation import validate_values


class GeneralPhysics:
    def __init__(self, models: GeneralModelService) -> None:
        self.models = models
        self.arrays = models.arrays
        self.policy = self.arrays.policy

    @operation
    def schema(self, request: SchemaRequest) -> PhysicsSchema:
        return schema(request)

    def manifest(self, reference: ArtifactRef) -> PhysicsManifest:
        with self.arrays.store.open_artifact(reference) as stream:
            result = PhysicsManifest.model_validate_json(stream.read())
        info = result.info
        if info.artifact != reference or info.model.session_id != reference.session_id:
            fail("The physics manifest identifies another artifact or session.")
        self.models.manifest(info.model)
        self.policy.require_memory((info.table_count * 8192 + 4096) / 1024**2)
        references = [c.array.artifact for table in result.tables for c in table.columns]
        references.extend(
            r.values.array for r in result.regions if isinstance(r.values, ArrayRegion)
        )
        if info.parent is not None:
            references.append(info.parent)
        if any(ref.session_id != reference.session_id for ref in references):
            fail("Every physics artifact must belong to its model session.")
        keys = [(table.keyword, table.region) for table in result.tables]
        if keys != sorted(set(keys)) or len(keys) != info.table_count:
            fail("Stored tables must be unique and match their manifest count.")
        if sum(table.rows for table in result.tables) != info.row_count:
            fail("The stored table rows differ from their manifest count.")
        return result

    def _regions(
        self, geometry: GeometryManifest, regions: tuple[RegionAssignment, ...]
    ) -> dict[str, int]:
        if len(regions) != len(GROUPS) or {r.keyword for r in regions} != set(GROUPS):
            fail("Provide one explicit assignment for PVTNUM, SATNUM, and EQLNUM.")
        maximums = {}
        for region in regions:
            values = region.values
            if isinstance(values, UniformRegion):
                maximums[region.keyword] = values.value
                continue
            if values.array.session_id != geometry.session_id:
                fail("Every region array must belong to the model session.")
            descriptor = self.arrays.descriptor(values.array)
            if (descriptor.dtype, descriptor.unit, descriptor.count) != (
                "int64",
                "1",
                geometry.shape.cells,
            ):
                fail("Region maps require one int64 value per global cell with unit 1.")
            maximum = 0
            for part in self.arrays.chunks(values.array):
                if part.min() < 1:
                    fail("Every region number must be positive, including inactive cells.")
                maximum = max(maximum, int(part.max()))
            maximums[region.keyword] = maximum
        return maximums

    def _table(self, source: TableInput, info: PhysicsInfo) -> TableInfo:
        definition = next(
            table
            for table in schema(SchemaRequest(unit_system=info.unit_system)).tables
            if table.keyword == source.keyword
        )
        if tuple(c.name for c in source.columns) != tuple(c.name for c in definition.columns):
            fail(f"{source.keyword} requires the exact named columns in schema order.")
        columns = []
        for column, expected in zip(source.columns, definition.columns, strict=True):
            if column.array.session_id != info.model.session_id:
                fail("Every table column must belong to the model session.")
            descriptor = self.arrays.descriptor(column.array)
            if (descriptor.dtype, descriptor.unit) != (expected.dtype, expected.unit):
                fail(
                    f"{source.keyword}.{column.name} requires {expected.dtype} in {expected.unit}."
                )
            columns.append(NamedArray(name=column.name, array=descriptor.info()))
        count = columns[0].array.count
        if any(c.array.count != count for c in columns):
            fail("Every column in a table must have the same row count.")
        if count < definition.minimum_rows or (definition.single_row and count != 1):
            fail(f"{source.keyword} has an invalid row count for its table structure.")
        table = TableInfo(
            keyword=source.keyword, region=source.region, rows=count, columns=tuple(columns)
        )
        validate_values(self.arrays, table)
        return table

    def _publish(
        self, source: PhysicsCreate, tables: tuple[TableInfo, ...], parent: ArtifactRef | None
    ) -> PhysicsInfo:
        self.policy.require_memory((len(tables) * 8192 + 4096) / 1024**2)
        geometry = self.models.manifest(source.model)
        required = self._regions(geometry, source.regions)
        coverage = []
        for group, keywords in GROUPS.items():
            indexes = [{t.region for t in tables if t.keyword == keyword} for keyword in keywords]
            maximum = max(required[group], *(max(index, default=0) for index in indexes))
            complete = set.intersection(*indexes)
            coverage.append(
                RegionCoverage(
                    keyword=group, required_regions=maximum, complete_regions=len(complete)
                )
            )
        info = PhysicsInfo(
            artifact=ArtifactRef(session_id=source.model.session_id, artifact_id=ArtifactId.new()),
            parent=parent,
            model=source.model,
            profile=source.profile,
            unit_system="METRIC" if geometry.length_unit == "m" else "FIELD",
            table_count=len(tables),
            row_count=sum(table.rows for table in tables),
            coverage=tuple(coverage),
            complete=all(c.complete_regions == c.required_regions for c in coverage),
        )
        self.arrays.publish(
            info.artifact, PhysicsManifest(info=info, regions=source.regions, tables=tables)
        )
        return info

    @operation
    def create(self, request: PhysicsCreate) -> PhysicsInfo:
        return self._publish(request, (), None)

    @operation
    def edit(self, request: PhysicsEdit) -> PhysicsInfo:
        if len(request.tables) + len(request.remove_tables) > self.policy.request_records:
            fail("The physics edit exceeds the configured request record budget.")
        parent = self.manifest(request.parent)
        updates = {(table.keyword, table.region): table for table in request.tables}
        removals = {(table.keyword, table.region) for table in request.remove_tables}
        if len(updates) != len(request.tables) or len(removals) != len(request.remove_tables):
            fail("An edit must not repeat a table key.")
        if updates.keys() & removals:
            fail("An edit must not replace and remove the same table.")
        tables = {(table.keyword, table.region): table for table in parent.tables}
        if not removals <= tables.keys():
            fail("A removed table does not exist in the parent.")
        self.policy.require_memory((len(tables) + len(updates)) * 8192 / 1024**2)
        for key in removals:
            del tables[key]
        for key, source in updates.items():
            tables[key] = self._table(source, parent.info)
        return self._publish(
            PhysicsCreate(
                model=parent.info.model,
                profile=parent.info.profile,
                regions=parent.regions if request.regions is None else request.regions,
            ),
            tuple(tables[key] for key in sorted(tables)),
            request.parent,
        )

    @operation
    def inspect(self, reference: ArtifactRef) -> PhysicsInfo:
        return self.manifest(reference).info

    @operation
    def regions(self, reference: ArtifactRef) -> PhysicsRegions:
        return PhysicsRegions(physics=reference, regions=self.manifest(reference).regions)

    @operation
    def tables(self, request: TablePageRequest) -> TablePage:
        if request.count > self.policy.response_records:
            fail("The table page exceeds the configured response record budget.")
        manifest = self.manifest(request.physics)
        if request.offset > len(manifest.tables):
            fail("The table page starts beyond the stored tables.")
        end = min(request.offset + request.count, len(manifest.tables))
        return TablePage(
            physics=request.physics,
            tables=manifest.tables[request.offset : end],
            next_offset=end if end < len(manifest.tables) else None,
        )
