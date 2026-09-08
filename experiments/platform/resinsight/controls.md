# P01 ResInsight control probe

The imported-well control probe passed on the selected macOS 14.2.1 arm64 host on September 8, 2026.
It controls one owned ResInsight 2026.09.0 GUI process through its Python API, `rips`.
The script requires `rips==2026.9.0.1` and Pillow from the locked repository environment.
It does not implement application package code or change simulator inputs.

## Run

Build the approved ResInsight GUI with its gRPC server enabled.
Use the SPE1 output from the P01 OPM experiment.
Pass a new output directory for each run.

```sh
LC_ALL=en_US.UTF-8 \
QT_PLUGIN_PATH=/private/tmp/resinsight-p01-build/qt/6.7.0/macos/plugins \
uv run --locked python experiments/platform/resinsight/controls.py \
  --executable /absolute/path/to/ResInsight \
  --grid /absolute/path/to/SPE1CASE1.EGRID \
  --well-route imported \
  --output /absolute/path/to/new-controls-output
```

The matching INIT and UNRST files must remain beside the EGRID file.
The successful run used the explicit locale and Qt plugin settings above.
Its [command record](evidence/controls-imported-03/command.json) preserves the actual executable, grid, and output paths.
Choose `--well-route imported` for the main completion acceptance probe.
Choose `--well-route modeled` in a separate run to inspect modeled-well support.
The route is required and never changes automatically.
Add `--keep-open` only when retaining the owned application supports visual inspection.
The flag retains the process after success or failure.
The event log records its process identifier.

## Checks and evidence

The script launches a child with `--server 0 --portnumberfile` and reads its assigned port.
A second client attaches through that explicit port and reads the loaded case.
The script never searches for other instances.
Without `--keep-open`, cleanup terminates only the owned child process, even when client cleanup raises an exception.
A child that ignores termination receives a kill after ten seconds.

The fixture uses FIELD units, including feet for length.
The inspected grid contains 10 × 10 × 3 active cells across 10,000 × 10,000 feet.
Its top and bottom depths are 8,325 and 8,425 feet.
The script checks these bounds before creating a well.
It displays initial PRESSURE and final SGAS results with a vertical scale of 20.
It records result values and exports decoded PNG snapshots.
A reviewer must inspect the pictures before claiming useful visual output.

Both routes occupy cell column I=5, J=5 at x=4,500 and y=4,500 feet.
The modeled route creates `P01CTRL` with absolute targets at positive-down depths of 0, 8,325, and 8,430 feet.
The imported route writes `P01IMPORT.asc` with x, y, positive-down vertical depth, and measured depth columns in feet.
Its header is `wellname: P01IMPORT`, as supported by the pinned importer.
It imports the fixture through `project.import_well_paths` after loading the case.
The importer assigns case units when the first loaded case intersects the well bounding box.
This probe loads only the inspected FIELD case.
Both routes add a perforation from 8,326 to 8,374 feet, then extend its endpoint to 8,424 feet.
The script reads the edited interval back before exporting completions.
Measured depth means distance along the well from its start.
For this vertical well, measured depth equals positive-down vertical depth.
The trajectory API names its depth array `coordinate_z`, but returns positive-down true vertical depth.
The grid bounding box instead uses positive-up Z coordinates.

The script saves trajectory data, the project, and a well snapshot before exporting completions.
Completion export must produce files and positive transmissibilities for the three expected cells.
The script reads COMPDAT records from the exported files.
It compares their cells, well name, status, and transmissibility with API data.
COMPDAT records define simulator well connections.
A 0.1 percent relative tolerance allows exporter rounding of transmissibility.
This reader accepts the pinned exporter's simple table shape, not arbitrary simulator input syntax.
Transmissibility describes flow capacity between a well and a cell.
The structured completion data remains available when these checks fail.
An empty result is a failed control, not successful completion evidence.

The output directory contains `events.jsonl`, `application.log`, snapshots, `trajectory.json`, and `controls.rsp`.
It also contains completion files and `completion_data.json` when those API calls return.
The event log records the first Python exception and process cleanup.
An application error can occur before every artifact exists.

## Successful imported run

The [imported-03 events](evidence/controls-imported-03/events.jsonl) record success and owned-process cleanup.
The application reported API version `2026.9.0`, and rips reported client version `2026.09.0`.
The probe attached on explicit port 59372 to its owned process 53194.
The process closed after SIGTERM, with return code -15.
The [outer result](evidence/controls-imported-03/result.json) records successful probe completion.

The three fresh 1280 × 900 images decoded successfully and received lead and independent visual review.
The [review record](evidence/runtime-review.json) preserves the findings and confirms that no listed probe process remained.
The images show result labels and the imported marker, while trajectory and completion data establish the subsurface geometry.
The reviewed images are:

- [PRESSURE at step 0](evidence/controls-imported-03/pressure_initial/pressure_initialSPE1CASE1_3D_View_PRESSURE_00_01_Jan_2015.png).
- [SGAS at step 120](evidence/controls-imported-03/gas_final/gas_finalSPE1CASE1_3D_View_SGAS_120_29_Dec_2024.png).
- [Imported well with final SGAS](evidence/controls-imported-03/imported_well/imported_wellSPE1CASE1_3D_View_SGAS_120_29_Dec_2024.png).

The loaded grid matched the 300-cell FIELD fixture.
The edited perforation readback retained start depth 8,326 feet, diameter 0.5 feet, and skin factor 0.
Its endpoint changed from 8,374 to 8,424 feet.
The [trajectory](evidence/controls-imported-03/trajectory.json) contains 170 vertical samples from 0 through 8,430 feet at x=y=4,500 feet.
Measured depth and positive-down vertical depth agree for those samples.
The [saved project](evidence/controls-imported-03/controls.rsp) preserves the resulting application state and original experiment paths.
Those external case paths must remain available when reopening it.

The [completion API data](evidence/controls-imported-03/completion_data.json) contain the expected three positive connections.
The actual [P01IMPORT.inc export](evidence/controls-imported-03/completions/P01IMPORT.inc) matches their COMPDAT cells, name, OPEN status, and transmissibility within the stated rounding tolerance.

| I | J | K | API transmissibility | Exported value |
| --- | --- | --- | ---: | ---: |
| 5 | 5 | 1 | 10.0787802733 | 1.007878E+01 |
| 5 | 5 | 2 | 1.59138635894 | 1.591386E+00 |
| 5 | 5 | 3 | 10.3970575451 | 1.039706E+01 |

The exporter also emitted [P01IMPORT_MSW.inc](evidence/controls-imported-03/completions/P01IMPORT_MSW.inc).
The probe validates COMPDAT agreement, not all multisegment-well records in that additional file.
It does not simulate an edited deck or establish a complete well design workflow.

## Failed attempts and modeled route

[Imported-01](evidence/controls-imported-01/events.jsonl) stopped at the well name/count check after case, view, and image operations passed.
[Imported-02](evidence/controls-imported-02/events.jsonl) records both returned and project well names as `me P01IMPORT`.
Both attempts used `name P01IMPORT` in the fixture.
The successful third run used the documented `wellname: P01IMPORT` header in the same imported route.
The probe did not change well routes after either failure.

The importer first attempts floating-point extraction, then reads text after clearing the stream error.
It does not restore characters consumed by that numeric probe.
This source behavior is consistent with losing `na` before failure, but the exact runtime parser path was not traced.
The failed records preserve the observed header behavior.

The separate [modeled-01 run](evidence/controls-modeled-01/events.jsonl) created targets and read back the perforation edit.
Its [trajectory response](evidence/controls-modeled-01/trajectory.json) contains empty arrays.
The probe failed its trajectory check and closed its owned process before requesting completion export.
This run does not establish a runtime FIELD-unit export error.
Modeled-well controls remain unproved by this experiment.

## Known source concern

Source inspection found a possible unit mismatch in modeled-well creation.
The generic `add_new_object(rips.ModeledWellPath)` route leaves the default METRIC well unit system.
The GUI creation command instead assigns the common case unit system.
Completion export rejects a well whose units differ from the case units.
The inspected Python API exposes no modeled-well unit setter or case-aware creation command.
The failed modeled run did not reach completion export, so it does not test this unit concern.
The imported route uses the supported import unit assignment and a scripted perforation edit.
It does not establish modeled-well creation support or convert the fixture.

The relevant pinned source is ResInsight tag `v2026.09.0`:

- `GrpcInterface/Python/rips/instance.py`: port-file launch and explicit-port attachment.
- `ApplicationLibCode/ProjectDataModelCommands/RimcWellPathGeometryDef.cpp`: absolute target depth conversion.
- `ApplicationLibCode/ReservoirDataModel/Well/RigWellPathGeometryExporter.cpp`: positive-down trajectory depth.
- `GrpcInterface/RiaGrpcServiceInterface.cpp`: generic object creation.
- `ApplicationLibCode/FileInterface/RifWellPathImporter.cpp`: ASCII coordinate and depth order.
- `ApplicationLibCode/ProjectDataModel/WellPath/RimWellPathCollection.cpp`: imported-well unit assignment.
- `ApplicationLibCode/Commands/WellPathCommands/RicNewEditableWellPathFeature.cpp`: GUI well unit assignment.
- `ApplicationLibCode/Commands/CompletionExportCommands/RicWellPathExportCompletionDataFeatureImpl.cpp`: unit compatibility checks.

Ruff and ty provide static checks for the prototype.
The imported-03 artifacts provide the bounded runtime evidence.
The results apply only to this recorded host and configuration.
The [P01 PR](https://github.com/LukasMosser/resinsight-mcp/pull/22) records delivery and review.
