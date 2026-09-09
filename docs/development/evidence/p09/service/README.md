# Maintained well service acceptance

Trial 04 passed all 64 checks and independent numerical, visual, and lifecycle review.
It used repository source `d862ec79f0dcee26ff88782c3db241c0ba191f1d` and native source `119850cfcfc761b5d4deffce42910c74e5853214`.
The [version record](versions.json) identifies the Python environment and generated RIPS client.
The [acceptance record](trial-04/acceptance.json) preserves the count, source identity, and process cleanup.
The [events](trial-04/events.json) preserve native arrays, trajectories, references, controls, and camera readback.

## Recorded trials

| Trial | Tested source | Result |
| --- | --- | --- |
| [01](trial-01/acceptance.json) | `3c04fb8` | Native export rejected an unset reference-depth string. No schedule or image acceptance. |
| [02](trial-02/acceptance.json) | `302f837` | All 60 service and numeric checks passed. Default image framing was rejected. |
| [03](trial-03/acceptance.json) | `6fb0975` | Service checks passed. Orthographic eye normalization failed the camera check before capture. |
| [04](trial-04/acceptance.json) | `d862ec7` | All 64 checks passed. The explicit display slice passed visual review. |

Each trial used a fresh owned process and a new output directory.
Every owned process exited, and detach and staged-source cleanup succeeded.
Rejected trials remain unchanged in this directory.

The native optional-field serializer writes an empty string for an unset reference depth.
The maintained boundary maps only that observed sentinel to `None`.
Explicit depths remain numeric, and malformed values remain failures.
The [independent source review](reference-depth-review.json) records the native and generated-client evidence.
Four public backend regressions cover empty strings, `None`, explicit values, and malformed depths.

The native orthographic camera keeps eye distance consistent with view height and field of view.
The runner uses `parallel_scale / tan(field_of_view / 2)` along its explicit viewing direction.
This matches the supported native normalization and retains strict camera readback.
Trial 03 preserves the rejected unnormalized request and its observed camera.

## Numeric evidence

The runner uses `ResInsightWellService` directly as the schedule service's `CompletionSource`.
It creates PROD, exports version zero, updates PROD, and publishes the earlier immutable export into a child schedule.
The complete native readback contains 300 centers, 2,400 corners, 300 volumes, and seven property arrays.
The original and updated trajectories end at 8,430 and 8,450 feet, with positive-down measured depth.
The complete [parent inputs](trial-04/inputs/parent/SPE1.DATA) and [child input](trial-04/inputs/child/SCHEDULE.DATA) remain available for inspection.

The [completion export](trial-04/completion-export.json) preserves the three zero-based cells `(4, 4, 0..2)`.
The [connection table](trial-04/connections.md) compares native FIELD factors and permeability-length values with parsed child values.
Factors use `cP·stb/(day·psia)`, and permeability-length uses `mD ft`.
Their reference values are approximately `10.078780273272798`, `1.5913863589378099`, and `10.397057545060358`, with `9500`, `1500`, and `9800 mD ft`.
The child retains injector events and the initial producer control, then applies OPEN BHP at report one.
The target `1200.1234567890123` psia remains active at report two.

Native comparisons allow relative tolerance `1e-6` for floating-point storage.
Cell depths also allow `0.001` feet absolute tolerance.
Native property readback allows `1e-8` absolute tolerance.
Parsed completion values allow four machine epsilons relative tolerance and zero absolute tolerance.
OPM schedule connections match parsed SI values within relative tolerance `1e-12`, with zero absolute tolerance.

The independent review accepts a one-step floating-point change in one preserved SWOF value within that serializer tolerance.
Identity, parent lineage, report dates, cells, and requested control fields remain exact checks.

The [numerical review](trial-04/independent-numerical-review.json) checks final consistency with the [full trial 02 audit](trial-02/independent-numerical-review.json).
Parent metadata and parsed parent values remain unchanged after publication.
The schedule receipt records a new child revision with the exact parent identity.
Stale versions and empty active completions fail clearly.
No simulator ran during this acceptance.

## Visual and lifecycle evidence

![Accepted J=5 PERMX slice](trial-04/serviceP09_PROD_J5_slice_PERMX_(mD)_3D_View_PERMX.png)

The image shows the full J=5 row through PROD, with three visible layers and a 50–500 mD PERMX legend.
The declared vertical scale is 20.
The display filter affects only this image, while completion checks use the full active-cell model.
Opaque cells hide the interior well segment, so the numeric records establish its cell intersections.
The snapshot record identifies native well version one, while the child consumes immutable export version zero.
The [visual and lifecycle review](trial-04/independent-visual-lifecycle-review.json) confirms the image and its issued references.

Process 5412 used the recorded executable, start marker, and command.
The attached session matched that process before native operations began.
The process exited with status `-15`, and its PID was absent after cleanup.
Detach and source cleanup both succeeded.
The saved project records the viewed state but does not establish restored-project support for staged in-memory grids.

## Reproduction

The runner requires the reviewed native commands and their matching generated RIPS client.
Use a new output directory for each trial.
The checked source contains the manual runner at `tests/resinsight/modeled_wells/service_probe.py`.

```sh
p09_build=/private/tmp/resinsight-p01-build
p09_app="$p09_build/application-build/ResInsight.app"
LC_ALL=en_US.UTF-8 \
QT_PLUGIN_PATH="$p09_build/qt/6.7.0/macos/plugins" \
PYTHONPATH="$p09_app/Contents/MacOS/Python:$PWD/tests/resinsight" \
uv run --locked python -m modeled_wells.service_probe \
  --output /private/tmp/p09-service-new \
  --executable "$p09_app/Contents/MacOS/ResInsight" \
  --source tests/models/imports/data/spe1 \
  --native-commit 119850cfcfc761b5d4deffce42910c74e5853214
```

The local [shared check](shared-check.log) passed 508 tests, Ruff, formatting, ty, and strict MkDocs.
Its [source record](shared-check.json) identifies the committed application source and copied documentation dependencies.
The [integrated checks](../integrated/README.md) separately record 518 tests on the lead's newer launcher base and the independent service review.
The accepted native trial is additional evidence, outside default pytest collection.
