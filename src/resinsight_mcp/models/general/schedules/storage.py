"""Store schedule manifests and independently readable event blocks."""

from collections.abc import Iterator

import numpy as np

from resinsight_mcp.contracts.identifiers import ArtifactId, SessionId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.models.general.arrays import ArrayInfo, NumericArray, fail
from resinsight_mcp.models.general.wells import GeneralWellModels

from .records import EventBlock, EventChunk, ScheduleManifest, TimedEvent, WellHistory


class ScheduleStorage:
    def __init__(self, plans: GeneralWellModels) -> None:
        self.plans = plans
        self.arrays = plans.arrays
        self.policy = self.arrays.policy

    @staticmethod
    def reference(session: SessionId) -> ArtifactRef:
        return ArtifactRef(session_id=session, artifact_id=ArtifactId.new())

    def timeline(self, reference: ArtifactRef) -> tuple[ArrayInfo, NumericArray]:
        descriptor = self.arrays.descriptor(reference)
        if descriptor.dtype != "float64" or descriptor.unit != "day":
            fail("Report times require a float64 array in day units.")
        days = self.arrays.read(reference)
        if days[0] != 0 or np.any(np.diff(days) <= 0):
            fail("Report times must start at zero and increase strictly.")
        return descriptor.info(), days

    def manifest(self, reference: ArtifactRef) -> ScheduleManifest:
        with self.arrays.store.open_artifact(reference) as stream:
            result = ScheduleManifest.model_validate_json(stream.read())
        info = result.info
        session = reference.session_id
        if info.artifact != reference or info.model.session_id != session:
            fail("The schedule manifest identifies another artifact or model session.")
        references = [info.reports.artifact]
        if info.parent is not None:
            references.append(info.parent)
        for well in result.wells:
            references.extend((well.plan, *(chunk.artifact for chunk in well.chunks)))
            if sum(chunk.count for chunk in well.chunks) != well.event_count:
                fail("The well history count differs from its stored blocks.")
        if any(ref.session_id != session for ref in references):
            fail("Every schedule artifact must belong to its model session.")
        names = [well.name for well in result.wells]
        if names != sorted(set(names)) or len(names) != info.well_count:
            fail("The schedule well names must be unique and match its count.")
        if sum(well.event_count for well in result.wells) != info.event_count:
            fail("The schedule event count differs from its well histories.")
        self.policy.require_memory((len(references) * 1024 + len(names) * 2048) / 1024**2)
        self.plans.models.manifest(info.model)
        return result

    def events(
        self, well: WellHistory, offset: int = 0, count: int | None = None
    ) -> Iterator[TimedEvent]:
        end = well.event_count if count is None else offset + count
        start = 0
        for chunk in well.chunks:
            stop = start + chunk.count
            if start < end and stop > offset:
                self.policy.require_memory(chunk.count * 2048 / 1024**2)
                with self.arrays.store.open_artifact(chunk.artifact) as stream:
                    block = EventBlock.model_validate_json(stream.read())
                times = [event.elapsed_days for event in block.events]
                if (
                    len(times) != chunk.count
                    or times[0] != chunk.first_day
                    or times[-1] != chunk.last_day
                    or any(b <= a for a, b in zip(times, times[1:], strict=False))
                ):
                    fail("Stored events differ from their block description.")
                yield from block.events[max(0, offset - start) : min(chunk.count, end - start)]
            start = stop
            if start >= end:
                break

    def history(self, name: str, plan: ArtifactRef, events: tuple[TimedEvent, ...]) -> WellHistory:
        chunks = []
        for offset in range(0, len(events), self.policy.request_records):
            part = events[offset : offset + self.policy.request_records]
            reference = self.reference(plan.session_id)
            self.arrays.publish(reference, EventBlock(events=part))
            chunks.append(
                EventChunk(
                    artifact=reference,
                    count=len(part),
                    first_day=part[0].elapsed_days,
                    last_day=part[-1].elapsed_days,
                )
            )
        return WellHistory(name=name, plan=plan, event_count=len(events), chunks=tuple(chunks))

    def page_end(self, offset: int, count: int, total: int) -> int:
        if count > self.policy.response_records:
            fail("The page exceeds the configured response record budget.")
        if offset > total:
            fail("The page offset exceeds the stored record count.")
        return min(offset + count, total)
