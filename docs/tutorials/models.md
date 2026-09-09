# Create and prepare model inputs

This workflow uses the shipped launcher with `--enable-models` and the pinned OPM parser.
The [connection guide](../mcp.md#enable-model-tools) provides the installation and startup commands.
ResInsight and Docker are not required for these input operations.
FIELD specifies feet, absolute pressure in psi, and field surface volumes.
The [model guide](../synthetic-models.md) describes the supported layered template and physics limits.

## Discover and select a session

Ask your agent:

> Read the tool catalog and list the durable sessions.
> Create a named session for this model if it does not exist.
> Keep its identifier explicit in every model request.

`session_list` and `session_create` manage durable records.
They do not connect to an application or select a default target for model operations.

## Create a layered model

Use `model_template` with `{}` to read the tested specification.
The returned `outcome.value` contains the complete specification for `model_create`.
The reference has 300 active cells, three layers, one injector, one producer, and two daily report intervals.
Review the well controls, dimensions, properties, and local datum before creating inputs.

Ask your agent:

> Read the model template and explain its layers, wells, controls, and units.
> Create that specification in the selected session with the local datum I supplied.
> Report the returned model revision and preparation summary.

`model_create` requires `session_id`, `datum`, and `specification`.
Its receipt contains `imported.prepared.revision`, the parsed summary, the specification artifact, and the active-cell mapping.
The service stores validated inputs and does not run a simulator.

## Import an existing model

`model_import` requires `session_id`, an absolute `source_root`, a relative `entrypoint`, and an explicit `datum`.
The source directory and included files must satisfy the [import limits](../development/model-imports.md#source-and-resource-limits).
The supported profile is `spe1-field-v2`.
Unsupported units, keywords, physics, paths, or controls fail before model publication.

Ask your agent:

> Import the model from my named source directory and entrypoint into the selected session.
> Use the local depth datum I supplied and show the parsed support summary.

## Inspect, clone, and prepare

Use `model_get` with the returned `ModelRef` to read its fixed revision record.
Use `model_inspect` with that reference to reparse stored geometry, properties, wells, and report times.
Both requests contain `session_id` and `revision_id`.

`model_clone` takes `source` and a new `revision_id`.
It publishes a child revision that retains the parent's input artifacts.
The parent remains fixed, and cloning alone does not change controls or geometry.

`model_prepare` takes the complete stored `revision` and `backend: "opm_flow"`.
It rejects a modified revision record or unsupported backend.
Its returned `PreparedModel` confirms input validation without claiming successful simulation.

After reconnecting, use `model_get` to recover the same revision identities.
The workspace preserves models independently of the MCP connection.
Read each operation's outcome before continuing after a failure.
