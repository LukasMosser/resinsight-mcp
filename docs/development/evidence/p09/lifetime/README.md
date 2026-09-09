# Persistent well lifetime acceptance

[Issue 48](https://github.com/LukasMosser/resinsight-mcp/issues/48) supplies the P07 and P09 prerequisite for P13.
The [acceptance record](acceptance.json) identifies the command, source commits, Python version, and check counts.
The shared repository command and pre-commit hook passed 550 maintained tests, Ruff, ty, and the strict documentation build.
The [shared log](shared-check.log) records those checks separately from the native trial.

## Native export build

The [native patch](native-build/prepared-grid-export.patch) adds `export_prepared_input_grid(path, output_path)`.
It uses OPM's supported EGRID writer and accepts only the existing FIELD profile.
It does not create native cases or run a simulator.
The first [build trial](native-build/trial-01/build.log) failed because the empty connection vector required the complete `NNCdata` declaration.
The supported `NNC.hpp` include fixed that compile error.
The export [build command](native-build/build-command.json) and [build log](native-build/build.log) passed at native commit `e9baf8b9eaa86ba2d44b9c9f5c1e29faa8321a67`.

The [reload patch](native-build/property-reload.patch) loads each property source once and preserves source order.
It also creates ordinary derived results before property reload, preserving initial property names.
Nested hybrid ordering and existing preferences remain unchanged.
The [deduplication build](native-build/deduplication/build.log) and [stable-name build](native-build/stable-names/build.log) passed.
The accepted native source is `551dc02e19a1eb75ae462a0313f7a9a3101c2f45`.
These internal fixes do not change the generated RIPS interface.

## Earlier trials

[Trial 01](trial-01/events.json) passed its original 42 checks but did not establish stable property inventories.
Review found seven imports of the same source file during reopening.
Deduplication removed that growth, but [Trial 02](trial-02/events.json) failed the new exact inventory check.
Derived names changed from `DX_1`, `DY_1`, and `DZ_1` to `DX`, `DY`, and `DZ`.
The corrected load order passed the unchanged probe in Trial 03.
Both earlier trials retain their original records and successful owned-process cleanup checks.

## Installed client and application

The trial used a wheel built from that native bundle's complete generated Python package.
The [client installation](client-installation.json) records its native source and wheel provenance.
The [runtime installation](runtime-installation.json) records both installed application and RIPS module paths and their `direct_url.json` metadata.
Both packages used ordinary noneditable wheel installation inside an isolated environment.
No runtime `sys.path` changes or source checkout imports supplied application behavior.

The [dependency installation](runtime-sync.log) used the existing lockfile and cached dependencies.
It excluded the published RIPS package before installing the [explicit matching wheels](application-install-final.log).
The native trial used ResInsight `2026.9.0`, RIPS `2026.9.0.1`, OPM `2025.10`, grpcio `1.83.1`, and protobuf `7.36.1`.
No packages were downloaded for this trial.

## Saved-project result

The manual runner `tests/resinsight/modeled_wells/lifecycle_probe.py` passed all 45 [native checks](trial-03/events.json).
The installed application source was `a60788d`, and the manual probe source was `ce76239`.
Its [launch request](trial-03/launch-request.json) created one owned native process.
Invalid parser input, METRIC input, and an existing export destination failed without changing native cases.
Parsed `GRIDUNIT` contained `FEET`.

The service exported a persistent EGRID, loaded it with `grid_only=True`, imported seven property arrays, and created the working view.
It then created PROD and saved the [native project](trial-03/saved-project-2.rsp).
The runner completed two save and reopen cycles before detaching the original service connection.
The exact seven-property inventory remained unchanged after [cycle one](trial-03/input-properties-1.json) and [cycle two](trial-03/input-properties-2.json).
A fresh service and workspace handle restored the current case using its immutable receipt.
Explicit well adoption issued a new connection identity and version zero.
The old reference failed, and the service retrieved the earlier immutable export from workspace storage.

The [before readback](trial-03/before.json) and [after readback](trial-03/after.json) retain 300 cell centers, 2,400 corners, active-cell order, and seven property arrays.
Every saved and reopened value matched exactly.
Independent parser comparisons used relative tolerance `1e-6` for native floating-point storage.
Depth comparisons also allowed `0.001` feet absolute tolerance, and property comparisons allowed `1e-8` absolute tolerance.
The [receipt](trial-03/after-receipt.json) ties all corner coordinates to the exact model revision and persistent source path.

The [created well](trial-03/created.json) and [adopted well](trial-03/adopted.json) each contain 170 trajectory samples ending at 8,430 feet.
The [earlier completion snapshot](trial-03/export-before.json) and [restored snapshot](trial-03/export-after.json) retain the same three connections.
Their zero-based cells are `(4, 4, 0)`, `(4, 4, 1)`, and `(4, 4, 2)`.
Their FIELD factors are `10.078780273272798`, `1.5913863589378099`, and `10.397057545060358`.
Those factors match the earlier P09 reference within relative tolerance `1e-6`.

The image shows the restored J=5 PERMX slice, the PROD label, and the 50 to 500 mD legend.
The display scale is 20.
Opaque cells hide the interior well segment, whose trajectory and cell connections are established by the numeric records.

![Restored prepared grid and PROD after native project reopening](trial-03/restoredP09_PROD_J5_slice_PERMX_(mD)_3D_View_PERMX.png)

The [owned process record](trial-03/owned-connection.json) identifies PID `92906` and start marker `1788971155.851697`.
The runner verified that identity before [termination](trial-03/cleanup.json).
The final check confirmed that the PID was absent.
Persistent model sources remained available after service close.

## Scope and limits

The [lead integration record](integration/environment.json) identifies the tested source and current tool versions.
Its [shared check log](integration/shared-check.log) passes 579 maintained tests, including source-path lookup and ambiguous-case failures.
Lead review inspected the complete accepted native checks and restored image before integration.
The new lookup uses the same verified restoration boundary, while full public MCP acceptance remains part of P13.

This trial establishes the bounded FIELD grid and well lifetime needed by the P13 launcher.
It does not establish full P13 MCP acceptance or simulator execution.
P11, P12, and the lead's clean launcher trial retain their separate evidence requirements.
The browser URL policy blocked inspection of the local rendered guide.
The strict documentation build passed, and the native screenshot was inspected directly.
