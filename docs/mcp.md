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
Its optional model configuration enables FIELD input import, creation, inspection, preparation, and cloning.
Its OPM workflow configuration adds native wells, schedule publication, bounded Flow jobs, result queries, and fresh native images.
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

## Author general models

Add `--enable-general-models` to expose geological arrays, native wells, schedules, regional physics, and input compilation.
Read `general_capabilities` for supported formats, physics, and local resource budgets.
These tools have no total cell, well, or report-count ceiling.
ResInsight, OPM, supported formats, and available resources still constrain an operation.

Use `general_simulation_define` to assemble compatible geometry, physics, schedules, and native connection exports.
Use `general_simulation_prepare` to compile inputs and validate them with OPM 2025.10.
The `imports` package extra supplies the supported parser.
The result contains file references, source identities, validated counts, and measured resource usage.
Use `general_simulation_prepared` to recover that receipt after reconnecting.

Preparation does not execute a simulation.
General prepared receipts cannot enter the legacy SPE1 execution path.
The [compiler guide](development/general-input-compilation.md) describes explicit choices, unit handling, validation, and resource configuration.
The [native evidence](development/evidence/general-compilation/README.md) records tested geometry and connection limitations.

## Start a workspace server

Use Python 3.12 and the locked environment from the [setup guide](development/local-setup.md).
For fixed mode, choose an absolute workspace path whose parent directory already exists.
For managed mode, choose an absolute parent path that the launcher can create.

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

To keep one MCP connection while working with several workspaces, start the managed launcher:

```console
uv run --locked python -m resinsight_mcp.mcp \
  --workspaces-root /absolute/path/workspaces
```

The launcher creates the managed root when it does not exist.
It does not select a workspace during startup.
Use `workspace_list` to inspect available workspaces.
Use `workspace_create` with `{"name": "case-a"}` to create one.
Use `workspace_select` with `{"name": "case-a"}` before calling workspace-scoped tools.
The selected workspace remains active until the client selects another one or disconnects.
The selection is not persisted, so reconnecting requires another `workspace_select` call.
The server keeps each selected workspace runtime separate within one connection.
The managed launcher does not accept `--create-workspace`.
Pass the optional model, native session, or OPM workflow flags with `--workspaces-root` when needed.
Their dependency checks run when a workspace is first selected.

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
Without a native log directory or model configuration, the launcher advertises workspace operations only.
The [OPM workflow configuration](#enable-the-opm-workflow) supplies the view, job, well, and result services together.
The [launcher evidence](development/launcher-evidence.md) records a clean installation and real ResInsight session trial.

## Enable model tools

Install the pinned parser with `uv sync --locked --extra imports`.
For an existing workspace, start the model configuration:

```console
uv run --locked --extra imports python -m resinsight_mcp.mcp \
  --workspace-root /absolute/path/workspace --enable-models
```

For a new workspace, add `--create-workspace`.
The launcher verifies `opm==2025.10` and its required parser interfaces before opening workspace storage.
This configuration does not require ResInsight or Docker.
To combine model and session tools, supply both documented configurations and their optional dependencies.

The configuration adds `model_import`, `model_get`, `model_inspect`, `model_prepare`, `model_clone`, `model_template`, and `model_create`.
Import and creation require an existing session and an explicit local depth datum.
All model operations retain the exact stored revision identity.
Preparation validates inputs without running a simulator.
The [model tutorial](tutorials/models.md) explains the public workflow and returned records.

## Enable the OPM workflow

Use an installed Python 3.12 environment with the application, OPM readers, and the matching generated RIPS wheel.
The published RIPS wheel does not contain the required native commands.
The [native client guide](development/wells.md#matching-generated-client) describes the supported wheel installation and source records.
The selected ResInsight build must include the reviewed prepared-grid, well, and view commands.
It also requires the [reviewed native build](development/evidence/p12/native/README.md#native-rendering-build) with the summary rendering and cell containment repairs.

The runtime requires the local pinned Flow image on `linux/arm64` and an available Docker daemon.
The [OPM guide](opm.md) records the exact digest, Flow version, limits, and dependency checks.
The launcher checks the local image without pulling it or starting a container.
It checks the generated client interfaces and parser before opening workspace storage.
An invalid runtime or incomplete client returns exit status 2 without creating a workspace.

Choose an existing writable application log directory and an absolute workspace path.
Start the installed interpreter directly:

```console
/absolute/path/environment/bin/python -m resinsight_mcp.mcp \
  --workspace-root /absolute/path/workspace \
  --resinsight-log-directory /absolute/path/application-logs \
  --enable-opm-workflow \
  --docker-executable /Applications/Docker.app/Contents/Resources/bin/docker
```

For a new workspace, add `--create-workspace`.
The Docker option requires the OPM workflow configuration and an absolute executable path.
Omitting that option selects the documented Docker Desktop path.
This configuration includes all model and session tools without requiring `--enable-models`.
Startup does not launch ResInsight or Flow.

| Task | Public tools |
| --- | --- |
| Prepare native cases | `model_load_case`, `model_restore_case` |
| Create and inspect wells | `well_create`, `well_update`, `well_inspect`, `well_adopt` |
| Publish native connections | `well_export`, `well_export_get`, `model_publish_schedule` |
| Run and assess Flow | `job_submit`, `job_poll`, `job_cancel`, `opm_collect` |
| Load and restore results | `result_get`, `result_load`, `result_rebind` |
| Query and compare values | `result_cell_property`, `result_curve`, `result_compare_cells`, `result_compare_curves` |
| Find views and capture native images | `view_list`, `view_apply`, `view_render`, `result_show_curve` |

The [workflow tutorial](tutorials/opm.md) explains the ordered public operations and their identity checks.

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
`result_show_curve` follows this rule through `EditedSummaryPlot`.
Its applied receipt retains the complete curve and current native plot context, even if image delivery fails.

Schema failures use `invalid_model` before the service operation runs.
Unavailable tools use `unsupported_operation`.
Known service failures retain their shared error code and mutation effect.
An unexpected mutation failure uses `execution_failed` with effect `unknown`.
Inspect the application log and current state before retrying that operation.

Disconnecting the client does not request application closure, project closure, job cancellation, or workspace recovery.
Reconnecting reads the same durable workspace when the client uses the same workspace path.
Native process ownership remains with the session service that launched the application.
Before restarting that server, save the project and terminate its owned application through `application_close` with `action: terminate`.
After reconnecting, launch a new owned application, open the saved project, and explicitly restore its case and result bindings.
Flow jobs continue under their independent supervisors across this server restart.
The [transport guide](development/mcp.md) explains service binding and acceptance evidence.
