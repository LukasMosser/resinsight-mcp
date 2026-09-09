# Connect an agent

Connect an MCP-enabled client to discover and use the tools supplied by your host.
MCP is the Model Context Protocol for tool access.
The transport uses local standard input and output.
Application output goes to standard error.

The configured client can send prompts, tool results, metadata, and images to its model provider.
The product assumes that users have appropriate provider data sharing agreements.
The [data boundary](views.md#data-boundary) explains local tools and remote model inference.

The supplied launcher manages durable workspace records and reads saved observations.
Its optional ResInsight configuration enables application sessions and project operations.
Fresh rendering and local jobs require explicitly supplied service implementations.
With session and view services supplied, an agent can inspect project objects, apply view settings, and receive fresh native images.
The [view guide](views.md) describes that configured workflow and its trusted result setup.

## Discover your tools

Ask your agent to list the connected server's tools before starting an application task.
Read `resinsight://catalog` for their complete request and response schemas.
The resource and tool discovery use the same catalog.
Optional operations appear only when their required service was supplied.

The [tutorials](tutorials/index.md) identify the tools and configuration each task needs.
If a required tool is absent, stop that task and inspect the host configuration.
The [operation map](development/agent-workflows.md) explains which capabilities exist and which paths remain integration work.
No tool accepts arbitrary shell commands or Python code.

## Start a workspace server

Use Python 3.12 and the locked environment from the [setup guide](development/local-setup.md).
Choose an absolute workspace path whose parent directory already exists.

For a new workspace, run:

```console
uv run --locked python -m resinsight_mcp.mcp \
  --workspace-root /absolute/path/workspace --create-workspace
```

For an existing workspace, run:

```console
uv run --locked python -m resinsight_mcp.mcp \
  --workspace-root /absolute/path/workspace
```

The first command refuses to overwrite an existing workspace.
The second command refuses missing, corrupt, or unsupported workspaces.
Neither command reconciles jobs or changes application connections.
The server waits for an MCP client after startup.

Configure your local MCP client with the second command after creating the workspace once.
Use absolute executable and checkout paths when your client starts outside the repository.
The [SDK documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) describes client transport support.

## Enable ResInsight sessions

Install the optional native dependencies from the repository:

```console
uv sync --locked --extra resinsight
```

Choose an absolute log directory that already exists and is writable.
For an existing workspace, start the configured launcher:

```console
uv run --locked --extra resinsight python -m resinsight_mcp.mcp \
  --workspace-root /absolute/path/workspace \
  --resinsight-log-directory /absolute/path/application-logs
```

For a new workspace, add `--create-workspace` to this command.
The host requires `lsof` and the native dependencies described in the [session guide](sessions.md#requirements).
The launcher rejects unavailable dependencies or an invalid log directory before creating a workspace.
Startup failures appear on standard error and return exit status 2.

This configuration adds session selection, connection inspection, application lifecycle, project operations, and object resolution to the advertised tools.
Starting the server does not launch or attach ResInsight.
Use `application_launch` with an absolute executable path or `application_attach` with an explicit local endpoint.
Those operations verify the application version and process before returning a connection.
The [session tutorial](tutorials/sessions.md) shows the requests and recovery steps.

Launch output goes to separate files in the configured log directory.
The service uses its [default timeouts](development/sessions.md#configure-and-use-the-service).
Without `--resinsight-log-directory`, the launcher advertises workspace operations only.
View, job, and model tools are not part of this launcher configuration.
The [launcher evidence](development/launcher-evidence.md) records a clean installation and real ResInsight session trial.

## Use explicit sessions

An engineering session identifies a durable workspace record.
Its identity remains separate from each protocol connection.
Every request that targets a session includes its identifier, directly or within a typed application context.
Selecting a session never supplies a default for another operation.

The `session_create` request uses an explicit identifier and a name:

```json
{
  "session_id": "session_00000000000000000000000000000001",
  "name": "Example reservoir"
}
```

The example identifier illustrates the declared format.
For a new session, supply a new identifier that follows the discovered schema.
Treat identifiers as opaque values.
Use `session_list` with `{}` to discover durable session records.
Use `session_get` with `session_id` to read one record.

## Read outcomes and images

Every tool returns an `OperationResult` record in both text and structured content.
A successful outcome has `status: success` and a typed `value`.
A failed outcome has `status: failure` and a stable `error` record.
The response sets `isError` for a failed operation.

`observation_get` requires `session_id` and `observation_id`.
It returns saved observation metadata followed by native PNG image content.
Reading a saved observation does not capture a fresh frame.
The image must decode and match its declared dimensions.

A filename, resource link, or metadata record does not replace native image content.
Clients must retain each content item when presenting the result to a model.
The observation metadata records its model, result, view, camera, property, units, and capture time.

An applied edit can have a failed observation.
The encoder preserves its edit receipt and records the image failure separately.
That result remains a successful edit with no replacement image.
Do not repeat an applied edit because its observation failed.

Schema failures use `invalid_model` before the service operation runs.
Unavailable tools use `unsupported_operation`.
Known service failures retain their shared error code and mutation effect.
An unexpected mutation failure uses `execution_failed` with effect `unknown`.
Inspect the application log and current state before retrying that operation.

Disconnecting the client does not request application closure, project closure, job cancellation, or workspace recovery.
Reconnecting reads the same durable workspace when the client uses the same workspace path.
The [transport guide](development/mcp.md) explains service binding and acceptance evidence.
