"""Verify explicit regional physics, streamed tables, and immutable ownership."""

import numpy as np
import pytest
from test_authoring import specification
from test_well_plans import setup

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.general.arrays import ArrayService, value
from resinsight_mcp.models.general.physics.records import (
    ArrayRegion,
    ColumnInput,
    PhysicsCreate,
    PhysicsEdit,
    RegionAssignment,
    SchemaRequest,
    TableInput,
    TableKey,
    TablePageRequest,
    UniformRegion,
)
from resinsight_mcp.models.general.physics.service import GeneralPhysics
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.workspaces import SqliteWorkspaceStore

ROWS = {
    "PVTW": [[200, 1.01, 0.00004, 0.5, 0]],
    "ROCK": [[200, 0.00004]],
    "DENSITY": [[800, 1000, 1.2]],
    "PVDG": [[1, 1, 0.01], [100, 0.01, 0.02], [300, 0.0035, 0.03]],
    "PVTO": [
        [0, 1, 1, 2],
        [0, 300, 0.99, 2.2],
        [100, 200, 1.2, 1.2],
        [100, 400, 1.18, 1.3],
        [150, 300, 1.3, 1],
    ],
    "SWOF": [[0, 0, 1, 0], [1, 1, 0, 0]],
    "SGOF": [[0, 0, 1, 0], [1, 1, 0, 0]],
    "EQUIL": [[1500, 200, 2000, 0, 1000, 0, 1, 0, 0]],
    "RSVD": [[1000, 100], [2000, 100]],
}


def prepare(tmp_path):
    plans, model = setup(tmp_path)
    physics = GeneralPhysics(plans.models)
    initial = value(
        physics.create(
            PhysicsCreate(
                model=model,
                profile="black_oil_disgas_rsvd",
                regions=tuple(
                    RegionAssignment(keyword=key, values=UniformRegion(value=1))
                    for key in ("PVTNUM", "SATNUM", "EQLNUM")
                ),
            )
        )
    )
    return physics, initial


def table_input(physics, info, keyword, rows=None, region=1):
    definition = next(
        t
        for t in value(physics.schema(SchemaRequest(unit_system=info.unit_system))).tables
        if t.keyword == keyword
    )
    data = np.asarray(ROWS[keyword] if rows is None else rows).T
    return TableInput(
        keyword=keyword,
        region=region,
        columns=tuple(
            ColumnInput(
                name=column.name,
                array=physics.arrays.write(
                    info.model.session_id, values.astype(column.dtype), column.unit
                ).artifact,
            )
            for column, values in zip(definition.columns, data, strict=True)
        ),
    )


def test_complete_regions_are_explicit_and_children_preserve_parent(tmp_path):
    physics, initial = prepare(tmp_path)
    assert not initial.complete
    tables = tuple(table_input(physics, initial, key) for key in ROWS)
    parent = value(physics.edit(PhysicsEdit(parent=initial.artifact, tables=tables)))
    assert parent.complete and not parent.simulation_ready
    assert parent.table_count == 9 and parent.row_count == 18
    child = value(
        physics.edit(
            PhysicsEdit(
                parent=parent.artifact,
                tables=(table_input(physics, parent, "ROCK", [[200, 0.00002]]),),
            )
        )
    )
    assert child.parent == parent.artifact
    old, new = physics.manifest(parent.artifact), physics.manifest(child.artifact)
    assert {t.keyword for t, u in zip(old.tables, new.tables, strict=True) if t != u} == {"ROCK"}
    removed = value(
        physics.edit(
            PhysicsEdit(parent=child.artifact, remove_tables=(TableKey(keyword="ROCK", region=1),))
        )
    )
    assert not removed.complete and value(physics.inspect(parent.artifact)) == parent
    reopened = GeneralPhysics(
        GeneralModelService(
            ArrayService(SqliteWorkspaceStore.open(tmp_path / "workspace"), physics.policy)
        )
    )
    assert value(reopened.inspect(child.artifact)) == child
    assert reopened.manifest(child.artifact) == new


def test_arrays_and_sparse_high_region_numbers_do_not_create_hidden_defaults(tmp_path):
    physics, initial = prepare(tmp_path)
    mappings = list(physics.manifest(initial.artifact).regions)
    ref = physics.arrays.write(initial.model.session_id, np.array([1, 2] * 4, dtype=np.int64), "1")
    mappings[0] = RegionAssignment(keyword="PVTNUM", values=ArrayRegion(array=ref.artifact))
    child = value(physics.edit(PhysicsEdit(parent=initial.artifact, regions=tuple(mappings))))
    assert child.coverage[0].required_regions == 2
    assert value(physics.regions(child.artifact)).regions[0].values.array == ref.artifact
    sparse = value(
        physics.edit(
            PhysicsEdit(
                parent=child.artifact, tables=(table_input(physics, child, "PVTW", region=10**9),)
            )
        )
    )
    assert sparse.coverage[0].required_regions == 10**9
    assert sparse.coverage[0].complete_regions == 0 and not sparse.complete
    assert sparse.table_count == 1


def test_repeated_edits_and_multipart_columns_have_no_total_count_limit(tmp_path):
    physics, initial = prepare(tmp_path)
    physics.arrays.policy = physics.policy.model_copy(
        update={"request_records": 2, "response_records": 1}
    )
    physics.policy = physics.arrays.policy
    source = table_input(
        physics, initial, "PVDG", [[i + 1, 1 / (i + 1), 0.01] for i in range(1001)]
    )
    current = initial
    for region in range(1, 6):
        current = value(
            physics.edit(
                PhysicsEdit(
                    parent=current.artifact, tables=(source.model_copy(update={"region": region}),)
                )
            )
        )
    assert current.table_count == 5 and current.row_count == 5005
    first = value(physics.tables(TablePageRequest(physics=current.artifact, count=1)))
    assert first.next_offset == 1 and first.tables[0].rows == 1001
    assert len(physics.arrays.descriptor(first.tables[0].columns[0].array.artifact).chunks) > 1
    assert isinstance(
        physics.tables(TablePageRequest(physics=current.artifact, count=2)).outcome, Failure
    )
    assert isinstance(
        physics.edit(
            PhysicsEdit(
                parent=current.artifact,
                tables=tuple(source.model_copy(update={"region": r}) for r in (6, 7, 8)),
            )
        ).outcome,
        Failure,
    )


@pytest.mark.parametrize(
    ("keyword", "rows", "message"),
    [
        ("PVTW", [[200, 0, 0.00004, 0.5, 0]], "volume_factor must be positive"),
        ("DENSITY", [[800, -1, 1.2]], "water must be positive"),
        ("SWOF", [[0, 0, 1, 0], [1, 1.1, 0, 0]], "within [0, 1]"),
        ("RSVD", [[1000, 100], [1000, 100]], "increase strictly"),
        ("PVTO", [[0, 100, 1, 1], [0, 90, 1, 1], [1, 200, 1, 1]], "increase within each branch"),
        ("PVTO", [[0, 100, 1, 1], [1, 90, 1, 1]], "Bubble pressures"),
        ("PVTO", [[1, 100, 1, 1], [0, 200, 1, 1]], "must not decrease"),
        ("EQUIL", [[1500, 200, 2000, 0, 1000, 0, 0, 0, 0]], "flags 1, 0, 0"),
    ],
)
def test_invalid_physics_does_not_publish_a_child(tmp_path, keyword, rows, message):
    physics, parent = prepare(tmp_path)
    result = physics.edit(
        PhysicsEdit(parent=parent.artifact, tables=(table_input(physics, parent, keyword, rows),))
    )
    assert isinstance(result.outcome, Failure) and message in result.outcome.error.message
    assert value(physics.inspect(parent.artifact)) == parent


def test_invalid_column_units_counts_ownership_and_stream_boundary_fail(tmp_path):
    physics, parent = prepare(tmp_path)
    source = table_input(physics, parent, "PVDG")
    first = source.columns[0]
    for array in (
        physics.arrays.write(parent.model.session_id, np.array([1.0, 2.0, 3.0]), "psia"),
        physics.arrays.write(parent.model.session_id, np.array([1.0, 2.0]), "bar"),
    ):
        changed = source.model_copy(
            update={
                "columns": (first.model_copy(update={"array": array.artifact}), *source.columns[1:])
            }
        )
        assert isinstance(
            physics.edit(PhysicsEdit(parent=parent.artifact, tables=(changed,))).outcome, Failure
        )
    foreign = SessionId.new()
    value(physics.arrays.store.create_session(Session(session_id=foreign, name="Foreign")))
    other = physics.arrays.write(foreign, np.array([1.0, 2.0, 3.0]), "bar")
    changed = source.model_copy(
        update={
            "columns": (first.model_copy(update={"array": other.artifact}), *source.columns[1:])
        }
    )
    assert isinstance(
        physics.edit(PhysicsEdit(parent=parent.artifact, tables=(changed,))).outcome, Failure
    )
    rows = [[i + 1, 1, 1] for i in range(130)]
    rows[64][0] = 64
    result = physics.edit(
        PhysicsEdit(parent=parent.artifact, tables=(table_input(physics, parent, "PVDG", rows),))
    )
    assert (
        isinstance(result.outcome, Failure) and "increase strictly" in result.outcome.error.message
    )


def test_missing_duplicate_and_invalid_region_maps_fail(tmp_path):
    physics, parent = prepare(tmp_path)
    regions = physics.manifest(parent.artifact).regions
    for invalid in (regions[:2], (*regions[:2], regions[0])):
        assert isinstance(
            physics.edit(PhysicsEdit(parent=parent.artifact, regions=invalid)).outcome, Failure
        )
    for data, unit in (
        (np.array([1, 0] * 4, dtype=np.int64), "1"),
        (np.ones(7, dtype=np.int64), "1"),
        (np.ones(8), "1"),
    ):
        array = physics.arrays.write(parent.model.session_id, data, unit)
        invalid = (
            RegionAssignment(keyword="PVTNUM", values=ArrayRegion(array=array.artifact)),
            *regions[1:],
        )
        assert isinstance(
            physics.edit(PhysicsEdit(parent=parent.artifact, regions=invalid)).outcome, Failure
        )


def test_duplicate_table_edits_and_missing_removals_fail(tmp_path):
    physics, parent = prepare(tmp_path)
    source = table_input(physics, parent, "ROCK")
    key = TableKey(keyword="ROCK", region=1)
    for request in (
        PhysicsEdit(parent=parent.artifact, tables=(source, source)),
        PhysicsEdit(parent=parent.artifact, tables=(source,), remove_tables=(key,)),
        PhysicsEdit(parent=parent.artifact, remove_tables=(key,)),
    ):
        assert isinstance(physics.edit(request).outcome, Failure)


def test_field_model_requires_field_columns_without_silent_conversion(tmp_path):
    physics, metric = prepare(tmp_path)
    model = value(
        physics.models.generate(
            specification(metric.model.session_id, 2, 2, 2).model_copy(update={"length_unit": "ft"})
        )
    )
    field = value(
        physics.create(
            PhysicsCreate(
                model=model.model,
                profile=metric.profile,
                regions=physics.manifest(metric.artifact).regions,
            )
        )
    )
    assert field.unit_system == "FIELD"
    wrong = table_input(physics, metric, "PVTO")
    failure = physics.edit(PhysicsEdit(parent=field.artifact, tables=(wrong,)))
    assert isinstance(failure.outcome, Failure) and "Mscf/stb" in failure.outcome.error.message
    complete = value(
        physics.edit(
            PhysicsEdit(
                parent=field.artifact,
                tables=tuple(table_input(physics, field, key) for key in ROWS),
            )
        )
    )
    assert complete.complete and complete.unit_system == "FIELD"


def test_combined_column_memory_budget_rejects_before_table_validation(tmp_path):
    physics, parent = prepare(tmp_path)
    physics.policy = physics.policy.model_copy(
        update={"working_memory_mib": 1, "request_values": 32768}
    )
    physics.arrays.policy = physics.policy
    source = table_input(physics, parent, "PVDG", [[i + 1, 1, 1] for i in range(32768)])
    failure = physics.edit(PhysicsEdit(parent=parent.artifact, tables=(source,)))
    assert (
        isinstance(failure.outcome, Failure)
        and "Estimated working memory" in failure.outcome.error.message
    )
    assert value(physics.inspect(parent.artifact)) == parent
