# Run a FIELD model through MCP

Enable the [OPM workflow configuration](../mcp.md#enable-the-opm-workflow) before following this sequence.
Read `resinsight://catalog` for the complete request and response schemas.
Keep returned records for later requests instead of reconstructing identifiers or report times.
Every step uses public MCP tools from the supplied launcher.

## Create a session and fixed inputs

Create a named session with `session_create` and a new session identifier.
Read `model_template` to inspect the supported layered FIELD specification.
Call `model_create` with that specification, the session identifier, and an explicit local depth datum.
Alternatively, use `model_import` with the supported source directory and entrypoint.
The [model tutorial](models.md) explains these input operations.

Keep the returned `PreparedModel` and exact revision.
Call `model_inspect` to read dimensions, active cells, properties, report times, and existing simulator wells.
The supported model already defines its injector and producer names.
Native well creation must use those names and the model's coordinate frame.

## Create native wells and publish their connections

Launch an owned ResInsight application with `application_launch` and an absolute executable path.
Call `model_load_case` with its application context and exact model reference.
Keep the returned case binding and immutable receipt.
The case uses persistent grid and property files required by saved projects.

Call `well_create` for each well with the current binding, FIELD target coordinates, and measured-depth perforation intervals.
Each successful mutation returns fresh native references.
After another well changes, use `project_inspect` and `well_inspect` to obtain the first well's current reference and version.
The [well guide](../wells.md) explains coordinates, intervals, completion values, and separate schedule publication.

Call `well_export` with each current well reference and expected version.
The returned native connection records show active-cell indices, interval depths, connection factors, diameters, and units.
Keep these immutable export artifacts and display their connection records when checking the completion design.
`well_export_get` verifies a stored export after reconnecting.

Call `model_publish_schedule` with the exact parent model, export artifacts, and explicit controls at existing report indices.
The returned child revision contains those native connections and requested controls.
Its parent, other wells, grid properties, fluid inputs, and report schedule remain identifiable.
Native edits and exports alone do not change simulator inputs.

## Run and load the baseline

Pass the child receipt's prepared model to `job_submit` with explicit resource limits.
The supported maximum is two CPUs, 2048 MiB, and 60 wall seconds.
Poll the returned session and job identifier with `job_poll`.
A successful job establishes process completion only.

Call `opm_collect` after confirmed success.
Collection checks complete output files, model identity, units, report times, and numerical validity before returning an accepted result.
Keep the returned job, result, model, and report records.
The [OPM guide](../opm.md) explains the acceptance policy and the separate status of independent numerical reference agreement.

Inspect the current project and call `result_load` with its context, the exact stored job, and the accepted result.
The response binds the native case and views to that result.
Use `result_cell_property` for PRESSURE, SWAT, or SGAS at a returned report time.
Use `result_curve` for field FOPR or a named well's WBHP curve.
Each response retains source identity, units, time records, and values.

## Compare a changed scenario

Inspect the project and restore the original prepared case with `model_restore_case`, its exact model, and its saved receipt.
Use the current project context, because loading baseline results advanced the native generation.
Call `model_clone` with the baseline input revision and a new revision identifier.
Load the clone as a new prepared case.
To reuse existing native well names, call `well_adopt` with their current references and saved definitions and trajectories.
Adoption verifies the existing objects and issues new bindings without silently creating or replacing wells.

Export the adopted wells and publish another child with the requested changed control.
Submit, poll, collect, and load this scenario through the same public tools.
The scenario keeps distinct model, job, result, and grid identifiers.
After loading another case, use `result_rebind` with the current project context and both result identifiers.

Call `result_compare_cells` for matching properties and report times.
The response returns scenario values minus baseline values and one common legend.
Call `view_list` with each current loaded-result binding to find its views and read their cameras and display scales.
The response records the current scene version without applying display changes.
Apply that legend and a common camera to both views with `view_apply`.
Capture fresh PNG observations with `view_render`.
The [view tutorial](views.md) explains complete view requests and image outcomes.

Call `result_compare_curves` for aligned well or field curves.
Use `result_show_curve` to create a native plot and receive its fresh PNG observation.
Plot creation advances the project generation, so refresh result bindings before another view operation.
Keep the applied plot receipt if image capture or delivery fails.

## Save, reconnect, and cancel

Save the project through `project_save` with its current application context and an explicit path.
Keep each prepared-case receipt, well definition and trajectory, and result identifier with the public request record.
Before restarting the MCP server, terminate its owned application through `application_close` with `action: terminate`.
Reconnect to the same workspace, launch a new owned application, and reopen the saved project.

Inspect the project for current object references.
Use `model_restore_case` with the current project context, each exact model, and its prepared-case receipt.
Explicitly adopt the restored wells before editing or exporting them again.
Use `result_rebind` to verify the saved result cases and issue fresh view bindings.
Old object references remain stale across these native lifetimes.

Flow jobs retain their durable identities across an MCP server restart.
Poll the saved job reference after reconnecting.
To cancel an active owned run, call `job_cancel` and continue polling until termination is confirmed or the state becomes unknown.
An unknown state requires explicit investigation of the recorded job and runtime ownership.
The [job guide](../jobs.md) explains durable states and cancellation outcomes.
