# Find a session and reopen its project

This tutorial uses a configured session service and compatible ResInsight application.
A session is a named, durable workspace identity.
A connection identifies one verified application connection.
See the [session setup](../sessions.md) and [host integration](../development/mcp.md) requirements before starting.

## Find the target session

Ask your agent:

> Find my session named Reservoir review.
> Inspect its connection and project before changing anything.

Call `session_list` with `{}`.
Select the matching record by name and retain its `session_id`.
If names repeat, use the project context to distinguish the intended session.
Do not infer an identifier from a session name.

These templates use `<SESSION_ID>` for the exact identifier returned by `session_list`.
Replace every angle-bracket placeholder before sending a request.

```text
session_get({"session_id": "<SESSION_ID>"})
session_select({"session_id": "<SESSION_ID>"})
connection_get({"session_id": "<SESSION_ID>"})
project_inspect({"session_id": "<SESSION_ID>"})
```

`session_select` resolves the session without setting a default for later requests.
Every later request must still identify its session.
`connection_get` reads the recorded connection without probing application health.
`project_inspect` observes the project and returns its current context and object references.

For a new session, supply a fresh identifier that follows the discovered schema.
The [identifier guide](../mcp.md#use-explicit-sessions) describes the required format.
Then call this template:

```text
session_create({"session_id": "<NEW_SESSION_ID>", "name": "Reservoir review"})
```

Creating a workspace session does not launch an application.

## Launch or attach

Ask your agent:

> Launch ResInsight for this session using the configured executable.

The executable must be an absolute path supplied for this host.
Use `application_launch` with this template:

```text
application_launch({"session_id": "<SESSION_ID>", "executable": "<ABSOLUTE_EXECUTABLE_PATH>"})
```

A successful response records an owned connection and its endpoint.
If launch fails, inspect its process and log details before trying again.
A failed launch can leave an application running.

For an existing application, ask:

> Attach this session to the ResInsight endpoint supplied by the host operator.

Use the operator's current port instead of a guessed or historical port.
The following template uses `<PORT>` as an integer placeholder:

```text
application_attach({"session_id": "<SESSION_ID>", "endpoint": {"host": "127.0.0.1", "port": <PORT>}})
```

Attachment verifies the local listening process and application version.
The resulting connection has attached ownership.
The service rejects duplicate process bindings within one controller interpreter.
Use one controller for each application.

## Open, save, and reopen

Ask your agent:

> Open the project at the supplied absolute path.
> Save a copy to the supplied output path, then reopen that copy.

Call `project_inspect` first.
In these templates, `CURRENT_CONTEXT` means the complete object from the latest successful project's `context` field.
It contains `session_id`, `connection_id`, and `project_generation`.
It is an object placeholder, not a quoted string or an MCP parameter name.

```text
project_open({"context": CURRENT_CONTEXT, "path": "<ABSOLUTE_INPUT_PROJECT_PATH>"})
project_save({"context": CURRENT_CONTEXT, "path": "<ABSOLUTE_OUTPUT_PROJECT_PATH>", "overwrite": false})
project_close({"context": CURRENT_CONTEXT})
project_open({"context": CURRENT_CONTEXT, "path": "<ABSOLUTE_OUTPUT_PROJECT_PATH>"})
```

After each successful command, replace `CURRENT_CONTEXT` with that response's context before continuing.
The input project must be an existing regular file.
The output directory must exist.
An existing output file requires an explicit `overwrite: true` request.

Each completed project command advances the project generation and invalidates earlier references.
The save response records `last_saved_path`.
That field records a service save, not the application's current filename.
Opening another project clears it.
Saving does not create a workspace checkpoint or simulator revision.

The [P04 event record](../development/evidence/p04/events.jsonl) preserves two separate projects saved and reopened at generation `2`.
These are native service acceptance records, not a complete MCP transcript for this tutorial.
The [P06 exchange](../development/evidence/p06/observer/server-responses.jsonl) separately verifies `project_inspect` through production MCP.

## Select current cases, views, and wells

Ask your agent:

> List the project's cases, views, and wells.
> Resolve the case and view I name before using them.

Read `objects` from `project_inspect`.
Each item contains a display `name` and a complete `ref` object.
Select by name and `ref.kind`, then retain the complete reference.
The kinds are `case`, `view`, and `well`.

Call `object_resolve` with the reference itself as arguments:

```text
object_resolve(CURRENT_OBJECT_REF)
```

`CURRENT_OBJECT_REF` is the chosen item's complete `ref` object.
It contains `context`, `kind`, and `object_id`.
Do not wrap it inside a `ref` field.
Service references are not native ResInsight object numbers.
Resolving a reference checks identity without changing the graphical selection.

## Recover or detach

If `stale_object` occurs, inspect the project again and select fresh references.
Do not change only the generation number inside an old reference.
A new attachment creates a new connection identifier and invalidates prior references.
View work also requires the host to restore trusted result bindings after reconnection.

If a mutation reports effect `unknown`, inspect logs and current state before repeating it.
A lost connection requires a new attachment before further project work.
A completed command with failed observation must not be repeated as though it never happened.
The [session recovery guide](../sessions.md) explains these boundaries.

To leave ResInsight running, ask:

> Detach this session from ResInsight.

Obtain `connection_id` from the current `connection_get` response, then use this template:

```text
application_close({"session_id": "<SESSION_ID>", "connection_id": "<CONNECTION_ID>", "action": "detach"})
```

Termination requires verified ownership.
The MCP request cannot grant the separate trusted authorization required to terminate an attached application.
Client disconnection alone does not close the application or project.
