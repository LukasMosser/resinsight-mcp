# Local MCP operations

The package exposes typed workspace operations through the MCP Python SDK.
MCP is the Model Context Protocol for tool access.
The transport uses local standard input and output.
Application output goes to standard error.

The supplied launcher manages durable workspace records and reads saved observations.
Application control and fresh rendering require explicitly supplied service implementations.
The launcher does not configure those services.

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

For new application code, generate identifiers with `SessionId.new()` from `resinsight_mcp.contracts.identifiers`.
Treat identifiers as opaque values.
Use `session_list` with `{}` to discover durable session records.
Use `session_get` with `session_id` to read one record.

Read the `resinsight://catalog` resource for available tools and their complete request and response schemas.
The resource and tool discovery use the same catalog.
Optional operations appear only when their service implementation was supplied.
No tool accepts arbitrary shell commands or Python code.

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
