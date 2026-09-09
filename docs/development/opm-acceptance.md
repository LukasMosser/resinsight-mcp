# Public OPM acceptance driver

This document describes the P13 driver for [issue 14](https://github.com/LukasMosser/resinsight-mcp/issues/14).
The lead reviewed the driver and its public protocol, numerical checks, failure handling, and cleanup boundaries.
Trial 04 completed locally with 354 public calls, 854 passing checks, and 29 independently reviewed native images.
Numerical, recovery, cancellation, and cleanup reviews passed.
The prepared runtime records await owner approval for evidence publication and final P13 delivery.
The lead must approve the source and native trial before execution.

## Public boundary

The driver starts the shipped launcher with the official MCP SDK.
MCP is the Model Context Protocol for tool access.
Every model, well, simulator, result, and project operation uses a discovered public tool.
The driver does not construct a server, access workspace storage, import domain services, or call RIPS.
RIPS is the supported ResInsight Python client.
The driver uses the shared `Camera` record and pure camera comparator only to validate returned values.
Every domain operation remains a public MCP call.

The launcher uses the explicitly selected installed interpreter with Python isolation enabled.
The version record includes installed package origins, application source, driver source, native source, arguments, Python, and macOS.
The application and matching generated RIPS client must use noneditable installations with recorded origins.
The driver rejects a used output directory or a dirty driver checkout.
Output must remain outside the repository.

The source depends on two agreed public recovery interfaces.
`model_restore_case` accepts `context`, `model`, and `receipt`, then verifies the unique native case through its stored source identity.
`view_list` accepts a `LoadedResult` and returns its associated view states.
Each state contains `loaded`, `view`, `camera`, `vertical_exaggeration`, and `scene_version`.
The lead owns these domain contracts and their MCP bindings.
Missing public operations fail discovery before model or native setup.

## Workflow

The driver creates named baseline and isolation sessions.
It generates the layered FIELD template and checks every inspected layer property and active-cell index.

OPM conversion through SI, the International System of Units, can add rounding error.
Inspection arrays use relative tolerance `1e-12` and zero absolute tolerance, following the maintained import property test.
Recorded [P09 conversion errors](evidence/p09/service/trial-04/parent-inspection.json) fit within this rule, including volume differences near `3.1e-6` cubic feet.
Each array records its maximum absolute and relative difference.
Array lengths, finite values, dimensions, active-cell identity, and FIELD units remain strict checks.
Source response comparisons and reopened result comparisons remain exact.

FIELD uses feet, pressure in pounds per square inch, and stock tank barrels.
It verifies that changing the selected session does not change explicit request targets.
Foreign model, job, result, and connection requests must fail without using another session's state.

The driver launches an owned ResInsight process and loads a persistent prepared case.
INJ and PROD targets use the returned specification and inspected cell depths.
Each vertical path crosses its specified completion cell.
Its perforation stays inside that layer, with a margin bounded by one foot or one tenth of its thickness.
The public native completion export must identify exactly that cell.
Readable tables preserve measured depth, connection factor, permeability length, and diameter.

The baseline schedule is an explicit child revision published from both completion exports and the template controls.
The driver submits, polls, and collects Flow through public tools.
It checks accepted result lineage and all five required output roles.
Repeated collection must return the same result.

The scenario explicitly clones the baseline revision.
It loads a separate prepared case and explicitly adopts the existing native INJ and PROD paths.
Definition names, coordinate metadata, field shapes, and target and perforation counts must match exactly.
Definition numeric fields use the existing conversion check with relative tolerance `1e-12` and zero absolute tolerance.
Each field records its maximum absolute and relative difference during adoption and inspection.
This check accepts the observed project rounding from `8374.999999999998` to `8375`, while remaining stricter than production tolerance `1e-6`.
Trajectories, adopted version zero, stored exports, and baseline/scenario completion comparisons retain their exact checks.
A second child schedule reduces the producer oil target by 25 percent.
The scenario has distinct model, job, result, and grid identities.

## Numerical checks and images

Every report returns complete PRESSURE, SWAT, and SGAS cell arrays through `result_cell_property`.
The checks retain exact result identity, report time, FIELD units, finite values, and active-cell count.
The driver compares all 7,200 corner coordinates with the generated Cartesian geometry.
The absolute corner tolerance is 0.001 feet, consistent with the bounded native geometry evidence.
This tolerance covers output representation and does not establish simulator accuracy.

Pressure must remain positive.
Water, gas, and combined saturation use the producer's declared tolerance of `2.384185791015625e-7`.
The driver retains full FOPR and both well WBHP curves.
It checks each curve scope, keyword, well name, unit, report series, and finite values.
WBHP values must remain positive.
Public cell and curve comparisons must equal scenario values minus baseline values for every aligned entry.
Both comparison source records must equal the saved query records.
At least one compared cell value must change.

`result_load` and every `result_rebind` run the domain service's complete source and native verification.
The driver records those public outcomes instead of repeating the verifier through hidden native calls.
It does not claim an independent numerical reference or a second simulator comparison.

The first observed result camera supplies a fixed camera for all comparison images.
Baseline and scenario images use one common legend per compared property and report.
The observation must preserve source identity, property, units, report, coordinates, legend, filters, and selected well references.
The actual camera, legend, vertical scale, and filters must match between each image pair.
Each observed camera must also match the requested camera within the view service numeric tolerance.
The shared camera check uses relative tolerance `1e-8` and absolute tolerance `1e-7`.
Native serialization can round legend endpoints.
Requested and observed endpoints use the view service relative tolerance `1e-14`, with zero absolute tolerance.
The two observed legends must still match exactly.
All other scene metadata checks keep their existing rules.
The public summary operation must return an applied plot receipt, its exact curve, and a new native image.
An applied edit with a failed image does not pass visual acceptance.

Selected well references establish object existence.
They do not establish exclusive visibility or prove that opaque grid cells expose each subsurface segment.
Separate visual review must assess every saved image before acceptance is complete.
The driver records successful automated checks without claiming that visual review has occurred.

## Recovery and cleanup

The first recovery saves, closes, and reopens the project through public tools.
Old well references must fail.
Both prepared receipts are verified, and the wells are explicitly adopted into the clone's current lifetime.
Saved completion exports and complete result values must remain exactly unchanged.
Freshly regenerated completion intervals allow only endpoint rounding with relative tolerance `1e-12` and zero absolute tolerance.
The check records maximum differences for `start_md_ft` and `end_md_ft` separately.
Trial 03 observed endpoint rounding from `8375.999999999998` to `8376.0`, while other connection fields remained exact.
Connection count, order, shape, cell identity, factors, permeability length, diameter, skin, status, and direction must match exactly.
Recorded result identifiers restore result bindings without hidden checkpoint creation.

Before MCP restart, the driver saves the project and publicly terminates its owned ResInsight process.
It verifies that the recorded process lifetime ended.
It then generates a separate 255-report model and submits a one-CPU Flow job.
The job must be running before SDK disconnection and still running after immediate reconnection.
The driver cancels that exact job publicly and requires confirmed cancellation.
Collection of the canceled job must fail.

The reconnected launcher starts a fresh owned ResInsight process and opens the saved project.
Old connection references must fail.
Prepared receipts, wells, results, arrays, comparisons, and images are verified again.
The final project is saved through `project_save`.

Normal cleanup uses only `job_cancel`, `job_poll`, `connection_get`, and `application_close`.
Job cleanup continues after individual failures and records every unresolved identity.
Unknown jobs receive public cancellation requests, but unknown status never proves termination.
Terminal job records establish that the owned jobs stopped.
Stopped containers remain because the public catalog has no container-removal operation.
Host outputs and the workspace remain for inspection.
A long job that finishes before reconnection fails this trial rather than triggering another run.

If public cleanup fails, `failure.json` preserves the outstanding native connection and known job ownership records.
The driver does not silently switch to direct process or Docker control.
The lead must verify the exact recorded identities before separately authorized emergency cleanup.
Record each emergency request, verified identity, outcome, and confirmed absence beside the failed trial.
Emergency cleanup never establishes normal acceptance.

## Execution command for review

Use an installed environment containing the reviewed application wheel and matching generated RIPS wheel.
Set `P13_SOURCE_COMMIT` to the full source commit used to build that application wheel.
Set `P13_PYTHON` to its absolute interpreter path.
The output path below must not exist.
Run the command from the reviewed driver checkout.

```sh
"$P13_PYTHON" \
  tests/acceptance/opm/run.py \
  --python "$P13_PYTHON" \
  --executable /private/tmp/resinsight-p01-build/application-build/ResInsight.app/Contents/MacOS/ResInsight \
  --docker /Applications/Docker.app/Contents/Resources/bin/docker \
  --output /private/tmp/resinsight-p13-public-trial-01 \
  --source-commit "$P13_SOURCE_COMMIT" \
  --native-source /private/tmp/resinsight-p01-build/source
```

The source review must precede this command.
Trial 04 ran under the owner's recorded native runtime authorization.
Evidence publication approval remains pending.
The driver has no bypass flag or test startup hook.

## Maintained checks

The focused tests cover wrong completion cells, changed corners, layer-derived paths, unexpected public errors, and applied edits without images.
They also reject shared camera drift, wrong curve sources, wrong units, nonfinite values, and nonpositive well pressure.
Definition checks accept recorded project rounding and reject changed numeric fields, metadata, field shapes, and list counts.
Cleanup tests cover failed polling, unknown job cancellation, continued cleanup, and all unresolved identities.
They do not launch MCP, ResInsight, Docker, or Flow.
The command help also runs without a native launch.
The normal repository command runs formatting, typing, maintained tests, and the strict documentation build.
The [lead preparation record](evidence/p13/preparation/README.md) preserves 673 passing tests, source review, the installed command help, and the exact trial command.

```sh
uv run --locked python -m pytest -q tests/acceptance/opm
uv run --locked python tests/acceptance/opm/run.py --help
uv run --locked python scripts/check.py
```
