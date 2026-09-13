"""Typed intent for immutable schedules in explicit simulator units."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from resinsight_mcp.contracts._base import Record, Text
from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.wells import WellStatus, require_control_rate
from resinsight_mcp.models.general.arrays import ArrayInfo


class Pressure(Record):
    value: PositiveFloat
    unit: Literal["bar", "psia"]


class SurfaceRate(Record):
    value: NonNegativeFloat
    unit: Literal["sm3/day", "stb/day", "Mscf/day"]


class Control(Record):
    kind: Literal["control"] = "control"
    role: Literal["producer", "injector"]
    injection_phase: Literal["WATER", "GAS"] | None = None
    status: WellStatus
    mode: Literal["ORAT", "RATE", "BHP"]
    rate: SurfaceRate | None = None
    bhp: Pressure

    @model_validator(mode="after")
    def check_control(self) -> Self:
        if (self.role == "injector") != (self.injection_phase is not None):
            raise ValueError("Only injectors require an injection phase.")
        rate_mode = "ORAT" if self.role == "producer" else "RATE"
        if self.mode not in (rate_mode, "BHP"):
            raise ValueError(f"This well role supports {rate_mode} or BHP control.")
        rate_unit = (
            "sm3/day"
            if self.bhp.unit == "bar"
            else "Mscf/day"
            if self.injection_phase == "GAS"
            else "stb/day"
        )
        require_control_rate(
            self.status,
            self.mode,
            None if self.rate is None else (self.rate.value, self.rate.unit),
            rate_unit,
        )
        return self


class StatusChange(Record):
    kind: Literal["status"] = "status"
    status: WellStatus


type Action = Annotated[Control | StatusChange, Field(discriminator="kind")]


class TimedEvent(Record):
    elapsed_days: NonNegativeFloat
    action: Action


class ScheduleCreate(Record):
    model: ModelRef
    start_date: date
    report_days: ArtifactRef


class WellEdit(Record):
    plan: ArtifactRef
    events: tuple[TimedEvent, ...]
    replace_history: bool = False

    @model_validator(mode="after")
    def check_events(self) -> Self:
        days = [event.elapsed_days for event in self.events]
        if not days or any(b <= a for a, b in zip(days, days[1:], strict=False)):
            raise ValueError("Event times must increase without duplicates.")
        return self


class ScheduleEdit(Record):
    parent: ArtifactRef
    report_days: ArtifactRef | None = None
    wells: tuple[WellEdit, ...] = ()
    remove_wells: tuple[Text, ...] = ()


class ScheduleInfo(Record):
    model: ModelRef
    start_date: date
    artifact: ArtifactRef
    version: Literal["general-schedule-v1"] = "general-schedule-v1"
    parent: ArtifactRef | None = None
    reports: ArrayInfo
    well_count: NonNegativeInt
    event_count: NonNegativeInt


class EventChunk(Record):
    artifact: ArtifactRef
    count: PositiveInt
    first_day: NonNegativeFloat
    last_day: NonNegativeFloat


class WellHistory(Record):
    name: Text
    plan: ArtifactRef
    event_count: PositiveInt
    chunks: tuple[EventChunk, ...]


class EventBlock(Record):
    events: tuple[TimedEvent, ...]


class ScheduleManifest(Record):
    info: ScheduleInfo
    wells: tuple[WellHistory, ...]


class PageRequest(Record):
    schedule: ArtifactRef
    offset: NonNegativeInt = 0
    count: PositiveInt


class HistoryRequest(PageRequest):
    well: Text


class WellInfo(Record):
    name: Text
    plan: ArtifactRef
    event_count: PositiveInt


class WellPage(Record):
    schedule: ArtifactRef
    wells: tuple[WellInfo, ...]
    next_offset: NonNegativeInt | None


class EventPage(Record):
    schedule: ArtifactRef
    well: Text
    events: tuple[TimedEvent, ...]
    next_offset: NonNegativeInt | None


class StateRequest(Record):
    schedule: ArtifactRef
    well: Text
    report_index: NonNegativeInt


class WellState(Record):
    schedule: ArtifactRef
    plan: ArtifactRef
    well: Text
    report_index: NonNegativeInt
    elapsed_days: NonNegativeFloat
    last_event_days: NonNegativeFloat
    control: Control


class DiffRequest(Record):
    before: ArtifactRef
    after: ArtifactRef
    offset: NonNegativeInt = 0
    count: PositiveInt


class WellDifference(Record):
    name: Text
    before_plan: ArtifactRef | None
    after_plan: ArtifactRef | None
    added_events: NonNegativeInt
    removed_events: NonNegativeInt
    changed_events: NonNegativeInt


class ScheduleDifference(Record):
    before: ArtifactRef
    after: ArtifactRef
    report_times_changed: bool
    start_date_changed: bool
    wells: tuple[WellDifference, ...]
    next_offset: NonNegativeInt | None
