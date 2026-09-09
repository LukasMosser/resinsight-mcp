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
The raw records remain under `/private/tmp/p09-modeled-probe/`.

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
Native commit `9b469c2` contains that patch and awaits build validation.

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
