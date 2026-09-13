# General schedule acceptance

This record covers schedule authoring under [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57).
It follows the [general well acceptance](../general-wells/README.md).
The implementation commit is `d7c644acef15c06b2a1f903c9c3980993690e68f`.
The [shared command log](shared-check.log) records 820 passing tests, Ruff, ty, and the strict documentation build.

A separate installed MCP package completed 274 public tool calls, including four expected rejection checks.
The client created all model, array, well-plan, and schedule inputs through public tools.
It did not seed a database, load ResInsight, or run a simulator.
This evidence establishes authored schedule behavior, without claiming new native or simulation acceptance.

## Observed behavior

The client generated the issue's 100 by 200 by 50 model with one million active cells.
Its three permeability bands are 1,000 mD, 10 mD, and 500 mD.
Cells measure 60 by 50 by 10 meters, and the top depth is 2,000 meters.
Porosity is 0.20, 0.15, and 0.25 in the three bands.
The coordinate frame is local positive-down depth.

The model has 36 authored well plans, including the issue's two corner producers and central water injector.
The producer columns use zero-based `(0, 0)` and `(99, 199)`.
The injector column uses `(50, 100)`, with each target path through cell centers.
The 33 additional plans exercise well-count generality and are not claimed as a physical development design.

The initial schedule contains 4,001 reports spanning 4,000 elapsed days from September 13, 2026.
It contains 644 authored events, including one independent 600-event history.
A child inserts a half-day report and changes only `PROD_A` at day three.
That child contains 4,002 reports, with earlier event times preserved.
The parent snapshot remains readable with its original values.

| Well | Day 0 | Day 1 | Day 2 | Day 3 and later |
| --- | --- | --- | --- | --- |
| `PROD_A` | OPEN, ORAT 100 | SHUT, ORAT 100 retained | OPEN, ORAT 100 | OPEN, ORAT 200 |
| `PROD_B` | OPEN, ORAT 100 | SHUT, ORAT 100 retained | OPEN, ORAT 100 | OPEN, ORAT 200 |
| `INJ_C` | OPEN, RATE 100 | SHUT, RATE 100 retained | OPEN, RATE 100 | OPEN, RATE 200 |

Rates are authored surface-volume targets in sm3/day.
Every control has an explicit bottom-hole pressure constraint of 200 bar.
These are synthetic authoring inputs, not simulated production or injection values.
The child changes `PROD_A` to ORAT 300 at day three and preserves the other wells.
At its inserted half-day report, `PROD_A` still carries its initial OPEN control.
At day one, it remains SHUT.

A paged difference identifies only the changed `PROD_A` event and the changed report timeline.
The client retrieves every event from the 600-event history through pages of at most 16 records.
After exiting MCP, a new MCP process resolves the same metadata, states, histories, and well names.
All 18 saved target-well state results match their post-restart counterparts exactly.
These comparisons concern deterministic authored records rather than floating-point simulator output.

## Rejected operations

Four recorded operations fail as expected:

- Removing a report time that still owns an event.
- Requesting 17 history records when the response budget is 16.
- Reading a schedule from another selected workspace.
- Editing a schedule from another selected workspace.

Focused tests also cover invalid initial controls, conflicting event times, wrong units, wrong roles, and invalid zero-rate reopening.
FIELD tests cover pressure in psia, liquid rates in stb/day, and gas rates in Mscf/day.
The request-budget test proves that separate valid edits can exceed one request's record count collectively.

## Measurements

The [metrics record](metrics.json) contains operation counts, client durations, response size, sampled memory, and workspace storage.
Peak sampled MCP resident memory was 361.2 MiB, including million-cell model generation.
The final workspace files occupy about 101.6 MiB.
The largest structured domain-tool response contains 3,749 characters, excluding tool discovery.

The acceptance configuration sets `request_records` to 64 and `response_records` to 16.
The default 512 MiB authoring working-memory estimate remains unchanged.
These are explicit operator budgets rather than total well, report, or event ceilings.
Memory sampling runs every 50 milliseconds and can miss short peaks.
Recorded client durations include the memory sampler's final shutdown wait.
They are observed run measurements rather than isolated latency benchmarks.

## Reproduction and versions

Install this delivery into a separate environment using the locked package versions.
Run the driver from that environment's Python executable.
The driver requires a new output directory and clears inherited `PYTHONPATH` for its MCP subprocess.
It needs neither a native application nor an OPM installation for schedule authoring.

```console
UV_PROJECT_ENVIRONMENT=/absolute/environment uv sync --locked --no-dev --no-editable
/absolute/environment/bin/python docs/development/evidence/general-schedules/acceptance.py /absolute/new-output --source-commit d7c644acef15c06b2a1f903c9c3980993690e68f
```

The [original summary](summary.json) identifies Python, platform, package versions, model, parent, child, and saved state responses.
The [installation log](installation.log) records the separate installation.
The [implementation commit log](implementation-commit.log) records the normal pre-commit hook passing the shared command.
The [rendered documentation](documentation.png) and [evidence page](evidence-page.png) were inspected in the browser.
The [documentation build log](documentation-build.log) records the strict evidence-page build.
The optional release-link lookup returned 404, while the local documentation rendered correctly.

## Archived records

`protocol-records.tar.gz` preserves 279 original files under `run/`.
These include all 274 `call-*-<tool>.json` records, discovered tools, configuration, summary, MCP stderr, and the driver log.
Every archived JSON document was parsed, and the archive membership was checked after packaging.
Complete workspace databases and model arrays remain at the original paths in the records.
The driver reproduces their inputs through public MCP calls.

```console
mkdir extracted-evidence
tar -xzf protocol-records.tar.gz -C extracted-evidence
```

## Review and remaining work

The schedule module owns snapshots, report references, event blocks, and control resolution.
The existing FIELD workflow and general controls share rate-validation rules.
No second OPM deck writer was introduced.
The managed launcher binds every operation to the selected workspace.

Well history queries read only overlapping event blocks.
State queries stream preceding events, and differences stream histories with bounded output pages.
Edits still materialize affected histories, and manifests still contain all well references.
Those allocations use configured working-memory estimates and do not establish guaranteed process-memory bounds.
Schedule operations remain synchronous under the managed workspace selection lock.

Simulator compilation must still connect a schedule snapshot to compatible native completion exports and explicit fluid and initialization inputs.
General Flow execution, scalable results, native schedule-result display, and asynchronous work remain under issue #57.
