# P01 ResInsight control probe

This prototype probes one owned ResInsight 2026.09.0 GUI process through its Python API, `rips`.
It does not implement application package code or change simulator inputs.
The script requires `rips==2026.9.0.1` and Pillow from the repository environment.
The lead task owns dependency versions and runtime evidence.

## Run

Build the approved ResInsight GUI with its gRPC server enabled.
Use the SPE1 output from the P01 OPM experiment.
Pass a new output directory for each run.

```sh
uv run python experiments/platform/resinsight/controls.py \
  --executable /absolute/path/to/ResInsight \
  --grid /absolute/path/to/SPE1CASE1.EGRID \
  --well-route imported \
  --output /absolute/path/to/new-controls-output
```

The matching INIT and UNRST files must remain beside the EGRID file.
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
The script reads COMPDAT records from the exported files and compares their cells, well name, status, and transmissibility with API data.
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

## Known source concern

Source inspection found a possible unit mismatch in modeled-well creation.
The generic `add_new_object(rips.ModeledWellPath)` route leaves the default METRIC well unit system.
The GUI creation command instead assigns the common case unit system.
Completion export rejects a well whose units differ from the case units.
The inspected Python API exposes no modeled-well unit setter or case-aware creation command.
A separate modeled-route run must determine whether this prevents FIELD completion export.
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
Those checks do not establish runtime support or successful completion export.
No application run is claimed by this document.
