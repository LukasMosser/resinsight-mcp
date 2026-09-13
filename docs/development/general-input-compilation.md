# General input compilation

This delivery continues [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57).
It combines geological arrays, native well connections, regional physics, and schedules into validated OPM input files.
A deck is the text input for an Eclipse-style simulator.
Preparation validates a deck without running a simulation.

## Review consolidation

The owner requested continued implementation and closure of superseded PRs on September 13, 2026.
PRs #59 and #60 were draft deliveries with passing checks and no outstanding review comments.
Their complete commits are ancestors of PR #62.
Both PRs closed without merging, and their branches remain available.
PR #61 had already closed on the same basis.
The compiler branch retains the complete PR #62 history.

## Implemented sequence

1. Store explicit fluid tables and regional assignments.
2. Assemble matching native exports, immutable schedules, and complete physics.
3. Stream four input files in an isolated worker.
4. Parse the files with OPM 2025.10 and construct its grid and schedule state.
5. Compare parsed inputs and effective well controls against their stored sources.
6. Publish a compact receipt after validation succeeds.

General simulator execution and bounded result queries remain the next delivery.
These receipts do not enter the legacy SPE1 execution path.
The [physics contract](general-simulator-inputs.md) defines the supported three-phase profile.
Additional physics and grid formats require explicit adapters and separate evidence.

## Public tools

Enable these tools with `--enable-general-models`.
Install the `imports` package extra for the supported OPM parser.
Authoring and receipt inspection do not import OPM into the MCP server.

| Tool | Behavior |
| --- | --- |
| `general_simulation_define` | Store an assembly with explicit sources and compilation choices. |
| `general_simulation_inspect` | Read source identities, counts, and completeness. |
| `general_simulation_exports` | Read a bounded page of native connection bindings. |
| `general_simulation_prepare` | Compile and validate inputs before publishing a receipt. |
| `general_simulation_prepared` | Recover a published receipt after a server restart. |

An assembly requires the exact same geological model for its schedule, physics, and native exports.
Each export must identify the immutable well plan used by the schedule.
Parent assemblies retain exports unless an edit explicitly removes or replaces them.
A changed or removed well plan causes failure when its old export remains.
Schedule-only edits can reuse matching exports.

An assembly can remain incomplete while bounded edits add exports.
Preparation requires complete physics and an export for every scheduled well.
Zero wells are valid.
The compiler derives dimensions from actual grids, wells, connections, regions, and tables.
It adds no total cell, well, connection, report, or table-row ceiling.

## Explicit choices and supported inputs

The request requires a well group, dissolved-gas rate limit, and restart-output choice.
The dissolved-gas rate limit uses `sm3/sm3/day` for METRIC and `Mscf/stb/day` for FIELD.
The compiler writes the authored start date and report intervals.
It uses UTC for OPM report dates, including fractional days.
Shutdown and reopening events retain the preceding explicit rate and pressure controls.

The current profile compiles `PORO`, `PERMX`, `PERMY`, and `PERMZ` alongside geometry and `ACTNUM`.
Active cells require porosity within `(0, 1]` and nonnegative permeability.
Porosity uses unit `1`, and permeability uses `mD`.
An explicit `omitted_fields` list must name every additional model field before preparation can succeed.
Missing supported fields and incorrect omission lists fail.

The compiler preserves native connection cells, factors, directions, status, diameter, skin, and permeability-length values.
Native measured-depth bounds remain in the source export because ordinary `COMPDAT` records do not contain them.
Well names cannot contain simulator pattern operators.
Names containing quotes or newlines fail because this deck writer cannot represent them safely.
These are visible format restrictions, not well-count restrictions.

The profile requests `FOPR` summaries and, when wells exist, `WBHP`, `WOPR`, `WWIR`, and `WGIR`.
Requested restart output uses `RPTRST BASIC=1`.
Custom summary vectors and other restart policies require later explicit support.

## Validation and resource policy

The worker uses supported OPM interfaces to compare parsed values against the immutable source arrays.
Checks cover dimensions, all compiled arrays, active cells, regional table boundaries, regional maps, well specifications, native connections, and effective controls.
Raw double access refreshes OPM's unit conversion cache before comparisons.
FIELD tests cover the conversion between authored units and native connection values.
Parser acceptance remains distinct from numerical convergence or engineering suitability.

| Configuration | Default | Meaning |
| --- | --- | --- |
| `parser_memory_mib` | 1024 | Maximum sampled worker resident memory. |
| `parser_timeout_seconds` | 120 | Deadline for compilation and validation. |
| `compilation_disk_mib` | 1024 | Maximum staged input and log size. |
| `working_memory_mib` | 512 | Existing array and metadata working-memory budget. |

Set local resource budgets through the launcher's `--authoring-policy` JSON file.
The controller samples worker memory and staged disk usage every 20 milliseconds.
Sampling allows brief overshoot between observations.
Limit failures terminate the owned worker and return typed failures without a prepared receipt.
OPM can impose stricter input rules and consume memory beyond streamed source buffers.

Preparation is synchronous and does not create a durable simulation job.
Normal success and failure remove temporary staging files.
The worker retains a CPU deadline if its controller exits unexpectedly.
Abrupt controller loss can leave temporary files and does not provide durable cancellation or recovery of unfinished preparation.
Published receipts remain recoverable after restart.

The receipt lists `MODEL.DATA`, `GRID.INC`, `PHYSICS.INC`, `SCHEDULE.INC`, and the validation log as workspace artifacts.
It records source identities, parser version, UTC clock, validated counts, elapsed time, sampled memory, disk usage, and configured limits.
The receipt is published last and always reports `simulation_executed: false`.
An interrupted artifact copy can leave unreferenced files without a successful receipt.

## Evidence and remaining work

Maintained tests exercise zero wells, multiple wells, METRIC and FIELD units, three regions, fractional report days, and explicit status changes.
Failure tests cover stale well exports, missing exports, unsupported field decisions, invalid native cells, and resource limits.
A production MCP test creates all inputs through public tools and checks workspace ownership and receipt recovery.
Native acceptance uses the [recorded driver](evidence/general-compilation/acceptance.py) with the reviewed ResInsight build.

Next, connect these bundles to explicit simulator execution with resource policy, durable jobs, and bounded result queries.
Record convergence, rates, field results, and native result visualization separately from input validation.
Keep issue #57 open until its broader acceptance criteria have evidence.
