# Wells and simulator inputs

P09 connects modeled well paths to fixed simulator input revisions.
A completion connects a well to reservoir cells.
Native edits and simulator input publication remain separate operations.
This page records the maintained services and their bounded native acceptance.
The [maintained service acceptance](#maintained-service-acceptance) records the final combined result.

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

The manual probe is `tests/resinsight/modeled_wells/native_probe.py`.
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
The lead reviews shared import inspection and revision publication interfaces.
The P07 follow-up implements these interfaces in a separate logical commit.
Its completion profile accepts explicit connection factors, permeability-length values, skin factors, and directions.
That profile preserves the existing black-oil physics.

## Prepared input probe

The manual probe `tests/resinsight/modeled_wells/input_probe.py` tests fixed inputs without a simulator run.
It imports the preserved SPE1 files through the model service and materializes the stored revision.
It compares native dimensions, active cells, depths, volumes, and imported properties with the validated inspection.
It then checks a modeled trajectory and the three reference completion factors described above.
Each run requires a new output directory and records process ownership and cleanup.

The first run used repository service commit `711bdc8` and native commit `119850c`.
Its [events](evidence/p09/prepared-input-initial/events.json) preserve an incorrect test assumption about coordinate direction.
Four invalid decks failed without changing the native case list.
The prepared grid had the expected dimensions and 300 active cells.
Its first cell center had API z `8335`, which correctly uses positive-down depth.
The test incorrectly expected `-8335`.
The probe stopped before checking volumes, properties, and completions.

The native grid builder converts positive-down depths to positive-up coordinates.
The grid API converts those coordinates back to positive-down depths.
The corrected probe compares the returned depth directly with the parser value.
Proposed native commit `4a9f259` would duplicate the conversion and will not be integrated.
The failed process 34091 exited with status `-15`, and the probe confirmed its absence.
Its start marker was `1788940220.433936`.
The preserved inspection and property file record the independent expected values.

The [second trial](evidence/p09/prepared-input-property-names/events.json) passed depth and volume checks, then failed on an unavailable property name.
The native property importer assigns unique result names but returns the original simulator keyword names.
The existing native `DX`, `DY`, and `DZ` geometry results cause their imported copies to receive suffixes.
The probe now compares computed native geometry values for these three dimensions.
It reads porosity and permeability through their advertised input property names.

The [third trial](evidence/p09/prepared-input-validated/events.json) passed all 20 checks at native commit `119850c` without a simulator run.
The [version record](evidence/p09/prepared-input-validated/versions.json) identifies the tested service and dependencies.
The first cell has positive-down depth 8,335 feet and volume 20,000,000 cubic feet.
Every native dimension, depth, volume, porosity, and permeability value matches the independent parser inspection within the recorded tolerances.
The modeled well produces the same three connection factors as the reference EGRID case.
The [export](evidence/p09/prepared-input-validated/P09INPUT.inc) preserves the native simulator records.

Process 43752 used start marker `1788940909.994174` and local port 59578.
It exited with status `-15`, and the probe confirmed its absence.
The screenshot shows the grid and `P09INPUT` label at the intended column.
The numeric trajectory and completion records establish subsurface geometry separately.
The screenshot displays the imported `DX_1` property, which has the expected constant value of 1,000 feet.
This earlier experiment established native feasibility before the maintained service acceptance described below.

![Prepared input grid and modeled well](evidence/p09/prepared-input-validated/prepared-input.png)

## Typed service contract

The shared P09 records and `CompletionSource` protocol live in `models/wells/records.py`.
The native service owns prepared case bindings and revalidates exact model geometry before well operations.
Caller-supplied bindings cannot establish trusted case ownership.
Every observed well carries its issued reference, version, definition, and sampled measured depths with positive-down coordinates.
Native changes require a current application context and advance the project generation.

Completion exports are immutable snapshots tied to the exact model, well reference, and well version.
The native service writes each snapshot to a workspace artifact and retains its issued identity.
`CompletionSource.get_export(reference)` returns `OperationResult[CompletionExport]` after verifying that identity and the stored artifact.
An export retains zero-based wellhead indices and the native reference depth in feet.
A missing reference depth preserves the native default, which uses the first connection.
Later visual edits do not rewrite an exported snapshot.

`compdat_factor_field` stores the FIELD COMPDAT connection factor.
Its unit convention is centipoise times stock-tank barrels divided by days times psia.
The pinned [OPM FIELD unit definitions](https://github.com/OPM/opm-common/blob/015a8107623afb4ea6ec35cff0d3d334fdb4c637/opm/input/eclipse/Units/Units.hpp#L310) define this conversion.
`permeability_length_md_ft` stores millidarcies times feet.
Exported connections require positive factors and diameters, nonnegative skin, explicit cell indices, and increasing measured-depth endpoints.
The service checks active cells against the stored model inspection.

`WellScheduleRequest` edits only existing prepared well names and preserves unrequested wells.
The schedule service rejects role changes, phase changes, duplicate names, and exports from another model revision.
Requested controls use existing report indices in increasing order without duplicates.
Connection replacement applies to the requested well from the initial report.
Each requested control applies at its report index, while unrequested controls retain their original timing.
The service publishes changed inputs through `derive_model()` and preserves grid identity because this operation does not change geometry.

Generation comments describe the inputs originally used to generate a model.
`read_specification()` recovers those inputs and does not establish a later edited schedule.
The stored parser-validated input graph defines the current simulator schedule.
The native service implements these interfaces through the session's existing verified RIPS connection.
The schedule service consumes immutable exports through the same records and `CompletionSource` protocol.

## Native service ownership

The initial P09 service retained temporary source files until explicit `close()`.
Its saved projects did not retain corner-point grid geometry.
The [persistent source follow-up](#persistent-source-follow-up) replaces that lifetime for launcher integration.

Each owned load captures the complete native corner geometry.
Later operations compare those corners and the parser-derived active cells, dimensions, depths, volumes, porosity, and permeability.
Numeric comparisons use relative and absolute tolerance `1e-6` for native floating-point storage.
The service requires explicit restoration after an untracked project state.
It refuses unexpected native well edits.
It also rejects unsupported filters, valves, fractures, and fishbones.
Sampled trajectory endpoints must match their positive-down targets within the same tolerance.

Public service tests use real workspace storage and session coordination with controlled native operations.
They cover creation, update, immutable exports, fresh references, depth signs, changed geometry, invalid cells, uncertain updates, artifact identity, and source cleanup.
Failed native result validation remains inside session ownership and retires the connection with an `UNKNOWN` outcome.
Refreshed inventories replace old address mappings before the service accepts new references.
Those controlled tests remain separate from real application acceptance.
The [integrated checks](evidence/p09/integrated/README.md) record the shared suite and independent service review.

## Persistent source follow-up

[Issue 48](https://github.com/LukasMosser/resinsight-mcp/issues/48) tracks the required P07 and P09 work for P13.
The change preserves the existing FIELD model profile and does not run a simulator.
Model inputs, native wells, simulator execution, and result analysis retain separate owners.

`OpmImportService.materialize_persistent(model, destination)` creates validated sources in a new, absolute, canonical directory.
Canonical paths contain no redirected ancestors.
The service rejects existing destinations, relative paths, and symbolic links before writing sources.
Temporary `materialize()` remains available for bounded parser and schedule operations.
`reopen_persistent()` compares retained sources with a fresh materialization of the immutable workspace revision.
It checks the include graph, parsed keyword values, default markers, report times, and model inspection.

The native `export_prepared_input_grid(path, output_path)` command uses the supported OPM `EclipseGrid::save()` writer.
It accepts FIELD units, bounds the grid size, and rejects existing output paths.
OPM writes unit metadata and corner geometry without application coordinate scaling or custom EGRID headers.
The backend loads that file through `project.load_case(path, grid_only=True)`.
It imports the verified property file and creates the working case view.
The existing session mutation boundary issues fresh case and view references.

`ResInsightWellService` requires an explicit, absolute, canonical `source_root`.
Each load creates a separate directory under its session and receipt identifiers.
`close()` waits for active calls and rejects new calls without removing these persistent sources.
Saved projects therefore retain their required EGRID and property paths after service shutdown.
Moving or deleting these files invalidates their supported source identity.
The service does not provide automatic source deletion.

Each prepared case returns an immutable `METADATA` receipt artifact.
The receipt records its exact revision, persistent source directory, and complete native corner baseline.
`restore_case()` requires a current case reference, the chosen model, and that receipt.
It verifies the workspace revision, retained parsed inputs, actual native EGRID path, active-cell order, and every corner and property value.
It does not accept an old object reference or a filename as proof of model identity.

`restore()` accepts `PreparedCaseLookupRequest` with the current project context, exact model, and saved receipt.
It validates the immutable receipt and retained inputs before finding one case at its canonical persistent EGRID path.
Missing, redirected, absent, or ambiguous source paths fail without creating a binding.
The lookup shares all existing restoration checks and does not infer identity from display names.
This public recovery path supplies the case lookup required by P13 without exposing native addresses.

`adopt_well()` requires a restored binding, a current modeled well reference, and the expected definition and sampled trajectory.
It checks native type, name, geometry settings, perforations, and all sampled points.
Successful adoption advances the project generation and issues version zero for the new binding.
Earlier references remain stale, including earlier version-zero requests.
A cloned model can explicitly adopt an existing native well name after obtaining its own prepared binding.
Duplicate creation still fails and never adopts a path silently.

Completion snapshots use immutable `METADATA` artifacts instead of an in-memory export registry.
`get_export()` verifies artifact identity, prepared receipt, model revision, well definition, and active-cell completion semantics.
It can resolve a prior export after a service restart without requiring live native objects.
Later native edits and adoption never rewrite an existing export.

### Matching generated client

The published `rips==2026.9.0.1` package does not contain these custom native commands.
The tested native bundle contains a matching generated Python package at `ResInsight.app/Contents/MacOS/Python`.
Copy that complete package directory into an isolated packaging directory.
Build its wheel with the supplied `pyproject.toml` and cached setuptools and wheel dependencies.
Install the application wheel and then explicitly install the matching RIPS wheel without editable mode.
Verify that `rips.__file__` identifies the selected environment and that `export_prepared_input_grid` exists.

Record the native commit, installed versions, and RIPS `direct_url.json` with the trial evidence.
Runtime `sys.path` changes and silent client substitution are not supported.

The isolated client installation passed against native commit `e9baf8b9eaa86ba2d44b9c9f5c1e29faa8321a67`.
The [client record](evidence/p09/lifetime/client-installation.json) records the noneditable wheel provenance.
The manual runner `tests/resinsight/modeled_wells/lifecycle_probe.py` checks one owned native process.
It compares complete grid, well, and completion readback after project close/reopen and service reconnection.
The [persistent lifetime acceptance](evidence/p09/lifetime/README.md) passed all 45 native checks.
That trial used the installed application and matching RIPS wheels with one verified owned process.
Its full geometry, trajectory, completion, and cleanup records remain separate from final P13 launcher acceptance.

## Maintained service acceptance

The final [combined trial](evidence/p09/service/README.md) passed all 64 checks on September 9, 2026.
It used service source `d862ec79f0dcee26ff88782c3db241c0ba191f1d` and native source `119850cfcfc761b5d4deffce42910c74e5853214`.
The runner is `tests/resinsight/modeled_wells/service_probe.py`.
It used one owned ResInsight process and the public well, schedule, import, workspace, and session services.
It did not run a simulator or use an imported trajectory.

The native readback preserves all 300 cell centers, 2,400 corners, volumes, and seven property arrays.
Create and update return positive-down trajectories ending at 8,430 and 8,450 feet.
The original immutable completion export retains version zero after the native well advances to version one.
The schedule service consumes that same issued export through the live well service.
It publishes a child with the exact parent revision and three parsed connections.
The [connection table](evidence/p09/service/trial-04/connections.md) compares native and parsed FIELD values.

The parsed child retains the parent geometry, properties, report dates, injector events, and initial producer control.
Its requested OPEN BHP control starts at report one and remains at report two.
The BHP target is `1200.1234567890123` psia.
Stored parent metadata and parsed parent values remain unchanged after publication.
Stale well versions and a well without active completions fail clearly.

Native geometry and reference completion comparisons use relative tolerance `1e-6` for floating-point storage.
The cell-depth comparison also allows `0.001` feet absolute tolerance.
Native property readback allows `1e-8` absolute tolerance.
Parsed completion values allow four machine epsilons relative tolerance and zero absolute tolerance.
OPM connection factors and permeability-length values use relative tolerance `1e-12` after conversion to SI units, with zero absolute tolerance.
Cell identities, controls, references, and parent lineage remain exact checks.

The accepted image shows the J=5 display slice through PROD, with PERMX from 50 to 500 mD.
Its vertical scale is 20, and its legend, slice bounds, property, and explicit camera are read back before capture.
The native display offset uses the full grid's center, so the slice target is `(0, -500, 0)`.
ResInsight ties orthographic eye distance to view height and field of view.
The runner computes that distance before setting the camera and retains strict readback checks.
Opaque cells hide the interior well segment, whose cell intersections are established by numeric records.

![Accepted native PERMX slice through PROD](evidence/p09/service/trial-04/serviceP09_PROD_J5_slice_PERMX_(mD)_3D_View_PERMX.png)

The snapshot record identifies the displayed native well as version one and the consumed completion export as version zero.
Its issued case and view references agree with the snapshot project and exact parent revision.
Owned process 5412 exited with status `-15`, and its PID was absent afterward.
Detach and staged-source cleanup both succeeded.
The [independent numerical review](evidence/p09/service/trial-04/independent-numerical-review.json) and [visual review](evidence/p09/service/trial-04/independent-visual-lifecycle-review.json) accepted these bounded results.
