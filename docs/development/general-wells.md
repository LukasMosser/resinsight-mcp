# General wells and completions

This delivery continues [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57) after the geological authoring delivery.
The owner authorized continuation on September 12, 2026.

## Contract

A well plan identifies one immutable geological model, a name, a role, and an optional injection phase.
Targets and perforation intervals use stored numeric arrays in the model's declared length unit and positive-down coordinate frame.
Measured depth starts at the first target.
ResInsight constructs the curved trajectory through its supported modeled-well API.
The sampled native trajectory remains an observed output, separate from the target points.

The general path has no fixed well, target, interval, or connection count ceiling.
Multipart uploads and bounded array queries control transport size.
The configured working-memory budget controls input materialization before native calls.
Native calls retain configured deadlines and can return explicit failures.
Branches and completion devices require later verified adapters.

Native loading requires the authored grid and its directional permeability fields.
It does not require a simulator deck or previously declared simulator well names.
Every exported connection must identify an active cell, with depth endpoints inside requested perforation intervals.
Exports retain native connection factors, permeability-length values, diameter, skin, direction, status, and measured-depth endpoints.
Units distinguish METRIC and FIELD simulator conventions.
ResInsight combines multiple intervals in one cell, so aggregate depth bounds can span gaps.

Immutable well plans and native receipts preserve model and artifact lineage.
Saved receipts support explicit verification after project reopening and MCP restart.
Restoration compares native targets, intervals, and sampled geometry with the saved record.
Re-export verifies grid properties and computes current connections.
Acceptance compares those connections with the earlier immutable export.

Simulator schedules consume these records in the next delivery.
This change does not make a geometry-only model ready for simulation.

## Acceptance

The target fixture has 100 by 200 by 50 active cells and the three permeability bands from issue #57.
Two opposite-corner producers and one central water injector must each return 50 verified layer connections.
Small fixtures establish vertical, slanted, horizontal, separated-interval, and inactive-cell behavior.
Both meters and feet require native evidence.
The public MCP client must create all inputs, query stored outputs, save the project, and restore it after restart.

Maintained tests cover ownership, units, interval validity, multipart targets, immutable records, and important native failures.
Native evidence records versions, original calls, numerical comparisons, images, time, memory, and cleanup.
The shared repository command must pass before review.

## Native sources

The adapter uses the reviewed native build and its matching generated RIPS package.
The [WellPath API](https://api.resinsight.org/en/main/api/rips.WellPath.html) documents trajectory sampling and completion data.
The reviewed `CreateModeledWellPathForCase` method assigns the selected case's METRIC or FIELD unit system.
Source inspection alone does not prove that geometry-only completion export works.
The [acceptance record](evidence/general-wells/README.md) reports observed support and remaining limitations.

## Public operations

`general_well_define` stores a plan and accepts array references, rather than complete inline trajectories.
`general_well_inspect` reads that plan after workspace or MCP restart.
`general_well_load` creates the native path and returns refreshed grid and well references.
Native creation changes the project generation, so callers must use those refreshed references.
`general_well_restore` verifies a saved well receipt against explicitly selected current objects.
`general_well_export` stores native connections, and `general_well_connections` reads their compact description.

Targets contain repeated `(x, y, depth)` triples in model units.
Perforation arrays contain `(start_md, end_md, diameter)` triples in those units.
A separate dimensionless array contains one skin value per interval.
Skin describes added resistance near a well.
`sampling_distance` sets the native trajectory sampling interval in model units.
Sampled trajectory arrays contain `(x, y, depth, measured_depth)` rows.

Use `array_upload` and `array_join` to supply multipart arrays.
Use `array_range` to query trajectory and connection arrays.
Connection arrays contain zero-based cell indices, native factors, permeability-length products, diameter, skin, direction, status, and depth bounds.
Direction codes are X=1, Y=2, and Z=3.
Status codes are SHUT=0 and OPEN=1.
Factor units use the named `ECLIPSE_METRIC_COMPDAT` or `ECLIPSE_FIELD_COMPDAT` convention.

The [authoring configuration](general-model-authoring.md) controls request sizes, response sizes, memory estimates, and native deadlines.
The native API currently returns each sampled trajectory and completion table in one response.
Their complete native allocations remain subject to ResInsight and host resources.
The MCP stores returned arrays before exposing bounded queries.
Asynchronous authoring, well branches, native path updates, schedules, and simulation preparation remain under issue #57.

## Required native correction

Acceptance found that the reviewed ASCII reader ignored `GRIDUNIT` and used METRIC units for FIELD inputs.
The native correction preserves declared units and exposes `case.grid_unit_system()`.
The MCP requires that query before well creation, restoration, or export.
It rejects unavailable queries and mismatched native units before well mutation.
The native patch and generated-client instructions appear in the acceptance record.
