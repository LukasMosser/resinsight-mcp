"""Verify compiled input semantics with the supported OPM parser and explicit test exports."""

from datetime import date

import numpy as np
import pytest
from test_authoring import specification
from test_physics import ROWS, prepare, table_input

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.identifiers import ArtifactId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.wells import WellStatus
from resinsight_mcp.models.general.arrays import value
from resinsight_mcp.models.general.compilation.records import AssemblyRequest, DissolutionLimit
from resinsight_mcp.models.general.compilation.service import GeneralCompilation
from resinsight_mcp.models.general.connections import GeneralWellConnections
from resinsight_mcp.models.general.physics.records import (
    PhysicsCreate,
    PhysicsEdit,
)
from resinsight_mcp.models.general.records import NamedArray
from resinsight_mcp.models.general.schedules.records import (
    Control,
    Pressure,
    ScheduleCreate,
    ScheduleEdit,
    StatusChange,
    SurfaceRate,
    TimedEvent,
    WellEdit,
)
from resinsight_mcp.models.general.schedules.service import GeneralSchedules
from resinsight_mcp.models.general.wells import GeneralWellhead, GeneralWellModels, WellPlanRequest


def fixture(tmp_path, *, wells=0, length_unit="m"):
    metric = length_unit == "m"
    rate_unit = "sm3/day" if metric else "stb/day"
    pressure_unit = "bar" if metric else "psia"
    physics, initial = prepare(tmp_path)
    if not metric:
        model = value(
            physics.models.generate(
                specification(initial.model.session_id, 2, 2, 2).model_copy(
                    update={"length_unit": length_unit}
                )
            )
        )
        initial = value(
            physics.create(
                PhysicsCreate(
                    model=model.model,
                    profile=initial.profile,
                    regions=physics.manifest(initial.artifact).regions,
                )
            )
        )
    tables = tuple(
        table_input(
            physics, initial, key, [*ROWS[key], [150, 500, 1.28, 1.1]] if key == "PVTO" else None
        )
        for key in ROWS
    )
    fluid = value(physics.edit(PhysicsEdit(parent=initial.artifact, tables=tables)))
    plans = GeneralWellModels(physics.models)
    schedules = GeneralSchedules(plans)
    arrays, model = physics.arrays, fluid.model
    reports = arrays.write(model.session_id, np.array([0.0, 0.5, 1.0, 2.0]), "day")
    schedule = value(
        schedules.create(
            ScheduleCreate(model=model, start_date=date(2026, 9, 13), report_days=reports.artifact)
        )
    )
    exports = []
    for index in range(wells):
        producer = index != 2
        plan = value(
            plans.define(
                WellPlanRequest(
                    model=model,
                    name=f"WELL_{index}",
                    role="producer" if producer else "injector",
                    injection_phase=None if producer else "WATER",
                    sampling_distance=1,
                    targets=arrays.write(
                        model.session_id,
                        np.array([500.0, 750.0, 1400.0, 500.0, 750.0, 1900.0]),
                        length_unit,
                    ).artifact,
                    intervals=arrays.write(
                        model.session_id, np.array([100.0, 300.0, 0.2]), length_unit
                    ).artifact,
                    skins=arrays.write(model.session_id, np.array([0.0]), "1").artifact,
                )
            )
        )
        control = Control(
            role=plan.role,
            injection_phase=plan.injection_phase,
            status=WellStatus.OPEN,
            mode="ORAT" if producer else "RATE",
            rate=SurfaceRate(value=100, unit=rate_unit),
            bhp=Pressure(value=200, unit=pressure_unit),
        )
        schedule = value(
            schedules.edit(
                ScheduleEdit(
                    parent=schedule.artifact,
                    wells=(
                        WellEdit(
                            plan=plan.artifact,
                            events=(
                                TimedEvent(elapsed_days=0, action=control),
                                TimedEvent(
                                    elapsed_days=0.5, action=StatusChange(status=WellStatus.SHUT)
                                ),
                                TimedEvent(
                                    elapsed_days=1, action=StatusChange(status=WellStatus.OPEN)
                                ),
                                TimedEvent(
                                    elapsed_days=2,
                                    action=control.model_copy(
                                        update={"rate": SurfaceRate(value=200, unit=rate_unit)}
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )
        )
        ref = ArtifactRef(session_id=model.session_id, artifact_id=ArtifactId.new())
        data = (
            ("cells", "int64", "zero_based_ijk", [0, 0, 0, 0, 0, 1]),
            (
                "factor",
                "float64",
                "ECLIPSE_METRIC_COMPDAT" if metric else "ECLIPSE_FIELD_COMPDAT",
                [10, 20],
            ),
            ("kh", "float64", f"mD*{length_unit}", [100, 200]),
            ("diameter", "float64", length_unit, [0.2, 0.2]),
            ("skin", "float64", "1", [0, 0]),
            ("direction", "int64", "X=1,Y=2,Z=3", [3, 3]),
            ("status", "int64", "SHUT=0,OPEN=1", [1, 1]),
            ("measured_depth", "float64", length_unit, [100, 200, 200, 300]),
        )
        export = GeneralWellConnections(
            artifact=ref,
            well_receipt=ref,
            plan=plan.artifact,
            model=model,
            wellhead=GeneralWellhead(i=0, j=0, reference_depth=1500),
            length_unit=length_unit,
            count=2,
            columns=tuple(
                NamedArray(
                    name=name,
                    array=arrays.write(model.session_id, np.array(values, dtype=dtype), unit),
                )
                for name, dtype, unit, values in data
            ),
        )
        arrays.publish(ref, export)
        exports.append(ref)
    service = GeneralCompilation(schedules, physics, tmp_path / "workspace")
    request = AssemblyRequest(
        schedule=schedule.artifact,
        physics=fluid.artifact,
        group="GENERAL",
        dissolution_limit=DissolutionLimit(
            value=0, unit="sm3/sm3/day" if metric else "Mscf/stb/day"
        ),
        write_restart=True,
        exports=tuple(exports),
        omitted_fields=(),
    )
    return service, request


@pytest.mark.parametrize(("wells", "unit"), [(0, "m"), (3, "m"), (3, "ft")])
def test_preparation_preserves_model_tables_reports_and_native_values(tmp_path, wells, unit):
    service, request = fixture(tmp_path, wells=wells, length_unit=unit)
    assembly = value(service.define(request))
    prepared = value(service.prepare(assembly.artifact))
    assert prepared.validation.global_cells == 8 and prepared.validation.active_cells == 8
    assert prepared.validation.wells == wells and prepared.validation.connections == 2 * wells
    assert prepared.validation.reports == 4 and prepared.validation.control_events == 4 * wells
    assert prepared.validation.verified_table_rows == 19
    assert not prepared.simulation_executed
    assert value(service.prepared(prepared.artifact)) == prepared


def test_incomplete_inputs_do_not_receive_prepared_receipts(tmp_path):
    service, request = fixture(tmp_path, wells=3)
    assembly = value(service.define(request.model_copy(update={"exports": ()})))
    failure = service.prepare(assembly.artifact)
    assert (
        isinstance(failure.outcome, Failure)
        and "every scheduled well" in failure.outcome.error.message
    )


def test_compiler_requires_explicit_omission_of_non_simulator_fields(tmp_path):
    service, request = fixture(tmp_path)
    assembly = value(service.define(request.model_copy(update={"omitted_fields": ("FACIES",)})))
    failure = service.prepare(assembly.artifact)
    assert (
        isinstance(failure.outcome, Failure) and "omitted_fields" in failure.outcome.error.message
    )
