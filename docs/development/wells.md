# Wells and simulator inputs

P09 connects modeled well paths to fixed simulator input revisions.
A completion connects a well to reservoir cells.
Native edits and simulator input publication remain separate operations.
This page records development evidence before the services are complete.

## Native feasibility

The first probe used repaired native commit `1859d96e9a40093abfc43c42df9e9ef5b3846c9d`.
It loaded the P01 FIELD grid `SPE1CASE1.EGRID` through the supported RIPS API.
It created three modeled well paths without importing trajectories.
The owned process used an automatically assigned local port.
Process 7383 had start marker `1788938007.638789` and exited with status 0.
The [baseline events](evidence/p09/baseline/events.json) preserve these observations.
The [application log](evidence/p09/baseline/application.log) records the native process output.

The source and runtime results establish these separate behaviors:

- Appending targets triggers geometry calculation through the existing native signal.
- Updating a target also recalculates geometry.
- An explicit sea-level target requires `use_auto_generated_target_at_sea_level = False`.
- With that setting, the vertical path returns 170 samples and ends at 8,430 feet.
- Updating its final target changes the endpoint to 8,450 feet.
- Target input and trajectory output both use positive-down depth in this API.
- Generic creation retains METRIC well units despite the loaded FIELD case.
- Those mismatched wells return no COMPDAT records and export only multisegment files.

COMPDAT records describe simulator connections.
The original P01 trajectory failure came from combining an explicit sea-level target with the automatic sea-level target.
That failure does not require a geometry implementation change.
The FIELD unit mismatch requires a case-aware creation command.

The proposed native command is `create_modeled_well_path_for_case(case_id, name)`.
It obtains units from the explicitly selected loaded case.
It rejects missing cases, unsupported units, empty names, and duplicate names before creating an object.
The native patch changes only `RimcWellPathCollection.h` and `RimcWellPathCollection.cpp`.
Existing target APIs and the P06 repair remain unchanged.
Native commit `9b469c2` contains that patch.
The lead reviewed and integrated it as `6ad2833930b3c1f8cc2939b08584f89e79dfd082`.
The [native build](evidence/p09/native-build/build-command.json) and matching Python client generation passed.
The [native patch](evidence/p09/native-build/modeled-well-units.patch) preserves the reviewed source change.
The existing P01 macOS overlays remain in place.
Those overlays enable macOS gRPC and modify the pinned OpenZGY submodule.
P09 changed neither overlay.

## Corrected native result

The case-aware probe passed 19 checks on September 9, 2026.
Its Python source matches repository commit `66c1f39367afc0d1a740bdea01f9ce4a4ef87346`.
The native process reported ResInsight `2026.9.0` at integrated commit `6ad2833930b3c1f8cc2939b08584f89e79dfd082`.
Process 14005 used start marker `1788938522.800408` and local port 56026.
It exited with status 0, and the probe confirmed its absence.
The [case-aware events](evidence/p09/case-aware/events.json) preserve all 19 checks.
The [version record](evidence/p09/versions.json) identifies the tested dependencies and source commits.

Both paths persist FIELD units and return the intended three active connections.
The one-based exported cells are `(5, 5, 1)`, `(5, 5, 2)`, and `(5, 5, 3)`.
The exported well names, OPEN status, and connection factors match the structured native response.
The factor comparison uses relative tolerance `1e-6` for the export's rounded decimal values.
Missing cases, empty names, and duplicate names fail without changing the observed well list.
Trajectory creation and target updates retain the expected positive-down endpoints.

The screenshot shows the grid and both well labels at their shared test column.
It does not establish subsurface geometry by itself.
The trajectory arrays and connection records establish that separate result.
The shared repository command passed 340 tests, Ruff, ty, and the strict documentation build.
Those 340 tests do not include the separately launched native probe.

Both wells produce the same connections in this bounded geometry experiment.
The [P09NOAUTO export](evidence/p09/case-aware/P09NOAUTO.inc) contains these rounded FIELD values.
Permeability-length describes permeability multiplied by the connected interval length.

| One-based cell | Measured depth, feet | Connection factor | Permeability-length, mD feet | Direction |
| --- | --- | --- | --- | --- |
| 5, 5, 1 | 8326–8345 | 10.07878 | 9500 | Z |
| 5, 5, 2 | 8345–8375 | 1.591386 | 1500 | Z |
| 5, 5, 3 | 8375–8424 | 10.39706 | 9800 | Z |

Each connection is OPEN, with diameter 0.5 feet and skin factor zero.
The additional multisegment files remain evidence artifacts and are not accepted simulator inputs.

![Modeled well labels at the expected grid column](evidence/p09/case-aware/modeled-wells.png)

## Bounded probe

The manual probe is `tests/resinsight/wells/native_probe.py`.
It is excluded from default pytest collection by its filename.
It requires explicit executable, grid, output, and creation arguments.
Each run requires a new output directory and records the launch command, process identity, observations, and cleanup.
The `generic` route measures existing behavior.
The `case-aware` route requires the reviewed native command and checks rejected creation, geometry, and exported connections.

The probe compares exported COMPDAT records through the official OPM parser.
It does not submit a simulator job or establish full P09 acceptance.
It does not change simulator physics or use an imported trajectory after failure.

## Agreed service boundary

Shared controls belong to `contracts/wells.py`.
P09 owns native trajectory and completion records.
The lead owns shared import inspection and revision publication interfaces.
The new completion support profile will accept explicit connection factors, permeability-length values, skin factors, and directions.
That profile will preserve the existing black-oil physics.
Its parser and native checks remain pending.
