# P08 native acceptance

The accepted trial is `trial-02`.
It loaded the generated P08 numerical result through the standalone Python API.
All 300 cells matched the generated geometry and final pressure reference.
The reference came from the official OPM result reader.
OPM is the Open Porous Media project.

## Result

The grid has 10 by 10 by 3 cells, with all 300 cells active.
The readback matched I-fastest cell order, cell centers, corner extents, and positive-down depths.
Each horizontal cell dimension is 1,000 feet.
The layer thicknesses are 20, 30, and 50 feet, starting at 8,325 feet.
Every geometry comparison had zero error within a 0.000001-foot serialization tolerance.

The final report is day two, January 3, 2015.
All 300 pressure values matched OPM with zero difference.
The absolute pressure tolerance is 0.0009765625 psia, with zero relative tolerance.
This tolerance equals two float32 increments at the maximum reference pressure.
Pressure ranges from 4,438.43212890625 to 5,421.6787109375 psia.
PSIA means pounds per square inch absolute.

The generated FIELD specification establishes feet and pressure units.
The OPM summary reports DAYS for time and PSIA for producer pressure.
The native numeric values match those inputs and results.
The Python API does not expose an independent pressure unit label in this trial.

## Visual review

The reviewer inspected the accepted image at its original size.
It shows three layers, a complete grid, and the final time label `2/2 03.Jan 2015`.
The injector corner has higher pressure, and the producer corner has lower pressure.
The fixed legend spans 4,000 to 5,600 psia.
The view uses twentyfold vertical exaggeration to expose layer thicknesses.

![Final generated pressure](trial-02/images/P08_generated_FIELD_pressure_(psia)_day_2_3D_View_PRESSURE_02_03_Jan_2015.png)

## Provenance and cleanup

The tested Python source base is `0c99af6`, with the recorded acceptance runner added locally.
The numerical evidence records source commit `f289e8eee5ea500f1a1f32535c6a262b35abaf16`.
The native source commit is `119850cfcfc761b5d4deffce42910c74e5853214`.
The environment records contain commands, package versions, paths, and working tree state.
The copied receipt and source record bind this result to the generated model.
The native build record identifies the tested executable build.

Each trial launched one owned application.
The runner verified its process identity, command, executable, endpoint, and port file before use and cleanup.
Both trials ended through native Exit and verified that the owned process was absent.
The accepted trial used process 41712.
No simulator run occurred during this native trial.

## Rejected snapshot

Trial one passed the geometry and pressure comparisons, but its image showed day zero.
A later update sent stale view time state after the separate time command.
The automatic result recorded success before visual review detected this error.
Therefore, `trial-01/result.json` does not establish accepted visual evidence.
Its original logs and image remain preserved.

The runner now sets time with the other view fields.
It reads back the final view time before export and requires report index two.
The second trial repeated the native checks and produced the accepted final image.

## Scope

This evidence covers generated geometry, native result readback, and a locally exported pressure image.
It does not establish an MCP result loader or image delivery through MCP.
It does not include a model-provider trial.
Native editor inspection remains deferred under issue 34.
The shared check log records repository validation separately from these application checks.
