"""Publish immutable schedules and resolve independent well control histories."""

from collections.abc import Iterable

import numpy as np

from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import NumericArray, fail, operation, value
from resinsight_mcp.models.general.wells import GeneralWellModels, WellPlan

from .differences import compare
from .records import (
    Control,
    DiffRequest,
    EventPage,
    HistoryRequest,
    PageRequest,
    ScheduleCreate,
    ScheduleDifference,
    ScheduleEdit,
    ScheduleInfo,
    ScheduleManifest,
    StateRequest,
    TimedEvent,
    WellEdit,
    WellHistory,
    WellInfo,
    WellPage,
    WellState,
)
from .storage import ScheduleStorage


def apply_event(control: Control | None, event: TimedEvent) -> Control:
    if isinstance(event.action, Control):
        return event.action
    if control is None:
        fail("A well requires an explicit control before status changes.")
    return Control.model_validate({**control.model_dump(), "status": event.action.status})


def require_times(events: Iterable[TimedEvent], days: NumericArray) -> None:
    for event in events:
        index = int(np.searchsorted(days, event.elapsed_days))
        if index == len(days) or days[index] != event.elapsed_days:
            fail(f"Event day {event.elapsed_days} is absent from the report times.")


def require_controls(plan: WellPlan, events: tuple[TimedEvent, ...]) -> None:
    if not events or events[0].elapsed_days != 0 or not isinstance(events[0].action, Control):
        fail("Each well history must start with an explicit control at day zero.")
    pressure = "bar" if plan.length_unit == "m" else "psia"
    control = None
    for event in events:
        control = apply_event(control, event)
        if (control.role, control.injection_phase) != (plan.role, plan.injection_phase):
            fail("Control role and injection phase must match the immutable well plan.")
        if control.bhp.unit != pressure:
            fail(f"This geological model requires pressure in {pressure}.")


class GeneralSchedules:
    def __init__(self, plans: GeneralWellModels) -> None:
        self.storage = ScheduleStorage(plans)
        self.plans = plans
        self.arrays = plans.arrays

    def _publish(self, info: ScheduleInfo, wells: tuple[WellHistory, ...]) -> ScheduleInfo:
        manifest = ScheduleManifest(info=info, wells=tuple(sorted(wells, key=lambda w: w.name)))
        self.arrays.policy.require_memory(
            (len(wells) * 2048 + sum(len(w.chunks) for w in wells) * 1024) / 1024**2
        )
        self.arrays.publish(info.artifact, manifest)
        return info

    @operation
    def create(self, request: ScheduleCreate) -> ScheduleInfo:
        self.plans.models.manifest(request.model)
        if request.report_days.session_id != request.model.session_id:
            fail("Report times must belong to the geological model session.")
        reports, _ = self.storage.timeline(request.report_days)
        return self._publish(
            ScheduleInfo(
                model=request.model,
                start_date=request.start_date,
                reports=reports,
                artifact=self.storage.reference(request.model.session_id),
                well_count=0,
                event_count=0,
            ),
            (),
        )

    @operation
    def inspect(self, reference: ArtifactRef) -> ScheduleInfo:
        return self.storage.manifest(reference).info

    def _edits(
        self, request: ScheduleEdit, parent: ScheduleManifest, days: NumericArray
    ) -> tuple[list[WellHistory], dict[str, tuple[WellPlan, tuple[TimedEvent, ...]]]]:
        existing = {well.name: well for well in parent.wells}
        if len(set(request.remove_wells)) != len(request.remove_wells):
            fail("Each removed well name must appear once.")
        if any(name not in existing for name in request.remove_wells):
            fail("A removed well must exist in the parent schedule.")
        changed: dict[str, tuple[WellPlan, tuple[TimedEvent, ...]]] = {}
        estimate = 0
        for edit in request.wells:
            plan = value(self.plans.inspect(edit.plan))
            if plan.model != parent.info.model:
                fail("Each well plan must identify the exact geological model.")
            if plan.name in changed or plan.name in request.remove_wells:
                fail("A well can appear only once in an edit and cannot also be removed.")
            previous = existing.get(plan.name)
            estimate += (0 if previous is None else previous.event_count) + len(edit.events)
            self.arrays.policy.require_memory(estimate * 4096 / 1024**2)
            events = self._merge(edit, plan, previous)
            require_times(events, days)
            require_controls(plan, events)
            changed[plan.name] = plan, events
        retained = [
            w for w in parent.wells if w.name not in changed and w.name not in request.remove_wells
        ]
        if request.report_days is not None:
            for well in retained:
                require_times(self.storage.events(well), days)
        return retained, changed

    def _merge(
        self, edit: WellEdit, plan: WellPlan, previous: WellHistory | None
    ) -> tuple[TimedEvent, ...]:
        if previous is not None:
            old_plan = value(self.plans.inspect(previous.plan))
            if (old_plan.role, old_plan.injection_phase) != (plan.role, plan.injection_phase):
                fail("A schedule child cannot change a well role or injection phase.")
        merged = (
            {}
            if previous is None or edit.replace_history
            else {event.elapsed_days: event for event in self.storage.events(previous)}
        )
        merged.update((event.elapsed_days, event) for event in edit.events)
        return tuple(merged[day] for day in sorted(merged))

    @operation
    def edit(self, request: ScheduleEdit) -> ScheduleInfo:
        records = (
            len(request.wells)
            + len(request.remove_wells)
            + sum(len(w.events) for w in request.wells)
        )
        if records > self.arrays.policy.request_records:
            fail("The edit exceeds the configured request record budget. Publish smaller edits.")
        if not records and request.report_days is None:
            fail("A schedule edit requires well changes or new report times.")
        parent = self.storage.manifest(request.parent)
        ref = request.report_days or parent.info.reports.artifact
        if ref.session_id != parent.info.model.session_id:
            fail("Report times must belong to the schedule session.")
        reports, days = self.storage.timeline(ref)
        retained, changed = self._edits(request, parent, days)
        for plan, events in changed.values():
            retained.append(self.storage.history(plan.name, plan.artifact, events))
        info = ScheduleInfo(
            artifact=self.storage.reference(request.parent.session_id),
            parent=request.parent,
            model=parent.info.model,
            start_date=parent.info.start_date,
            reports=reports,
            well_count=len(retained),
            event_count=sum(w.event_count for w in retained),
        )
        return self._publish(info, tuple(retained))

    @staticmethod
    def _well(manifest: ScheduleManifest, name: str) -> WellHistory:
        for well in manifest.wells:
            if well.name == name:
                return well
        fail(f"The schedule has no well named {name}.")

    @operation
    def wells(self, request: PageRequest) -> WellPage:
        manifest = self.storage.manifest(request.schedule)
        end = self.storage.page_end(request.offset, request.count, len(manifest.wells))
        return WellPage(
            schedule=request.schedule,
            wells=tuple(
                WellInfo(name=w.name, plan=w.plan, event_count=w.event_count)
                for w in manifest.wells[request.offset : end]
            ),
            next_offset=end if end < len(manifest.wells) else None,
        )

    @operation
    def history(self, request: HistoryRequest) -> EventPage:
        well = self._well(self.storage.manifest(request.schedule), request.well)
        end = self.storage.page_end(request.offset, request.count, well.event_count)
        return EventPage(
            schedule=request.schedule,
            well=request.well,
            events=tuple(self.storage.events(well, request.offset, end - request.offset)),
            next_offset=end if end < well.event_count else None,
        )

    @operation
    def state(self, request: StateRequest) -> WellState:
        manifest = self.storage.manifest(request.schedule)
        well = self._well(manifest, request.well)
        if request.report_index >= manifest.info.reports.count:
            fail("The report index exceeds the schedule timeline.")
        day = float(
            next(self.arrays.chunks(manifest.info.reports.artifact, request.report_index, 1))[0]
        )
        control = None
        last = 0.0
        for event in self.storage.events(well):
            if event.elapsed_days > day:
                break
            control = apply_event(control, event)
            last = event.elapsed_days
        if control is None:
            fail("The stored well history has no initial control.")
        return WellState(
            schedule=request.schedule,
            plan=well.plan,
            well=well.name,
            report_index=request.report_index,
            elapsed_days=day,
            last_event_days=last,
            control=control,
        )

    @operation
    def difference(self, request: DiffRequest) -> ScheduleDifference:
        return compare(self.storage, request)
