# Modeled wells and schedules

The Python well service loads a fixed model revision as a native working case.
It creates or updates modeled well paths and exports their cell connections.
A connection describes flow between a well and one reservoir cell.
Native well edits do not change simulator inputs.
The separate schedule service publishes those connections and requested controls as a child input revision.
These services currently have Python interfaces, without MCP well tools.

The service supports the existing FIELD black-oil input profile.
Coordinates use feet and positive-down depth with the prepared model's datum.
Measured depth is distance along the well from its first target.
Each well requires at least two targets and at least one perforation interval.
Multiple intervals must increase in measured depth without overlapping.

Intervals require positive diameters and nonnegative skin factors.
The modeled well name must already exist in the prepared simulator model.

## Python operations

`ResInsightWellService` receives a workspace store, session service, import service, and `RipsWellBackend`.
It also requires an absolute, canonical `source_root` for persistent native model files.
The native backend uses the session's existing verified ResInsight connection.
It requires the reviewed native commands for prepared input grids and case-aware modeled well creation.
The [native setup record](development/wells.md#native-feasibility) identifies the patches and matching generated client.
It does not open another native connection or run a simulator.

- `load(PreparedCaseRequest)` loads and validates one fixed model as a working case.
- `restore_case(PreparedCaseRestoreRequest)` verifies a reopened case against its saved model receipt.
- `create(WellCreateRequest)` creates a modeled well and returns its observed trajectory.
- `update(WellUpdateRequest)` replaces a well's targets and perforations at its expected version.
- `inspect(ObjectRef)` returns a current well after checking its native geometry.
- `adopt_well(WellAdoptRequest)` verifies an existing modeled well and issues its new service binding.
- `export(WellExportRequest)` stores an immutable completion snapshot for the expected well version.
- `get_export(ArtifactRef)` reads a service-issued snapshot after checking its stored content.
- `close()` waits for active calls and closes the service while preserving native source files.

Each operation returns `OperationResult` with either a value or a clear failure.
A failure marked `UNKNOWN` means that a native edit or artifact write can be incomplete.
Inspect the application and workspace before retrying such an operation.

A native change advances the application project generation and refreshes object references.
Use the returned well and case references for the next operation.
After another well changes, inspect the project to obtain its current well references.
The well service accepts refreshed references only within the project state it established.
After a project reopens, restore its case and explicitly adopt the existing wells before using their new references.

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
A separate schedule publication operation consumes that immutable snapshot through an open well service.

## Publish a child schedule

`OpmWellScheduleService` receives the import service and a well service that verifies stored completion exports.
Its `publish(WellScheduleRequest)` operation returns `OperationResult[ImportReceipt]`.
The request names the exact parent revision, issued export artifacts, and controls at existing report indices.
Each named well must already exist in the parent model at report zero.

This example uses an existing `imports` service, an open `wells` service, and a successful export named `completion`.
The parent must have at least two report entries, including report zero.
The exported well must be a producer.
BHP means pressure at the well's reference depth.

```python
from resinsight_mcp.contracts.wells import ProducerControl, WellStatus
from resinsight_mcp.models.wells.records import (
    ScheduledControl,
    ScheduledWell,
    WellScheduleRequest,
)
from resinsight_mcp.models.wells.service import OpmWellScheduleService

schedules = OpmWellScheduleService(imports, wells)
request = WellScheduleRequest(
    parent=completion.modeled_well.binding.model,
    wells=(
        ScheduledWell(
            export=completion.artifact,
            controls=(
                ScheduledControl(
                    report_index=1,
                    control=ProducerControl(
                        status=WellStatus.OPEN,
                        mode="BHP",
                        bhp_psia=1200.0,
                    ),
                ),
            ),
        ),
    ),
)
outcome = schedules.publish(request)
```

The child replaces the requested well's connections from report zero and applies each requested control after existing events at that report.
Later parent controls remain at their original reports and can supersede the requested control.
Unrequested wells, report times, grid properties, fluids, and the parent revision remain unchanged.
The service rejects changes to a well's producer or injector role and injection phase.
It preserves the actual exported connection values and supports the bounded FIELD input profile.

Check `outcome.outcome.status` before using the result.
On success, `outcome.outcome.value` contains the child import receipt.
On failure, `outcome.outcome.error` describes the error and mutation effect.
An `UNKNOWN` publication result can include the created child revision for recovery.
Publication does not run a simulator or update the native working case.
The [schedule reference](development/well-schedules.md) defines supported controls, units, preservation checks, and tolerances.

## Working case lifetime

The native working case depends on persistent EGRID and property files under `source_root`.
Each load uses its own session and receipt directory.
Service close preserves those files, which saved native projects need when reopening.
Keep these files at their original canonical paths.

The returned `PreparedCase.receipt` identifies an immutable record of the revision, source paths, and complete native grid corners.
After reopening a project, inspect its objects to obtain a current case reference.
Call `restore_case()` with that reference, its exact model, and the saved receipt.
The service checks parsed inputs, file identity, active-cell order, all properties, and all corners before returning a binding.

Call `adopt_well()` with the restored binding, a current well reference, its expected definition, and its expected sampled trajectory.
Adoption verifies the existing native well and returns version zero in a new binding.
An old reference remains stale, even if its earlier version was also zero.
Duplicate creation still fails and does not adopt an existing name.
Stored completion exports remain available through `get_export()` after service restart.

The [lifetime acceptance](development/evidence/p09/lifetime/README.md) records two save and reopen cycles with exact restored values.
The supplied launcher does not expose well or schedule tools.
