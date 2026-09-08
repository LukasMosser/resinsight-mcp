# P06 view evidence

P06 implements native view controls and image responses through configured production MCP bindings.
The native smoke checks pass, and a local SDK client completes six image captures.
Model-facing acceptance remains a separate gate until the isolated observer receives and describes those native images.
The default workspace launcher does not compose the view service or establish result lineage.

## Native controls

The tested native source is `949c4d3cb279b36ae500477f8a02405413ae5d79`.
The [13-file patch](evidence/p06/native/view-controls.patch) applies to ResInsight source `197d58a750dd0bc243025b3939ab2a8a01a2c709`.
It uses the [P01 macOS build configuration](platform-resinsight.md#approved-build-path), with Qt 6.7.0 and LLVM 19.1.7.
The prior vcpkg and openzgy configuration changes remain separate from this patch.
No binary distribution or new simulator physics is included.

The patch exposes projection control, live camera values, legend settings, actual legend bounds, and display range filters.
It initializes newly scripted filters and selects the correct property legend after a scripted result update.
It also rejects unsupported linked views, missing viewers, and unsupported filter states.
Normal graphical projection changes retain their existing scene extent.

The [build command](evidence/p06/native/build-command.json) records a successful rebuild and generated RIPS package.
The [build log](evidence/p06/native/build.log), [versions](evidence/p06/native/versions.json), and [paths](evidence/p06/native/native-build.json) identify that environment.
The application uses its matching generated RIPS package through an explicit Python path.
The released `rips==2026.9.0.1` package alone does not contain the added APIs.

All 34 [native smoke checks](evidence/p06/native/results.json) pass.
The [command](evidence/p06/native/smoke-command.json), [script](evidence/p06/native/smoke-script.txt), and [log](evidence/p06/native/smoke.log) preserve the checks.
The log includes earlier exploratory failures before the final successful run.
The final command record identifies exit code zero and the tested native commit.

| Check | Observed result |
| --- | --- |
| Camera | Projection, field of view, parallel height, and repeated calls retain requested values. |
| Invalid camera | Zero, negative, infinite, and invalid angular values fail without changing camera state. |
| Legends | Decimal bounds read back as `0.12345` and `0.9876500000000001` after clearing prior logarithmic and centered settings. |
| Category legend | An inactive category legend reports unavailable bounds without unsafe mapper access. |
| Range filter | One included cell becomes visible, while the second view retains its filter collection. |
| Unsupported filters | Displayed non-range filters and active data filters reject view control before mutation. |
| Missing viewer | A console-only view rejects camera control and reports unavailable live camera values. |
| PNG output | A fresh PNG decodes with the requested 320 by 240 dimensions. |

The smoke image establishes decoded dimensions only.
Its tight camera framing does not clearly show the selected cell.
The cell-visibility check uses the native visibility API.
These checks do not establish model-visible images or numerical simulation accuracy.

## Result provenance and MCP trial

The trial uses the completed [P01 SPE1 run](platform-opm.md), with 300 active cells and 120 completed report steps.
It archives the derived input deck, successful output files, and original run record in a new workspace.
It explicitly backfills the historical job record without claiming a new simulator execution.
Report metadata comes from the actual loaded native case, ending at 3,650 days on December 29, 2024.
The trusted setup binds that case to the stored result before the MCP server starts.

ResInsight, artifact storage, and MCP transport execute on the workstation.
The isolated Codex observer uses the existing authenticated OpenAI account for model inference.
Its payload contains public SPE1-derived images, required view metadata, and issued test identifiers.
The observer cannot read simulator decks, output files, unrelated workspace files, or secrets through its supplied tools.
The owner explicitly authorized this model-provider transfer and requested documentation of the product's data boundary.

The observer must resolve the case, two views, and a well through `project_inspect`.
It must apply five complete requests and render the unchanged control view once.
The six images compare initial pressure, final pressure, final gas saturation, and changed camera and filter settings.
Pressure comparisons retain bounds of 1,000 to 5,000 psi.
Saturation comparisons retain bounds of zero to one.

The gate checks issued references, typed receipts, actual camera values, fixed legends, distinct observation identifiers, and decoded 1200 by 800 PNGs.
It requires the model's final answer after all seven MCP calls and rejects unrelated tools.
The model must describe visible spatial and color changes from all six images.
Separate visual review must assess those descriptions before acceptance is complete.
The maintained P05 visible, hidden, and empty controls remain part of the final image gate.

## Maintained tests and review

The shared check passes 230 tests before final integration.
It runs Ruff, ty, pytest, and the strict documentation build.
The maintained view tests cover scene changes, stale observations, result bindings, export failures, camera geometry, and native capability failures.
Gate tests reject missing images, incorrect dimensions, hidden content, wrong references, changed cameras, and incomplete call sequences.
Fixture tests do not claim native rendering or model-facing acceptance.

Independent reviews assessed duplicate behavior, branching, native ownership, maintenance cost, public failures, and evidence quality.
Review fixes preserve connection retirement after uncertain edits and validate native state after export.
Native review also caught unsupported filter deletion, raw-versus-rendered legend bounds, and unsafe category mapper readback.
The final native smoke checks cover those corrected behaviors.

## Integration limits

The [user guide](../views.md) describes the configured MCP workflow.
The [implementation guide](views.md) records the trusted binding and required native APIs.
Production launcher composition and general result import remain separate integration work.
The trial bootstrap is explicit acceptance setup, not an MCP result importer.
View edits do not change simulator inputs, create well geometry, or run simulations.
