# General geological authoring

This work implements the first geological delivery in the [approved issue #57 plan](issue-57-plan.md).
It adds general corner-point arrays and an original geological generator to the public MCP launcher.
A corner-point grid describes cells through pillars and corner depths.
The work keeps geological inputs separate from simulator preparation and native display.

## Current contract

`geological_create` accepts explicit `COORD`, `ZCORN`, and `ACTNUM` array artifacts.
It also accepts named cell fields, coordinate units, a local datum, and an optional parent revision.
`COORD` contains six values for each pillar.
`ZCORN` contains eight depths for each cell in Eclipse order.
`ACTNUM` identifies active cells with one and inactive cells with zero.
Cell fields use global cell order, with I changing fastest, then J, then K.
The stored model revision references immutable input artifacts.
The public model response contains compact array descriptions and its revision identifier.

`array_upload` stores a numeric array part with its unit.
`array_join` combines compatible references without copying their numeric values.
Joined arrays can exceed the maximum values in one message.
`array_range` loads only chunks that intersect the requested interval.
`array_inspect` reports the array count, unit, numeric type, and extrema.
Array descriptors and numeric chunks remain immutable across MCP restarts.

`geological_generate` is a convenience operation over the same explicit array representation.
It accepts dimensions, extents, depth, thickness, folds, faults, rock bands, and optional channel properties.
Faults displace cells across specified lines in the horizontal plane.
Fold terms change the layer surfaces, and thickness variation changes the local layer thickness.
Rock bands specify porosity and permeability over fractions of the thickness.
The optional channel changes properties along a sinusoidal horizontal path.
The optional elliptical boundary creates inactive cells outside the model footprint.
These helpers do not define the complete set of geometry accepted by `geological_create`.

## Native boundary

`geological_load` exports a persisted GRDECL file and loads it with ResInsight's public `Project.load_case` interface.
It uses the existing session service for application ownership and current project references.
Native dimensions, active cell counts, and every authored active property value must match the stored model.
Property comparison uses relative tolerance `1e-6` and absolute tolerance `1e-8` for native numeric conversion.
A successful load returns a receipt, case reference, and view reference.

`geological_verify` returns selected native cell corners and the maximum coordinate error for each cell.
Coordinates use the source length unit and positive-down depth.
The comparison interpolates corner positions along the authored pillars.
Coordinate comparison uses relative tolerance `1e-7` and absolute tolerance `1e-6` for native text and numeric conversion.
The operation also verifies authored active property values.

`geological_render` applies an explicit camera, property, vertical exaggeration, and optional J section.
It returns an applied edit receipt and a separate observation outcome.
A failed image must preserve the confirmed view edit.
ResInsight can move an orthographic camera along its viewing axis while preserving the projected image and scale.
The receipt records the observed camera position.
A successful observation includes a newly exported PNG as MCP image content.
`geological_restore` verifies a durable load receipt against current native case and view references after project reopening.

## Resource configuration

Enable this delivery with `--enable-general-models`.
Add `--resinsight-log-directory` to enable native geological tools.
This delivery requires NumPy and does not require OPM or Docker for geological authoring.
Native camera controls require the matching generated RIPS client and the reviewed ResInsight build used by the existing view tools.

Pass an absolute JSON path with `--authoring-policy` to select operator budgets.
The configuration has these defaults:

```json
{
  "working_memory_mib": 512,
  "request_values": 65536,
  "response_values": 4096,
  "native_rpc_timeout_seconds": 30,
  "native_launch_timeout_seconds": 120
}
```

These values constrain working estimates and individual transfers.
They do not prescribe grid dimensions, total array length, or well counts.
`general_capabilities` reports the active policy and implemented geometry support.
Generation uses NumPy arrays and currently requires a working estimate within the configured budget.
The budget is an admission estimate, not an operating-system memory limit.
Native application memory remains separate from the Python estimate.
A disk write failure remains an explicit storage failure.
Unreferenced artifacts can remain after interrupted publication, while unpublished model revisions remain unavailable.

## Remaining approved work

This delivery establishes geological authoring and native inspection, not a complete general simulation workflow.
It does not create fluid tables, well declarations, completion schedules, or simulator controls for these geological revisions.
It does not remove the existing limits in the earlier SPE1 and OPM workflow.
General polyhedral grids, local refinement, branching wells, broader physics, and asynchronous authoring remain adapter work under issue #57.
The current native verification streams the available native API and can inspect more cells than the requested response contains.
Some model validation and property verification still allocate complete numeric arrays within the configured estimate.
Native launch and RPC deadlines are configurable through the same visible operator policy.
The synchronous workspace operation lock still applies.
These are explicit implementation gaps in the approved plan, not permanent model ceilings.

## Evidence

The maintained tests cover array joining, bounded reads, ownership, fault offsets, layer ordering, explicit arrays, and MCP recovery.
The shared command also checks the existing suite and strict documentation build.
The [acceptance script](evidence/general-models/acceptance.py) uses the installed MCP launcher for every engineering operation.
Its model uses original folds, displaced faults, heterogeneous layers, channel properties, and inactive cells.
The evidence record will distinguish tested geological behavior from remaining simulation scope.
