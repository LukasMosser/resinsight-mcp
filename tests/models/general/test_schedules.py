"""Verify independent histories, immutable edits, units, and scalable schedule queries."""

from datetime import date

import numpy as np
import pytest
from test_well_plans import request, setup

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.wells import WellStatus
from resinsight_mcp.models.general.arrays import ArrayService, value
from resinsight_mcp.models.general.schedules.records import (
    Control,
    DiffRequest,
    HistoryRequest,
    PageRequest,
    Pressure,
    ScheduleCreate,
    ScheduleEdit,
    StateRequest,
    StatusChange,
    SurfaceRate,
    TimedEvent,
    WellEdit,
)
from resinsight_mcp.models.general.schedules.service import GeneralSchedules
from resinsight_mcp.models.general.service import GeneralModelService
from resinsight_mcp.models.general.wells import GeneralWellModels
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def control(role="producer", phase=None, rate=100.0, unit="bar", status=WellStatus.OPEN):
    return Control(
        role=role,
        injection_phase=phase,
        status=status,
        mode="BHP" if rate is None else "ORAT" if role == "producer" else "RATE",
        rate=None
        if rate is None
        else SurfaceRate(
            value=rate,
            unit="sm3/day" if unit == "bar" else "Mscf/day" if phase == "GAS" else "stb/day",
        ),
        bhp=Pressure(value=200.0, unit=unit),
    )


def event(day, action):
    return TimedEvent(elapsed_days=float(day), action=action)


def prepare(tmp_path, days=(0, 1, 2, 5, 4000)):
    plans, model = setup(tmp_path)
    schedules = GeneralSchedules(plans)
    timeline = plans.arrays.write(model.session_id, np.asarray(days, dtype=np.float64), "day")
    initial = value(
        schedules.create(
            ScheduleCreate(
                model=model,
                start_date=date(2026, 9, 13),
                report_days=timeline.artifact,
            )
        )
    )
    producer = value(plans.define(request(plans, model, name="PRODUCER")))
    injector = value(
        plans.define(
            request(plans, model, name="INJECTOR").model_copy(
                update={"role": "injector", "injection_phase": "WATER"},
            )
        )
    )
    return schedules, initial, producer, injector


def populated(tmp_path):
    schedules, initial, producer, injector = prepare(tmp_path)
    current = value(
        schedules.edit(
            ScheduleEdit(
                parent=initial.artifact,
                wells=(
                    WellEdit(
                        plan=producer.artifact,
                        events=(
                            event(0, control()),
                            event(1, StatusChange(status=WellStatus.SHUT)),
                            event(2, StatusChange(status=WellStatus.OPEN)),
                            event(5, control(rate=None)),
                        ),
                    ),
                    WellEdit(
                        plan=injector.artifact,
                        events=(
                            event(0, control("injector", "WATER", 150.0)),
                            event(2, control("injector", "WATER", 250.0)),
                        ),
                    ),
                ),
            )
        )
    )
    return schedules, initial, current, producer, injector


def state(schedules, snapshot, well, index):
    return value(
        schedules.state(
            StateRequest(
                schedule=snapshot.artifact,
                well=well,
                report_index=index,
            )
        )
    )


def test_independent_controls_carry_forward_and_reopen(tmp_path):
    schedules, initial, current, producer, injector = populated(tmp_path)
    assert initial.well_count == 0 and current.well_count == 2 and current.event_count == 6
    for index, expected in enumerate(("OPEN", "SHUT", "OPEN", "OPEN", "OPEN")):
        result = state(schedules, current, producer.name, index)
        assert result.control.status == expected
        assert result.control.mode == ("ORAT" if index < 3 else "BHP")
        assert state(schedules, current, injector.name, index).control.rate.value == (
            150 if index < 2 else 250
        )
    assert state(schedules, current, producer.name, 4).last_event_days == 5
    assert value(schedules.inspect(initial.artifact)) == initial


def test_child_changes_only_requested_events_and_diff_is_semantic(tmp_path):
    schedules, _, parent, producer, injector = populated(tmp_path)
    changed = value(
        schedules.edit(
            ScheduleEdit(
                parent=parent.artifact,
                wells=(WellEdit(plan=producer.artifact, events=(event(2, control(rate=300.0)),)),),
            )
        )
    )
    assert changed.parent == parent.artifact
    assert state(schedules, parent, producer.name, 2).control.rate.value == 100
    assert state(schedules, changed, producer.name, 2).control.rate.value == 300
    assert (
        state(schedules, changed, injector.name, 2).control
        == state(schedules, parent, injector.name, 2).control
    )
    diff = value(
        schedules.difference(DiffRequest(before=parent.artifact, after=changed.artifact, count=2))
    )
    assert len(diff.wells) == 1 and diff.wells[0].name == producer.name
    assert diff.wells[0].changed_events == 1 and not diff.report_times_changed
    rewritten = value(
        schedules.edit(
            ScheduleEdit(
                parent=changed.artifact,
                wells=(WellEdit(plan=producer.artifact, events=(event(2, control(rate=300.0)),)),),
            )
        )
    )
    assert (
        value(
            schedules.difference(
                DiffRequest(
                    before=changed.artifact,
                    after=rewritten.artifact,
                    count=2,
                )
            )
        ).wells
        == ()
    )


def test_inserted_reports_do_not_move_events_and_removed_event_times_fail(tmp_path):
    schedules, _, parent, producer, _ = populated(tmp_path)
    timeline = schedules.arrays.write(
        parent.model.session_id, np.array([0.0, 0.5, 1.0, 2.0, 5.0, 4000.0]), "day"
    )
    child = value(
        schedules.edit(ScheduleEdit(parent=parent.artifact, report_days=timeline.artifact))
    )
    assert state(schedules, child, producer.name, 1).control.status == "OPEN"
    assert state(schedules, child, producer.name, 2).control.status == "SHUT"
    diff = value(
        schedules.difference(DiffRequest(before=parent.artifact, after=child.artifact, count=2))
    )
    assert diff.report_times_changed and not diff.wells
    bad = schedules.arrays.write(parent.model.session_id, np.array([0.0, 2.0, 5.0, 4000.0]), "day")
    assert isinstance(
        schedules.edit(ScheduleEdit(parent=parent.artifact, report_days=bad.artifact)).outcome,
        Failure,
    )
    assert value(schedules.inspect(parent.artifact)) == parent


def test_history_replacement_and_well_removal_are_explicit(tmp_path):
    schedules, _, parent, producer, injector = populated(tmp_path)
    child = value(
        schedules.edit(
            ScheduleEdit(
                parent=parent.artifact,
                remove_wells=(injector.name,),
                wells=(
                    WellEdit(
                        plan=producer.artifact,
                        replace_history=True,
                        events=(event(0, control(rate=None)),),
                    ),
                ),
            )
        )
    )
    assert child.well_count == child.event_count == 1
    assert state(schedules, child, producer.name, 1).control.status == "OPEN"
    diff = value(
        schedules.difference(DiffRequest(before=parent.artifact, after=child.artifact, count=1))
    )
    assert diff.wells[0].name == injector.name and diff.wells[0].after_plan is None
    assert diff.next_offset == 1
    assert isinstance(
        schedules.edit(ScheduleEdit(parent=child.artifact, remove_wells=("missing",))).outcome,
        Failure,
    )


def test_many_wells_reports_and_events_survive_reopen_with_small_pages(tmp_path):
    schedules, initial, producer, _ = prepare(tmp_path, days=range(4001))
    current = initial
    for index in range(35):
        plan = value(
            schedules.plans.define(request(schedules.plans, initial.model, name=f"W{index:02d}"))
        )
        current = value(
            schedules.edit(
                ScheduleEdit(
                    parent=current.artifact,
                    wells=(WellEdit(plan=plan.artifact, events=(event(0, control()),)),),
                )
            )
        )
    for start in range(0, 600, 200):
        current = value(
            schedules.edit(
                ScheduleEdit(
                    parent=current.artifact,
                    wells=(
                        WellEdit(
                            plan=producer.artifact,
                            events=tuple(
                                event(day, control(rate=day + 1.0))
                                for day in range(start, start + 200)
                            ),
                        ),
                    ),
                )
            )
        )
    assert current.well_count == 36 and current.reports.count == 4001
    reopened = GeneralSchedules(
        GeneralWellModels(
            GeneralModelService(
                ArrayService(
                    SqliteWorkspaceStore.open(tmp_path / "workspace"),
                    schedules.arrays.policy,
                )
            )
        )
    )
    assert value(reopened.inspect(current.artifact)) == current
    assert state(reopened, current, producer.name, 4000).control.rate.value == 600
    page = value(
        reopened.history(
            HistoryRequest(schedule=current.artifact, well=producer.name, offset=254, count=4)
        )
    )
    assert [e.elapsed_days for e in page.events] == [254, 255, 256, 257]
    assert page.next_offset == 258
    assert len(value(reopened.wells(PageRequest(schedule=current.artifact, count=3))).wells) == 3
    assert isinstance(
        reopened.history(
            HistoryRequest(schedule=current.artifact, well=producer.name, count=129)
        ).outcome,
        Failure,
    )


@pytest.mark.parametrize(
    "events",
    [
        (event(1, control()),),
        (event(0, StatusChange(status=WellStatus.OPEN)),),
        (event(0, control("injector", "WATER")),),
        (event(0, control(unit="psia")),),
        (
            event(0, control(rate=0.0, status=WellStatus.SHUT)),
            event(1, StatusChange(status=WellStatus.OPEN)),
        ),
        (event(0, control()), event(3, control())),
    ],
)
def test_invalid_history_fails_without_changing_parent(tmp_path, events):
    schedules, initial, producer, _ = prepare(tmp_path)
    result = schedules.edit(
        ScheduleEdit(
            parent=initial.artifact, wells=(WellEdit(plan=producer.artifact, events=events),)
        )
    )
    assert isinstance(result.outcome, Failure)
    assert value(schedules.inspect(initial.artifact)) == initial


def test_duplicate_times_phase_units_and_control_modes_are_rejected(tmp_path):
    _, _, producer, _ = prepare(tmp_path)
    with pytest.raises(ValueError, match="without duplicates"):
        WellEdit(plan=producer.artifact, events=(event(0, control()), event(0, control())))
    for update in (
        {"mode": "RATE"},
        {"rate": None},
        {"injection_phase": "WATER"},
        {"rate": SurfaceRate(value=1.0, unit="stb/day")},
    ):
        with pytest.raises(ValueError):
            Control.model_validate({**control().model_dump(), **update})
    assert control("injector", "GAS", unit="psia").rate.unit == "Mscf/day"


def test_field_controls_and_exact_model_binding(tmp_path):
    from test_authoring import specification

    schedules, initial, _, _ = prepare(tmp_path)
    generated = value(
        schedules.plans.models.generate(
            specification(initial.model.session_id, 2, 2, 2).model_copy(
                update={"length_unit": "ft"}
            )
        )
    )
    snapshot = value(
        schedules.create(
            ScheduleCreate(
                model=generated.model,
                start_date=initial.start_date,
                report_days=initial.reports.artifact,
            )
        )
    )
    for role, phase in (("producer", None), ("injector", "GAS"), ("injector", "WATER")):
        plan = value(
            schedules.plans.define(
                request(
                    schedules.plans,
                    generated.model,
                    unit="ft",
                    name=f"{role}_{phase}",
                ).model_copy(update={"role": role, "injection_phase": phase})
            )
        )
        edit = WellEdit(plan=plan.artifact, events=(event(0, control(role, phase, unit="psia")),))
        assert isinstance(
            schedules.edit(ScheduleEdit(parent=initial.artifact, wells=(edit,))).outcome, Failure
        )
        snapshot = value(schedules.edit(ScheduleEdit(parent=snapshot.artifact, wells=(edit,))))
        effective = state(schedules, snapshot, plan.name, 4).control
        assert effective.bhp.unit == "psia"
        assert effective.rate.unit == ("Mscf/day" if phase == "GAS" else "stb/day")


def test_configured_request_budget_can_be_exceeded_through_separate_edits(tmp_path):
    schedules, initial, producer, injector = prepare(tmp_path)
    bounded = GeneralSchedules(
        GeneralWellModels(
            GeneralModelService(
                ArrayService(
                    schedules.arrays.store,
                    schedules.arrays.policy.model_copy(update={"request_records": 2}),
                )
            )
        )
    )
    edits = (
        WellEdit(plan=producer.artifact, events=(event(0, control()),)),
        WellEdit(plan=injector.artifact, events=(event(0, control("injector", "WATER")),)),
    )
    assert isinstance(
        bounded.edit(ScheduleEdit(parent=initial.artifact, wells=edits)).outcome, Failure
    )
    current = initial
    for edit in edits:
        current = value(bounded.edit(ScheduleEdit(parent=current.artifact, wells=(edit,))))
    assert current.well_count == 2 and current.event_count == 2
    assert value(bounded.inspect(initial.artifact)).well_count == 0
