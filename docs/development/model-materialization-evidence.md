# Model materialization evidence

[Issue #39](https://github.com/LukasMosser/resinsight-mcp/issues/39) extends P07 with temporary stored inputs and child revision publication.
Materialization means staging validated inputs for temporary use.
The tested source is `32fd79e7238a7dad416da4e5be7318ca2febecf3`.
The seven changed files match the reviewed change `ef3b6910c9b435046c6117dd8f11fd588a1aab44`, including its cleanup fixes.
The [import guide](model-imports.md#materialization-and-child-revisions) describes the public interface and ownership transfer.

## Public behavior

The public library tests use the stored model reference after deleting the original source directory.
They verify exact revision identity, independent staging directories, and removal of staged inputs and the property file after exit.
Changing one staged copy leaves another copy and the stored parent unchanged.
Missing revisions and input files outside the stored include graph fail before the context yields files.

The isolated OPM parser supplies cell order, geometry, static properties, and report times.
OPM is the Open Porous Media project.
The tests verify I-fastest indices, an 8,335-foot cell depth, and a 20,000,000-cubic-foot cell volume.
They check a 1,000-foot cell length, 500-millidarcy permeability, and report days zero, one, and two.
They parse the derived property file and compare all seven arrays with the inspection.
The arrays contain `DX`, `DY`, `DZ`, `PORO`, `PERMX`, `PERMY`, and `PERMZ` in FIELD units.

Child publication inherits the stored parent's session, coordinates, and units, and records its parent reference.
The tests change a schedule value and verify that the child contains it while the parent keeps the original value.
Invalid child inputs publish no artifacts.
An injected child publication failure preserves the parent and reports `UNKNOWN` after artifact writes begin.
This result requires recovery inspection and does not promise rollback.

## Profile and failure checks

New validation uses `spe1-field-v2`.
An existing `spe1-field-v1` summary still deserializes without rewriting its profile.
The pinned OPM version remains `2025.10`, and supported black-oil physics stays unchanged.
The tests compare explicit connection factors and permeability-length values with OPM schedule values in its standard units.
Invalid factors, permeability-length values, skin values, directions, and completion ranges fail validation.
Inactive-cell inputs remain outside the supported profile.

A consumer's `OSError` passes through as the same exception, and staged files are removed.
If cleanup also fails, the same consumer exception retains its mutation effect and receives a cleanup note.
If the consumer succeeds but cleanup fails, materialization reports `STORAGE_FAILED` with effect `UNKNOWN`.
A regression test invokes the context inside an unrelated exception handler.
It verifies that cleanup failure remains visible and does not attach a note to the unrelated exception.

## Validation record

The [environment record](evidence/model-materialization/environment.json) preserves the source commit, working state, versions, and commands.
The [shared check log](evidence/model-materialization/shared-check.log) records Ruff, ty, pytest, and the strict documentation build.
The [issue snapshot](evidence/model-materialization/issue-39.json) preserves the reviewed scope.
The [dependency log](evidence/model-materialization/dependency-sync.log) records the locked environment installation.
The shared command passed all 427 tests, Ruff, ty, and the strict documentation build.
The [result record](evidence/model-materialization/result.json) separates those outcomes from external acceptance.
The test output establishes public library behavior through the real workspace store and isolated parser.

The [integrated check](evidence/model-materialization/integrated/shared-check.log) passed 453 tests, Ruff, ty, and strict documentation after P08 merged.
The [integration record](evidence/model-materialization/integrated/result.json) identifies its source base and working changes.
The current guides name profile version 2 while preserving version 1 in historical P08 trial records.

The [browser record](evidence/model-materialization/browser/review.json) checked two local pages and eight local links without page errors.
The [visual review](evidence/model-materialization/browser/visual-review.json) records inspection of both captured screenshots.
The headings, text, and materialization table remained readable without clipping or overlap.
The [integrated browser review](evidence/model-materialization/integrated/browser/visual-review.json) covers the navigation, current profile, capability map, and linked evidence.

The review assessed duplicate behavior, control flow, ownership, failure handling, tests, and evidence limits.
Original imports and child revisions share one validation and publication path.
The materialization context owns staging cleanup and keeps consumer failures distinct from service failures.
The changed public tests exercise observable values and failure outcomes.
No blocking review finding remained.

## Evidence limits

This local check does not replace Linux and macOS CI.
It does not launch ResInsight, run a simulator, or exercise MCP wiring.
MCP is the Model Context Protocol for tool access.
Native input-grid and well acceptance belong to P09 under issue #10.
Those separate checks establish whether native consumers use these staged files correctly.
This record does not infer native success from library tests.
