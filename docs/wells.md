# Modeled wells

The Python well service loads a fixed model revision as a native working case.
It creates or updates modeled well paths and exports their cell connections.
A connection describes flow between a well and one reservoir cell.
Native well edits do not change simulator inputs.

The service supports the existing FIELD black-oil input profile.
Coordinates use feet and positive-down depth with the prepared model's datum.
Measured depth is distance along the well from its first target.
Each well requires at least two targets and one ordered perforation interval.
Intervals require positive diameters and nonnegative skin factors.
The modeled well name must already exist in the prepared simulator model.

## Python operations

`ResInsightWellService` receives a workspace store, session service, import service, and `RipsWellBackend`.
The native backend uses the session's existing verified ResInsight connection.
It requires the reviewed native commands for prepared input grids and case-aware modeled well creation.
It does not open another native connection or run a simulator.

- `load(PreparedCaseRequest)` loads and validates one fixed model as a working case.
- `create(WellCreateRequest)` creates a modeled well and returns its observed trajectory.
- `update(WellUpdateRequest)` replaces a well's targets and perforations at its expected version.
- `inspect(ObjectRef)` returns a current well after checking its native geometry.
- `export(WellExportRequest)` stores an immutable completion snapshot for the expected well version.
- `get_export(ArtifactRef)` reads a service-issued snapshot after checking its stored content.
- `close()` ends the lifetime of the service's staged sources.

Each operation returns `OperationResult` with either a value or a clear failure.
A failure marked `UNKNOWN` means that a native edit or artifact write can be incomplete.
Inspect the application and workspace before retrying such an operation.

A native change advances the application project generation and refreshes object references.
Use the returned well and case references for the next operation.
After another well changes, inspect the project to obtain its current well references.
The well service accepts refreshed references only within the project state it established.
An external project change requires a new well service lifetime.

## Completion snapshots

The service verifies the fixed model's active cells, geometry, porosity, and permeability before well operations.
It rejects unsupported native filters, valves, fractures, and fishbones.
Completion export does not use the visible view filter.
Exported snapshots retain the model revision, well version, trajectory, wellhead, measured-depth intervals, and cell indices.
Cell indices are zero-based in the Python records.

`compdat_factor_field` uses centipoise times stock-tank barrels divided by days times psia.
`permeability_length_md_ft` uses millidarcies times feet.
The snapshot preserves an explicit native reference depth or its first-connection default.
Later native edits do not change a stored snapshot.
A separate schedule publication operation can consume that snapshot.

## Working case lifetime

The native working case depends on staged source files retained by the well service.
Explicit `close()` removes those files and ends the working case's supported source lifetime.
Close waits for running service calls and rejects new work before removing the files.
Do not close this service merely because an MCP connection disconnects while ResInsight survives.
Cleanup failures remain visible through the operation result.

This package does not establish restoration of these working cases from a saved native project.
Load the fixed model through a new service lifetime when starting a new application project.
Launcher recovery must manage staged-source lifetime before it advertises integrated well tools.
