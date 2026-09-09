# Constrained model creation

P08 uses the P07 `spe1-field-v1` profile without adding simulator physics.
The model contains an all-active Cartesian grid, a rectangular arrangement of cells.
Each horizontal layer has uniform thickness, porosity, and three directional permeability values.
The grid contains at most 10,000 cells.
Cell arrays vary I fastest, followed by J and K.
Coordinates use feet and positive-down depth.

`SyntheticModelService` renders complete inputs and delegates validation and publication to `OpmImportService`.
The request separates session identity and datum from reusable engineering inputs.
Shared FIELD control records define well control validation.
P08 owns its single-cell well placement records and does not depend on the P09 implementation.
The official OPM parser checks generated properties, cell order, connections, and controls in focused tests.

The source preserves canonical specification JSON and one generated grid identifier in separate comments.
The import service stores that source as the immutable revision entrypoint.
Readers recover the specification and grid identifier from that artifact after reopening the workspace.
The service adds no publication path or metadata artifact.
Source limits and publication failures remain owned by the import service.
Cleanup failures after successful import report the created revision with effect `UNKNOWN`.

## Physics template and data terms

The fixed template is `spe1-field-synthetic-v1`.
It retains the P07 SPE1 fluid tables and rock compressibility.
The packaged Python constant includes the source copyright and data notices.
Numeric table content remains unchanged, with whitespace wrapping for source readability.
Generated inputs must retain these notices.

The source is the [P07 SPE1 fixture](model-imports.md).
Copyright 2015 Statoil applies to the source data.
The Open Database License 1.0 and Database Contents License 1.0 apply separately from the software license.
This reuse does not change the repository software license.

## Numerical acceptance plan

The existing [P07 record](evidence/p07/acceptance.json) reports a 10 by 10 by 3 grid with 300 active cells.
The report at two days has pressure extrema of 4438.43212890625 and 5421.6787109375 psi.
The record identifies its Flow image, parser, ResInsight version, source revision, and prepared inputs.
It does not contain a solver repeatability study or a justified numerical tolerance.

P08 will reproduce that model through typed generation and compare semantic inputs before running Flow.
The coordinated acceptance will establish repeatability with the same pinned simulator image and recorded solver settings.
The numerical tolerance must reflect that evidence and the precision of the exported pressure values.
No numerical simulator acceptance is claimed by the grid tests.
