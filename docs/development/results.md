# Results

P12 adds accepted result queries, scenario comparisons, native loading, and fresh result bindings.
`ResultsService` uses the semantic dataset produced by P11.
It does not parse simulator files again or change numerical acceptance.
Its native backend uses the session service's verified application connection.
Its required `ResultVerifier` dependency uses P11's semantic output reader.

## Numerical queries

`cell_property(CellQuery)` returns one property in the stored active cell order.
`curve(CurveQuery)` returns one field or well curve.
Both responses carry the complete stored result, including its job and model revision.
They also carry units and report times.
A missing manifest, rejected result, wrong dataset identity, or unavailable quantity fails explicitly.

`compare_cells(baseline, scenario)` requires matching geometry, coordinate frames, dimensions, active cell order, properties, units, and report times.
Matching scenarios can retain different grid identifiers from their separate runs.
`compare_curves(baseline, scenario)` requires matching curve scope, keyword, well name, units, and report times.
Both operations require one session.
They return scenario values minus baseline values without interpolation or unit conversion.

Cell comparison also returns one legend covering both source arrays.
Apply that same legend to both native views before capturing comparison images.

## Persistent source files

Configure `bundle_root` as an absolute directory without symbolic links.
`materialize(ResultRef)` copies the five immutable output artifacts beneath `bundle_root/session_id/result_id`.
The copied files retain their case basename and native filename extensions.
The bundle includes the typed manifest.
Files must remain at these paths while a native project refers to them.

An existing bundle must have the same manifest and regular files with one link.
These checks establish source identity and path safety, not numerical correctness.
Every new or reused materialization then passes through `verify_outputs(result, directory)`.
That P11 operation verifies all five files, including geometry, units, and static result data.
Its returned dataset must equal the immutable stored dataset before the service returns a bundle.
Loading and rebinding also verify native semantic content against that dataset.

No byte comparison establishes equivalence.
A failed or conflicting bundle operation does not replace another result's files.

## Native loading and binding

`load(ResultImportRequest)` checks the stored result and job before loading their files.
It imports the summary case, loads a new grid case, and creates its view.
The grid case name includes its result and model revision identifiers.
It does not replace an existing case or summary case at the result path.
The session service holds ownership through mutation and native verification.
Only a verified current case receives a trusted view binding.

Normal native grid import can also import the companion summary file.
Importing the summary first supports both native summary import settings through one fixed load order.
Native grid import can replace that summary object with another object at the same file path.
Verification resolves the current exact-path summary after grid import instead of retaining the first object.
Existing exact grid or summary paths still fail before any import.

Native verification checks the exact file paths, grid dimensions, main-grid active cell order, and report indices.
It also checks every active-cell corner against the accepted geometry.
It checks calendar dates, elapsed days, all dataset cell properties, and all dataset summary curves.
Extra initial grid reports and internal summary samples are allowed.
Each requested summary report must match one serialized timestamp.
Timestamp matching uses the report date and fractional elapsed day from the supported midnight-start models.

Value comparisons allow two single-precision representable steps at each reference magnitude.
OPM restart and summary values supply the reference precision.
This tolerance permits native serialization rounding without permitting engineering differences.
Nonfinite values and different array lengths fail.

The pinned RIPS API has no independent grid-unit or summary-unit getter.
P11 verifies units from the exact files before native access.
Native values must then agree with the corresponding accepted values and their verified source units.
The service does not claim an independent native unit read.

Geometry comparison uses absolute tolerance `1e-6` in the source length unit, with no relative tolerance.
The supported FIELD models use feet, so this allows one millionth of a foot for double-precision interpolation and serialization rounding.
This rule preserves the earlier P08 geometry criterion before the P12 native trial.
The trial must retain raw native corners, reference corners, and their differences with the tested source and native commits.
RIPS corners are reordered with `(0, 1, 3, 2, 4, 5, 7, 6)` to match OPM EGRID order.
`RifReaderOpmCommon` defines that mapping, and the native handler returns corners with positive depth.

## Fresh references and reopened projects

Loading cases and creating summary plots advance the project generation.
Old object references then fail the session checks.
`rebind(context, result_ids)` verifies current cases and issues fresh bindings without requiring a saved project.
Use it after adding another result or creating a summary plot.
It verifies every requested result before it starts binding them.

`restore(context, checkpoint_id)` uses the checkpoint's result identifiers with the same verification procedure.
A checkpoint can include parent and child results from the same session.
Each result retains its exact model identity.
The checkpoint's `model` remains its primary revision association.
Saved object identifiers never authorize new bindings.

## Summary images

`show_curve(SummaryPlotRequest)` verifies the native summary data and creates a plot for the exact requested curve.
It returns `EditedSummaryPlot` with an applied `SummaryPlotEditReceipt` and a separate observation outcome.
The receipt preserves the current application context, complete numerical curve, and native plot address.
Image persistence or delivery failures replace only the observation outcome after confirmed plot creation.

The plot title includes the result identifier, quantity, and unit.
Curve normalization is disabled.
Export targets the new plot's `MultiPlot` ancestor with a nonnegative native window identifier.
The child summary plot has identifier `-1`, which would export every docked plot.
A missing parent or negative window identifier fails before export.
The service exports and decodes one new PNG with the requested dimensions.
It never returns an earlier image after an export failure.

`SummaryObservation` carries the complete numerical curve, application context, native plot address, and source SMSPEC artifact.
It also carries an observation identifier, image artifact, UTC capture time, and metadata artifact containing its complete provenance.
A native failure without confirmed plot creation returns an uncertain mutation effect without an applied receipt.
The 3D observation store remains separate because its context describes a grid view.

## Evidence and limits

The maintained tests use real workspace storage and controlled native interfaces.
They cover known scenario differences, wrong mappings and times, wrong values and paths, fresh bindings, and saved image provenance.
They do not launch ResInsight or OPM Flow.
The lead records separate native acceptance before claiming application behavior.
The [lead integration record](evidence/p12/integration/environment.json) identifies the tested source, runtime versions, and remaining acceptance gates.
The [shared check log](evidence/p12/integration/shared-check.log) records 600 passing maintained tests, Ruff, ty, and strict documentation checks.

Source inspection used native commit `119850cfcfc761b5d4deffce42910c74e5853214` and its generated RIPS client.
The implementation uses `Project.load_case`, `Case.create_view`, and `Project.import_summary_case`.
It reads `SummaryCase.available_time_steps` and `SummaryCase.summary_vector_values`.
Plots use `SummaryPlotCollection.new_summary_plot` and `Plot.export_snapshot`.
Source inspection establishes these supported calls, not a successful runtime trial.

The first native trial failed when summary import followed grid import.
The native API returned `No result returned from Method`, and public owned-process cleanup succeeded.
Source inspection shows that normal grid readers enable summary import and that separate summary import skips an existing filename.
This supports a duplicate-import explanation, but the failed trial did not capture intermediate native inventory.
The fixed load order has maintained tests for both native summary import settings and duplicate-path rejection.
A fresh native trial must establish the repaired runtime behavior.

## Prepared native acceptance

`tests/results/native_acceptance.py` provides the bounded native trial.
It requires genuine P11 baseline and scenario results from one workspace session.
The scenario revision must identify the baseline revision as its parent.
Both results must pass the production accepted-result requirement before application launch.
The probe does not create simulator jobs or change numerical acceptance records.

The lead must authorize the native lane before running this command.
Use the reviewed `70399abb9eba31f713f72028ffe94ae0be4db2c4` build and its installed matching RIPS wheel.
Do not add Python, Qt, or library path overrides.

```sh
uv run --no-sync python -m tests.results.native_acceptance \
  --workspace /absolute/p11-workspace \
  --session SESSION_ID \
  --baseline BASELINE_RESULT_ID \
  --scenario SCENARIO_RESULT_ID \
  --well PROD \
  --executable /absolute/ResInsight \
  --native-source /absolute/ResInsight-source \
  --output /absolute/new-p12-evidence
```

The trial loads both exact bundles through the production result, session, and view services.
It captures final-report pressure and water saturation for both results with common legends and a common camera.
It exports a native well bottom-hole pressure plot with numerical provenance.
It then exports scenario `FOPR` at `1000 × 700` pixels while the `1200 × 800` well plot remains present.
Both requests, edit receipts, observations, and native plot inventories are retained.
The second request uses the inspected current project context and must identify a different parent window.
It records source and native arrays, verified source units, report mappings, complete corners, and numerical differences.
The source and native comparison records preserve complete model, job, result, and grid identities.

The trial saves a checkpoint containing both results and reopens its native project.
It makes sure that old references fail and restored bindings retain both exact results.
It then records fresh native values and geometry from the restored project.
The probe terminates only its service-owned application and records the close outcome.

After the trial, inspect all six images for meaningful content, correct quantities, visible units, and matching legends.
The completion record reports automated checks separately and leaves complete acceptance false until visual review.
Record the tested repository commit, native source commit, executable, installed wheel, command, and application logs with the evidence.
Review the raw geometry differences against the declared tolerance before accepting the trial.
Preserve failed attempts with their errors and logs.
This prepared probe does not establish completed native acceptance.
