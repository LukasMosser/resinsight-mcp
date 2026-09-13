"""Compare typed histories with bounded event-block reads and result pages."""

import numpy as np

from resinsight_mcp.models.general.arrays import fail

from .records import DiffRequest, ScheduleDifference, WellDifference, WellHistory
from .storage import ScheduleStorage


def event_counts(
    storage: ScheduleStorage, before: WellHistory | None, after: WellHistory | None
) -> tuple[int, int, int]:
    left = iter(()) if before is None else storage.events(before)
    right = iter(()) if after is None else storage.events(after)
    a, b = next(left, None), next(right, None)
    added = removed = changed = 0
    while a is not None or b is not None:
        if a is None or (b is not None and b.elapsed_days < a.elapsed_days):
            added += 1
            b = next(right, None)
        elif b is None or a.elapsed_days < b.elapsed_days:
            removed += 1
            a = next(left, None)
        else:
            changed += a.action != b.action
            a, b = next(left, None), next(right, None)
    return added, removed, changed


def compare(storage: ScheduleStorage, request: DiffRequest) -> ScheduleDifference:
    before, after = storage.manifest(request.before), storage.manifest(request.after)
    if before.info.model != after.info.model:
        fail("Schedule differences require the same geological model.")
    left, right = ({w.name: w for w in manifest.wells} for manifest in (before, after))
    names = sorted(left.keys() | right.keys())
    end = storage.page_end(request.offset, request.count, len(names))
    differences = []
    for name in names[request.offset : end]:
        a, b = left.get(name), right.get(name)
        if a == b:
            continue
        added, removed, changed = event_counts(storage, a, b)
        old_plan, new_plan = None if a is None else a.plan, None if b is None else b.plan
        if added or removed or changed or old_plan != new_plan:
            differences.append(
                WellDifference(
                    name=name,
                    before_plan=old_plan,
                    after_plan=new_plan,
                    added_events=added,
                    removed_events=removed,
                    changed_events=changed,
                )
            )
    first, second = before.info.reports, after.info.reports
    same_reports = first.count == second.count
    if same_reports and first.artifact != second.artifact:
        for offset in range(0, first.count, storage.policy.response_values):
            count = min(storage.policy.response_values, first.count - offset)
            a_values = np.concatenate(tuple(storage.arrays.chunks(first.artifact, offset, count)))
            b_values = np.concatenate(tuple(storage.arrays.chunks(second.artifact, offset, count)))
            if not np.array_equal(a_values, b_values):
                same_reports = False
                break
    return ScheduleDifference(
        before=request.before,
        after=request.after,
        report_times_changed=not same_reports,
        start_date_changed=before.info.start_date != after.info.start_date,
        wells=tuple(differences),
        next_offset=end if end < len(names) else None,
    )
