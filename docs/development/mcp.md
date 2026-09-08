# MCP transport

P05 implements a local MCP transport over standard input and output.
It binds typed shared services without implementing application control, rendering, or simulation backends.
The [user guide](../mcp.md) describes the workspace launcher and tool outcomes.

The runtime uses `mcp>=1.28,<2`, `pillow>=12,<13`, and the existing Pydantic requirement.
The lockfile records tested versions.
The [official SDK v1 source](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) defines the supported protocol interfaces.

## Ownership and contract agreement

P05 owns `src/resinsight_mcp/mcp/` and its transport tests.
P04 owns the application session implementation.
The P04 owner reviewed the `SessionService` contract before P05 bound its operations.
That contract extends the existing `ProcessController` without changing its signatures.

The agreed optional `resinsight` extra contains rips and psutil for P04.
An extra selects optional runtime dependencies.
P04 provides that extra independently of the MCP runtime dependencies.
P05 does not import the optional ResInsight runtime.
Future simulator and model tools require their own package implementations and reviewed catalog additions.

## Public entry points

`Bindings` holds one required `WorkspaceStore` and optional `SessionService` and `Renderer` implementations.
These implementations retain ownership of engineering state.
`create_server(bindings)` creates an SDK `Server` with no application lifecycle changes.
`serve_stdio(bindings)` serves one dedicated process using the SDK stdio transport.

```python
import asyncio
from pathlib import Path

from resinsight_mcp.mcp import Bindings, serve_stdio
from resinsight_mcp.workspaces import SqliteWorkspaceStore

store = SqliteWorkspaceStore.open(Path("/absolute/path/workspace"))
asyncio.run(serve_stdio(Bindings(workspaces=store)))
```

To bind application operations, supply `sessions=service` with a `SessionService` implementation.
The [session implementation guide](sessions.md) describes the provided ResInsight service and native factory.
To bind fresh images, supply `renderer=renderer` with a `Renderer` implementation.
The caller must supply services that share the same workspace store.
This injection point does not establish external application behavior.

## One operation catalog

`catalog.py` owns tool names, descriptions, request types, result types, session lookup, and annotations.
It also owns the `resinsight://catalog` resource name.
Tool discovery and the catalog resource derive their schemas from those same records.
The catalog uses the shared request classes for application lifecycle and project operations.

The required workspace binding exposes session creation, listing, lookup, and saved observations.
A session service adds selection, connection inspection, application lifecycle, project operations, and object resolution.
A renderer adds `view_render` with an explicit session, view context, and requested image dimensions.
Operations appear only when their implementation was explicitly supplied.

`view_render` resolves the stored result before constructing the shared `RenderRequest`.
It rejects a context from another session or a report absent from that result.
The returned observation must match the requested context and dimensions.
The renderer remains responsible for fresh output and actual application context.
The transport does not claim that a visual edit changes simulator inputs.

The catalog has no shell, arbitrary Python, transport-selected session, or attached-process authorization tool.
`application_close` uses the shared detach default.
It cannot set the trusted `attached_termination_authorized` argument.
The session service retains responsibility for verified process ownership.

## Validation and stable failures

The SDK supplies parsing, initialization, discovery, dispatch, and transport behavior.
The server validates request JSON through Pydantic before calling a service.
JSON validation preserves shared enum, path, and tuple representations without relaxing strict Python construction.
Unknown fields and invalid identifier shapes fail before the service call.

The server disables the SDK's generic input-error conversion to preserve the shared error envelope.
It validates service results against each operation's declared response type.
Known `ContractError` records retain their code, message, and effect.
Unexpected service-call exceptions produce sanitized `execution_failed` responses and detailed stderr logs.
Unexpected image read or decode exceptions produce `render_failed` without exposing exception details.

Invalid requests use the existing `invalid_model` code.
An unavailable tool uses `unsupported_operation`.
An unavailable resource uses MCP invalid parameters with a `not_found` error record in its data.
Unexpected failures use effect `unknown` for mutations and `not_applied` for read operations.

## Protocol and engineering lifetimes

Each server owns protocol handlers and its immutable operation bindings.
It has no selected session, workspace cache, application ownership table, or recovery loop.
Synchronous service calls run in AnyIO worker threads.
Service implementations must serialize application mutations as their shared contracts require.

Closing a protocol connection does not call close, detach, cancel, or reconcile.
A new stdio process opens the same workspace without changing persisted job states.
Application continuity across processes depends on the session service lifecycle and explicit reconnection policy.
The maintained P05 fixture tests do not prove real ResInsight process survival.
The separate [P04 acceptance trial](p04-evidence.md) records two real applications that remained running after the SDK client and server exited.

The stdio runner reserves a separate output stream for the SDK.
It redirects ordinary process stdout to stderr while serving requests.
This includes Python output, native library output, and inherited child-process output.
The runner restores stdout when it exits.
Use this runner only in a dedicated stdio process because descriptor redirection affects the whole process.

## Native image responses

`content.py` preserves typed JSON in `TextContent` and `structuredContent`.
Successful observations append `ImageContent` with `image/png` and no visibility restriction.
Pillow decodes the stored image and checks its format and declared dimensions.
An empty, corrupt, mislabeled, missing, or mismatched image produces an explicit failure.

A successful `EditedView` preserves its applied edit receipt when image delivery fails.
The nested observation records the failure, and the outer operation remains successful.
No prior image replaces a failed observation.
The transport does not infer that a saved image represents the current application state.

## Maintained evidence

`tests/mcp/` uses real SDK clients and public workspace APIs.
Stdio tests launch independent Python server processes.
They exercise typed discovery, session isolation, reconnects, stable failures, native images, and stderr separation.
Image tests use supported Pillow decoding without byte or pixel comparisons.

Session binding tests use an explicit test service through the SDK in-memory transport.
They establish transport routing and lifecycle separation, not real application control.
The [P05 evidence record](mcp-evidence.md) records reviewed commands, versions, and image acceptance results.
