# General schedule authoring

This delivery continues [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57) after general wells.
The owner authorized schedule implementation on September 13, 2026.

## Delivery contract

A schedule snapshot identifies one geological model, a start date, report times, and immutable well plans.
Report times are stored float64 arrays in days elapsed since the start date.
The first report is zero, and later times increase strictly.
Events identify elapsed days rather than report positions, so inserted reports cannot move existing events.
Every event must occur at an explicit report time.

An empty snapshot starts authoring before any native loading or simulation.
Bounded edits add wells, replace selected events, remove wells, or replace report times.
Edits publish complete immutable snapshots and retain the parent identity.
An omitted well retains its plan and event artifact unchanged.
Removing a report with a retained event fails explicitly.
A replacement history must include an initial control at day zero.

Each well starts with an explicit producer or injector control.
Producer controls support oil rate (`ORAT`) and bottom-hole pressure (`BHP`).
Injector controls support surface rate (`RATE`) and `BHP`, with WATER or GAS injection.
Bottom-hole pressure is pressure at the well reference depth.
Rate controls require an explicit pressure constraint.
Pressure controls forbid a simultaneous rate target.

METRIC models require pressure in bar and surface rates in sm3/day.
FIELD models require pressure in psia, liquid rates in stb/day, and gas rates in Mscf/day.
These units apply to explicit quantities without silent conversion.
Status-only events support shut-in and reopening while retaining the latest control values.
An OPEN rate control requires a positive rate, including when a status event reopens a well.
Role and injection phase must match the referenced well plan.

## Storage and queries

Schedule manifests reference separate event artifacts for each well.
Public inspection returns compact metadata and array references.
Well lists and event histories use bounded pages.
A state query resolves one well at one report, carrying earlier controls forward.
A semantic diff compares typed events, plans, and report times rather than artifact identities alone.
Its cursor advances over the sorted union of well names, including unchanged names.

The authoring policy defines request and response record budgets.
Repeated edits can exceed each request budget without a total well or event count ceiling.
Full internal manifests and edited well histories remain subject to the configured working-memory estimate.
Schedule operations remain synchronous under the managed workspace selection lock.

## Acceptance plan

Public MCP checks must create independent histories for the issue's three wells.
Checks must cover report insertion, control carry-forward, shut-in, reopening, immutable edits, and schedule differences.
Additional cases must exceed the earlier 32-well, 256-report, and 3,660-day restrictions.
A fresh MCP process must read the same schedules and reject references from another selected workspace.
Focused tests must cover bad units, phase changes, conflicting events, removed report times, and reopening a zero-rate control.
The shared repository command and Linux/macOS checks must pass before review.

## Remaining work

These snapshots record simulator intent without declaring a prepared simulator model.
The next delivery connects schedule snapshots and native completion exports to validated simulator inputs.
Fluid tables, initialization, general Flow execution, and scalable result queries remain under issue #57.
Groups, role switching, additional control modes, and new physics require verified adapters and explicit scope decisions.

## Public operations

| Tool | Result |
| --- | --- |
| `general_schedule_create` | Create an empty snapshot with an explicit model, start date, and report array. |
| `general_schedule_edit` | Publish a child snapshot from selected well events, removals, or a replacement report array. |
| `general_schedule_inspect` | Return the model, parent, start date, report array, well count, and event count. |
| `general_schedule_wells` | Page through well names, plan references, and event counts in sorted name order. |
| `general_schedule_history` | Page through one well's authored events in time order. |
| `general_schedule_state` | Resolve one well's effective control at one report index. |
| `general_schedule_diff` | Compare report times, well plans, and typed event values across two snapshots. |

Use `array_upload` and `array_join` to construct the report array.
Pass the array artifact as `report_days` when creating a schedule.
Use an ISO calendar date such as `2026-09-13` for `start_date`.

Each well edit contains `plan`, `events`, and optional `replace_history`.
An event contains `elapsed_days` and an `action` with kind `control` or `status`.
Control actions specify role, injection phase, status, mode, rate, and bottom-hole pressure.
Status actions specify only `OPEN` or `SHUT`.
If `replace_history` is false, an event replaces the existing event at the same elapsed day.
If `replace_history` is true, the supplied events replace that well's entire history.

The default request budget is 256 records, and the default response budget is 128 records.
Each edited well, removed well, and supplied event counts as one request record.
Set `request_records` and `response_records` in the existing authoring policy file to change these budgets.
Repeated edits grow the schedule beyond one request without changing these budgets.
No record budget defines a maximum simulation duration.

An empty page can still have a `next_offset` in a schedule difference.
Continue with that offset because the page may contain only unchanged well names.
A difference counts added, removed, and changed authored events by elapsed day.
Equivalent typed events produce no difference even when stored under different artifact identities.
A redundant explicit event still counts as authored intent and can appear in a difference.

## Ownership and implementation review

The general schedule module owns snapshot storage and control resolution.
The existing FIELD workflow and general controls share rate-validation rules.
The existing OPM schedule writer remains the owner of bounded imported-deck editing.
This delivery does not introduce a second deck writer or claim simulator-input compilation.

History queries read only event blocks that intersect the requested page.
State queries stream preceding events and retain one current control.
Differences stream event blocks and compare report arrays in bounded numeric ranges.
Edits materialize the affected well histories within the working-memory estimate.
Internal manifests contain all well references and remain subject to that estimate.
