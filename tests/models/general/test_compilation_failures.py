"""Verify preparation lineage, regional tables, and isolated worker failures."""

import numpy as np
import psutil
import pytest
from test_compilation import fixture
from test_physics import table_input

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import value
from resinsight_mcp.models.general.compilation import runner
from resinsight_mcp.models.general.physics.records import (
    ColumnInput,
    PhysicsEdit,
    RegionAssignment,
    TableInput,
    UniformRegion,
)
from resinsight_mcp.models.general.records import NamedArray
from resinsight_mcp.models.general.schedules.records import ScheduleEdit, WellEdit
from resinsight_mcp.models.general.wells import WellPlanRequest


def test_multiple_regions_reuse_exact_exports(tmp_path):
    service, request = fixture(tmp_path, wells=3)
    parent = value(service.define(request))
    source = service.physics.manifest(request.physics)
    tables = tuple(
        TableInput(
            keyword=table.keyword,
            region=region,
            columns=tuple(ColumnInput(name=c.name, array=c.array.artifact) for c in table.columns),
        )
        for region in (2, 3)
        for table in source.tables
    )
    changed = value(
        service.physics.edit(
            PhysicsEdit(
                parent=request.physics,
                tables=tables,
                regions=tuple(
                    RegionAssignment(keyword=key, values=UniformRegion(value=3))
                    for key in ("PVTNUM", "SATNUM", "EQLNUM")
                ),
            )
        )
    )
    child = value(
        service.define(
            request.model_copy(
                update={"parent": parent.artifact, "physics": changed.artifact, "exports": ()}
            )
        )
    )
    assert (
        service.manifest(child.artifact).connections
        == service.manifest(parent.artifact).connections
    )
    result = value(service.prepare(child.artifact))
    assert result.validation.verified_table_rows == 57
    assert result.validation.connections == 6


def test_changed_well_plan_requires_explicit_export_replacement(tmp_path):
    service, request = fixture(tmp_path, wells=1)
    parent = value(service.define(request))
    binding = service.manifest(parent.artifact).connections[0]
    plan = value(service.plans.inspect(binding.plan))
    source = WellPlanRequest.model_validate(
        plan.model_dump(include=WellPlanRequest.model_fields.keys())
    )
    changed = value(
        service.plans.define(
            source.model_copy(update={"parent": plan.artifact, "sampling_distance": 2})
        )
    )
    schedule = value(
        service.schedules.edit(
            ScheduleEdit(
                parent=request.schedule,
                wells=(
                    WellEdit(
                        plan=changed.artifact,
                        events=tuple(
                            service.storage.events(
                                service.storage.manifest(request.schedule).wells[0]
                            )
                        ),
                        replace_history=True,
                    ),
                ),
            )
        )
    )
    failure = service.define(
        request.model_copy(
            update={"parent": parent.artifact, "schedule": schedule.artifact, "exports": ()}
        )
    )
    assert (
        isinstance(failure.outcome, Failure)
        and "changed well plan" in failure.outcome.error.message
    )
    incomplete = value(
        service.define(
            request.model_copy(
                update={
                    "parent": parent.artifact,
                    "schedule": schedule.artifact,
                    "exports": (),
                    "remove_exports": (binding.well,),
                }
            )
        )
    )
    assert incomplete.missing_exports == 1


@pytest.mark.parametrize(
    ("field", "budget", "message"),
    [("parser_timeout_seconds", 0.001, "deadline"), ("parser_memory_mib", 1, "memory budget")],
)
def test_parser_resource_limits_return_typed_failures(tmp_path, field, budget, message):
    service, request = fixture(tmp_path)
    assembly = value(service.define(request))
    service.policy = service.policy.model_copy(update={field: budget})
    failure = service.prepare(assembly.artifact)
    assert isinstance(failure.outcome, Failure) and message in failure.outcome.error.message


def test_compilation_disk_budget_includes_generated_inputs(tmp_path):
    service, request = fixture(tmp_path)
    source = service.physics.manifest(request.physics).info
    service.arrays.policy = service.policy.model_copy(update={"request_values": 32768})
    table = table_input(
        service.physics,
        source,
        "PVDG",
        [[i + 1, 1 / (i + 1), 0.01234567891234567] for i in range(30001)],
    )
    fluid = value(service.physics.edit(PhysicsEdit(parent=request.physics, tables=(table,))))
    assembly = value(service.define(request.model_copy(update={"physics": fluid.artifact})))
    service.policy = service.policy.model_copy(update={"compilation_disk_mib": 1})
    failure = service.prepare(assembly.artifact)
    assert isinstance(failure.outcome, Failure) and "disk budget" in failure.outcome.error.message


def test_opm_rejects_native_connections_outside_the_grid(tmp_path):
    service, request = fixture(tmp_path, wells=1)
    export = service.connections.read(request.exports[0])
    column = service.arrays.write(
        export.model.session_id, np.array([99, 0, 0, 0, 0, 1], dtype=np.int64), "zero_based_ijk"
    )
    reference = ArtifactRef(session_id=export.model.session_id, artifact_id=ArtifactId.new())
    invalid = export.model_copy(
        update={
            "artifact": reference,
            "columns": (NamedArray(name="cells", array=column), *export.columns[1:]),
        }
    )
    service.arrays.publish(reference, invalid)
    assembly = value(service.define(request.model_copy(update={"exports": (reference,)})))
    failure = service.prepare(assembly.artifact)
    assert isinstance(failure.outcome, Failure)
    assert "OPM validation failed" in failure.outcome.error.message


def test_preparation_survives_memory_statistics_disappearing_during_exit(tmp_path, monkeypatch):
    service, request = fixture(tmp_path, wells=3)
    assembly = value(service.define(request))
    real_popen = runner.subprocess.Popen
    real_memory_info = psutil.Process.memory_info
    workers = {}

    def launch(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        poll = child.poll
        pending = {"exit": False, "used": False}

        def delayed_exit_status():
            if pending["exit"]:
                pending["exit"] = False
                return None
            return poll()

        monkeypatch.setattr(child, "poll", delayed_exit_status)
        workers[child.pid] = (child, pending)
        return child

    def disappearing_statistics(process):
        if process.pid not in workers:
            return real_memory_info(process)
        child, pending = workers[process.pid]
        child.wait(timeout=30)
        if not pending["used"]:
            pending.update(exit=True, used=True)
        raise psutil.NoSuchProcess(process.pid)

    monkeypatch.setattr(runner.subprocess, "Popen", launch)
    monkeypatch.setattr(psutil.Process, "memory_info", disappearing_statistics)
    receipt = value(service.prepare(assembly.artifact))
    assert receipt.validation.connections == 6
    assert receipt.validation.control_events == 12
