# P06 view evidence

P06 implements native view controls and image responses through configured production MCP bindings.
The native smoke checks and isolated model acceptance pass.
The observer received six native images and described their visible changes.
Native GUI legend inspection remains pending because Computer Use startup failed and macOS denied assistive access.
The default workspace launcher does not compose the view service or establish result lineage.

## Native controls

The latest tested native source is `1859d96e9a40093abfc43c42df9e9ef5b3846c9d`.
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

All 34 [native smoke checks](evidence/p06/native/results.json) passed at `949c4d3cb279b36ae500477f8a02405413ae5d79`, before the editor visibility repair.
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

The final repair hides four camera and legend readback fields from graphical editors while preserving scripting access.
The [repair delta](evidence/p06/native/repair/repair-delta.patch) adds four explicit visibility settings.
The [incremental rebuild](evidence/p06/native/repair/build-command.json) and RIPS generation succeeded at `1859d96e9a40093abfc43c42df9e9ef5b3846c9d`.
Its [build log](evidence/p06/native/repair/build.log) records that result.

All 11 [affected runtime checks](evidence/p06/native/repair/results.json) passed on a synthetic one-cell grid at that commit.
The [command](evidence/p06/native/repair/smoke-command.json), [script](evidence/p06/native/repair/smoke-script.txt), and [log](evidence/p06/native/repair/smoke.log) preserve the run.
Camera and legend fields retain scripting readback after the repair.
Both linked views reject validation and camera updates without changing their camera state.
Unlinking restores independent validation and camera updates.

The [repair record](evidence/p06/native/repair/native-build.json) identifies source review as the evidence for hidden editor fields.
Visual inspection did not run because Computer Use failed to start.
No screenshot establishes the repaired legend editor, and the earlier 34 checks were not repeated at this commit.

## Result provenance and MCP trial

The trial uses the completed [P01 SPE1 run](platform-opm.md), with 300 active cells and 120 completed report steps.
It archives the derived input deck, successful output files, and original run record in a new workspace.
It explicitly backfills the historical job record without claiming a new simulator execution.
Report metadata comes from the actual loaded native case, ending at 3,650 days on December 29, 2024.
The trusted setup binds that case to the stored result before the MCP server starts.

The isolated Codex observer used the existing authenticated OpenAI account for model inference.
Its payload contained six public SPE1-derived images, required view metadata, and issued test identifiers.
The observer cannot read simulator decks, output files, unrelated workspace files, or secrets through its supplied tools.
The owner approved the exact six public SPE1 images, view metadata, and test identifiers for this isolated provider transfer.
The [data boundary](../views.md#data-boundary) describes the product's provider configuration.

[Trial 03](evidence/p06/observer/trial-03/audit.json) reached project inspection but captured no images.
The client reported `MCP tool call requires approval, but approval policy is never`.
The isolated runner now uses [per-tool approval settings](https://learn.chatgpt.com/docs/extend/mcp) for `view_apply` and `view_render`, which the owner authorized.
These settings apply only to this invocation and its owned trial views.
The exact tool allowlist, read-only shell sandbox, and disabled unrelated tools remain unchanged.
Trial 04 completed after that repair at Python source `b0b41f65bb72599e6f12ba647cb4d47c2f53446c`.

The observer resolved the case, two views, and a well through `project_inspect`.
It applied five complete requests and rendered the unchanged control view once.
The six images compare initial pressure, final pressure, final gas saturation, and changed camera and filter settings.
Pressure comparisons retain bounds of 1,000 to 5,000 psi.
Saturation comparisons retain bounds of zero to one.

The gate checks issued references, typed receipts, actual camera values, fixed legends, distinct observation identifiers, and decoded 1200 by 800 PNGs.
It requires the model's final answer after all seven MCP calls and rejects unrelated tools.
The model must describe visible spatial and color changes from all six images.

The [original audit](evidence/p06/observer/audit.json) passed with exit code zero, seven completed MCP calls, and six native images.
Its `visual_claims_verified: false` field reserves the visual decision for separate review.
The audit remains unchanged.

The separate [visual review](evidence/p06/observer/image-review.json) records acceptance by the lead and an independent Codex agent.
Both reviewed all six images and accepted all four answer fields.
Saturation descriptions apply only to visible cells and do not establish numerical simulator accuracy.

The [environment](evidence/p06/observer/environment.json) records the tested sources, command, Python 3.12.13, MCP 1.30.0, and Pillow 12.3.0.
The [invocation](evidence/p06/observer/invocation.json) records `gpt-6-astra`, low reasoning, tool restrictions, and the exact prompt.
The [binding](evidence/p06/observer/server-binding.json), [responses](evidence/p06/observer/server-responses.jsonl), and [events](evidence/p06/observer/events.jsonl) preserve the production MCP exchange.
The [answer](evidence/p06/observer/answer.json) describes pressure, saturation, filtered geometry, and the unchanged control view.
The [package notes](evidence/p06/observer/README.md) identify omitted local setup files and the retained failure record.

| Image | Observed scene |
| --- | --- |
| [One](evidence/p06/observer/native-01.png) | Initial target pressure, with a red-orange full block. |
| [Two](evidence/p06/observer/native-02.png) | Initial control pressure, with the same full block. |
| [Three](evidence/p06/observer/native-03.png) | Final target pressure, with yellow and olive cells and greener cells near the right edge. |
| [Four](evidence/p06/observer/native-04.png) | Final gas saturation, with a green upper layer and blue lower side layers. |
| [Five](evidence/p06/observer/native-05.png) | A rotated, narrower half-block with exposed blue side layers. |
| [Six](evidence/p06/observer/native-06.png) | The control scene remains visibly unchanged. |

The retained [P05 controls](evidence/p05/image-review.json) come from September 8, 2026, at source `2842d9175ef01ebfab7fcbd67fb93edc39051f1d`.
The visible, hidden, and empty controls passed their original model runs.
This record does not claim a new P05 observer run.

## Maintained tests and review

The shared check passed 340 tests after the isolated approval repair.
The 35 maintained P05 and P06 gate tests also passed.
The evidence packaging [check record](evidence/p06/observer/repository-check.json) and [log](evidence/p06/observer/repository-check.log) preserve the final shared check.
It runs Ruff, ty, pytest, and the strict documentation build.
The maintained view tests cover scene changes, stale observations, result bindings, export failures, camera geometry, and native capability failures.
Gate tests reject missing images, incorrect dimensions, hidden content, wrong references, changed cameras, and incomplete call sequences.
Fixture tests do not claim native rendering or model-facing acceptance.

Independent reviews assessed duplicate behavior, branching, native ownership, maintenance cost, public failures, and evidence quality.
Review fixes preserve connection retirement after uncertain edits and validate native state after export.
Native review also caught unsupported filter deletion, raw-versus-rendered legend bounds, and unsafe category mapper readback.
The 34-check native run covers those corrected behaviors.

## Integration limits

The [user guide](../views.md) describes the configured MCP workflow.
The [implementation guide](views.md) records the trusted binding and required native APIs.
Production launcher composition and general result import remain separate integration work.
The trial bootstrap is explicit acceptance setup, not an MCP result importer.
View edits do not change simulator inputs, create well geometry, or run simulations.
