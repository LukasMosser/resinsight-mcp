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

## Numerical acceptance

Four isolated Flow trials passed at commit `f289e8eee5ea500f1a1f32535c6a262b35abaf16` on September 9, 2026.
Two trials used the preserved P07 fixture, and two used the generated reference specification.
Every trial reached two days with 300 active cells and the intended injector and producer connections.
All compared cell pressures, field oil rates, and well pressures had zero differences across both repeats and model sources.
The [P08 evidence](evidence/p08/README.md) records the source, commands, versions, tolerances, and complete numerical arrays.

The tolerance rule uses two representable output increments at each reference magnitude, with zero relative tolerance.
Cell pressure tolerance is 0.0009765625 psia, and field oil-rate tolerance is 0.00390625 stb/day.
The rule was fixed before execution and does not expand with measured repeat differences.
This evidence covers the pinned Flow runtime and the supplied gas-injection reference on the tested host.
Other generated specifications still require separate convergence checks.
The [native acceptance](evidence/p08-native/README.md) separately verifies generated geometry and pressure in ResInsight.
All 300 cell centers, corner extents, active-cell positions, and final pressure values matched their references.
The accepted image shows the final report, three layers, and opposite pressure changes at the injector and producer.
The record preserves a rejected first snapshot and the correction that produced the accepted image.
Production MCP model creation, simulation, and result loading remain separate integration work.

The service cleanup tests also cover failed cleanup after successful publication and after delegated import failures.
They preserve the created revision identity and retain `UNKNOWN` whenever publication may have happened.
No application source change was needed for these cases.
