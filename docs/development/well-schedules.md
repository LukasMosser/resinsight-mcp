# Immutable well schedules

The P09 schedule service connects issued completion exports to child FIELD input revisions.
A completion connects a well to a reservoir cell.
This service does not change native objects or submit simulator jobs.

## Public boundary

`OpmWellScheduleService(imports, completion_source).publish(request)` returns `OperationResult[ImportReceipt]`.
The imports argument is an `OpmImportService`.
The completion source implements `CompletionSource.get_export()`.
The source owns issued export identities and verifies their stored artifacts.
The schedule service rejects a resolved artifact that differs from the requested artifact.

Every export must name the exact parent revision and its coordinate frame, including depth datum.
Requested well names must already exist at report zero.
Distinct exports cannot request the same well name twice.
Each connection must identify an active cell and use OPEN status.
Its measured-depth interval, diameter, and skin must match one supplied perforation interval within the native consistency tolerances.
The exported wellhead must fit the parent grid.

Native diameter and skin comparisons use relative and absolute tolerances of `1e-6`.
Measured-depth containment allows an absolute `1e-6` feet at each perforation boundary.
Connection endpoints must still increase strictly.
Cells, names, roles, and report indices remain exact.
The child retains the actual exported values without rounding them to the requested perforation values.
These native consistency tolerances are separate from the four-epsilon untouched-input comparison below.

The service retains the parent group and preferred phase in WELSPECS.
It applies the exported wellhead and reference depth.
A missing reference depth retains the native default, which uses the first connection.
It replaces each requested well's connections from report zero.
It removes that well's later COMPDAT records, so old connections cannot return.
Unrequested wells retain their declarations, completions, controls, and report timing.

Controls overlay the parent controls at their requested report indices.
An overlay applies after existing events at that same report.
Later parent controls remain at their original reports and can supersede an earlier overlay.
The request requires increasing, distinct indices within the existing report series.
The service rejects production and injection role changes.
It also rejects injection phase changes and requested wells whose parent injection phase changes later.

## FIELD values

Connection factors use the FIELD COMPDAT convention.
The unit is centipoise times stock-tank barrels divided by days times psia.
Permeability-length uses millidarcies times feet.
Diameters and reference depths use feet.
Oil and water surface rates use stock-tank barrels per day.
Gas surface rates use thousands of standard cubic feet per day.

The writer passes these values directly as FIELD records.
OPM applies its supported unit conversions when it builds the schedule.
`WELLDIMS.MAXCONN` increases when the requested connection count exceeds the parent capacity.
The other WELLDIMS values remain unchanged.
The existing import profile bounds the resulting capacity and cell count.
This capacity change does not change reservoir geometry or physics.

## Parsing and preservation

The implementation uses the official OPM Parser, DeckItem, EclipseState, and Schedule interfaces.
The [OPM Python reference](https://opm.github.io/opm-python-documentation/master/common.html) describes these interfaces.
The pinned dependency is `opm==2025.10`.
The writer reads parsed records, rather than replacing simulator text fragments.
It flattens the validated include graph into one child entrypoint.
It splits TSTEP arrays only at their existing report boundaries.

OPM keyword string formatting rounds numeric values to nine significant digits.
That precision can change untouched fluid tables and grid properties.
The bounded writer therefore reads raw numeric values through DeckItem getters and writes 17 significant digits.
It reads those values before constructing Schedule, which can populate OPM's internal SI value cache.
Raw data-list access restores raw units before individual value access during later comparisons.

Before publication, the service reparses the candidate and compares untouched keyword values.
This comparison includes unrequested well records at their original report indices.
It compares strings, default markers, integers, record counts, and keyword order exactly.
Floating-point values use relative tolerance `4 * sys.float_info.epsilon`, with zero absolute tolerance.
For this Python build, the relative tolerance is approximately `8.88e-16`.
Report dates must remain exactly equal.

OPM decimal parsing and raw/SI conversion produced one-unit differences in the last binary place during the focused tests.
The tolerance allows those conversion differences across the comparison's two paths.
Its scale is the larger absolute value of the compared pair.
Zero values must remain zero.
The high-precision tests use values that nine-digit keyword formatting would change well beyond this tolerance.
The P08 reference test compares every fluid-table value and the unrequested injector schedule.

The current writer rejects unsupported item types, uninitialized table entries, quoted strings containing apostrophes, and multiline strings.
It accepts only WELSPECS, COMPDAT, WCONPROD, WCONINJE, TSTEP, RPTSCHED, RPTRST, and DRSDT inside SCHEDULE.
Other parent schedule constructs fail explicitly.
The existing import profile further limits accepted inputs.
The writer does not introduce alternate parser paths or broader simulator physics.

## Attribution and lineage

The child retains standalone source comments from the complete parent input graph.
These comments include the SPE1 attribution and data license notices.
The child adds its parent revision and each requested well's changed control reports.
It identifies retained generation comments as original input metadata.
`read_specification()` therefore recovers the original generation specification, which does not establish the child's current schedule.
The parsed child inputs establish that schedule.
Grid identity metadata remains unchanged because this service does not alter geometry.

Publication uses `OpmImportService.derive_model()`.
The child inherits the parent's session, coordinates, units, and revision lineage.
The parent input artifacts remain immutable.
A delegated publication failure retains its error code, mutation effect, and recovery identity.
A materialization cleanup failure after successful publication returns `STORAGE_FAILED` with `UNKNOWN` and the published child revision.
Cleanup notes remain visible when another publication error already exists.

## Delivery ownership and evidence

The schedule agent owns `models/wells/service.py`, its two service test files, and this page.
The lead also authorized an empty well-test package marker to prevent pytest module-name collisions.
Shared well records, native services, transport, and dependencies remain outside this implementation slice.
The local branch includes the reviewed P08 dependency for its generated reference test.
Its integration resolves only two shared guide conflicts and preserves the base launcher description.
The P08 dependency commit is separate from the P09 delivery commit.

On September 9, 2026, the focused command passed 34 tests.

```text
UV_CACHE_DIR=/private/tmp/resinsight-review-uv-cache uv run --locked --no-sync pytest -q tests/models/wells
34 passed in 15.87s
```

The shared command passed Ruff, formatting, ty, 477 tests, and the strict documentation build.

```text
UV_CACHE_DIR=/private/tmp/resinsight-review-uv-cache uv run --locked python scripts/check.py
477 passed in 56.08s
Documentation built in 1.01 seconds
```

The environment used Python 3.12.13, uv 0.9.18, OPM 2025.10, and Pydantic 2.13.5.
The check tools were pytest 9.1.1, Ruff 0.16.6, ty 0.0.79, pre-commit 4.6.2, and MkDocs 1.6.1.
The normal repository hook also passed during the local P08 dependency integration.
These tests use the OPM library and repository fixture processes.
They do not launch ResInsight or a simulator.
The lead owns the combined browser review and native-export acceptance.
The [combined review](evidence/p09/integrated/README.md) records merged prerequisites, test collection repairs, and independent service findings.
