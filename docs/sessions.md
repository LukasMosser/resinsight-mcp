# ResInsight sessions

An agent can manage named ResInsight sessions through a configured MCP connection.
MCP is the Model Context Protocol for tool access.
A session is a durable workspace identity.
An application connection identifies one running ResInsight instance.
Every change names its session explicitly, so selecting one does not redirect later changes.
The [session tutorial](tutorials/sessions.md) shows requests for project work and recovery.

## Requirements

Application operations require a configured session service.
Enable that service through the shipped launcher's [ResInsight configuration](mcp.md#enable-resinsight-sessions).
The optional `--resinsight-log-directory` argument supplies an existing, writable directory for application output.

Use a trusted local workspace and an absolute application executable path.
ResInsight must expose gRPC, its remote procedure call interface.
The application and `rips` package must have matching major and minor versions.
The host requires `lsof` to verify the application process at an explicit local endpoint.
The [platform record](development/platform-resinsight.md) identifies the tested macOS build.

## Create, save, and detach

Ask the agent to create a named session, launch ResInsight, inspect its project, save it, and detach.
The agent uses `session_create`, `application_launch`, `project_inspect`, `project_save`, and `application_close`.
It must retain returned session identifiers and project context for subsequent requests.
A context identifies the connection and observed project state.

Saving requires an absolute output path with an existing parent directory.
An existing file requires an explicit overwrite request.
`application_close` detaches by default and leaves the application running, including applications launched through MCP.

A failed launch can leave an application running.
Inspect the returned process and log details before requesting another launch.
The [developer example](development/sessions.md#configure-and-use-the-service) shows direct Python construction for host integrators.

## Find and attach sessions

`session_list` lists stored sessions, and `session_get` reads one by identifier.
`session_select` resolves a session without setting a default target.
`connection_list` and `connection_get` read connection records without probing application health.

`application_attach` connects a session to an explicit port on `127.0.0.1`.
Attachment verifies the listening process and application version.
It rejects a second binding to the same process within one controller process.
Separate controller processes do not share that protection.

Reopening a workspace preserves session identities but does not reconnect applications automatically.
A successful launch or attachment creates a new connection identifier.
Earlier object references cannot cross that connection boundary.

## Project operations

`project_inspect` returns current project context and references for observed cases, views, and wells.
`object_resolve` checks an issued reference against a fresh project observation.
Use these references instead of guessing native object numbers.

`project_open` opens an existing regular project file.
`project_save` saves the explicitly identified project.
`project_close` closes its project without terminating ResInsight.
Each completed command invalidates earlier object references, including after saving.
Use the returned context for the next request.

Observed external changes also invalidate references.
`last_saved_path` records the last successful service save for retained state, rather than the application's current filename.
A changed project state or new connection clears that path.
Saving does not create a workspace checkpoint or establish simulator input lineage.
The [checkpoint boundary](development/workspaces.md#project-checkpoints) explains those separate records.

## Errors and recovery

A competing operation returns `busy` without applying its change.
A remote timeout can also return `busy`, with an `unknown` effect for a mutation.
An unknown effect means that the operation's complete outcome is uncertain.
The service does not retry project commands automatically.

A lost connection or uncertain project mutation requires a new attachment.
Inspect the current project before deciding whether to repeat a change.
For `stale_object`, obtain current context or references through `project_inspect`.
A completed command followed by failed observation does not mean that the command was unapplied.

An explicit termination request through `application_close` requires verified service ownership.
Attached applications cannot receive termination authorization through this MCP request.
Their termination requires separate trusted operator handling.
Termination checks process identity and waits for confirmed exit.

## Detection limits

The service compares observed project roots and case, view, and well inventories.
It cannot detect every external edit, identical empty-project reopen, or native address reuse.
It does not prevent simultaneous changes through the application interface.
Use one controller for each application and avoid simultaneous manual project changes.
The [implementation guide](development/sessions.md) explains connection ownership and failure handling.
