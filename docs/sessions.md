# ResInsight sessions

`ResInsightSessionService` manages named workspaces and explicit ResInsight connections.
A session is a durable workspace identity.
A connection identifies one verified application connection and its current project generation.
Selecting a session does not set a default for later changes.
Every change names its session through the request or its application context.

## Requirements

Install the optional ResInsight dependencies from the repository:

```sh
uv sync --locked --extra resinsight
```

The adapter requires `lsof` to verify the process listening at an explicit local endpoint.
ResInsight must expose gRPC, its remote procedure call interface.
The application and `rips` package must have matching major and minor versions.
The optional dependency fixes `rips` at `2026.9.0.1`.
The [platform record](development/platform-resinsight.md) describes the custom application build on macOS 14.2.1.

Use a trusted local workspace and an absolute application executable path.
`RipsApplicationFactory` takes a log directory, a launch timeout, and a timeout for each remote call.
The default timeouts are 120 seconds for launch and 30 seconds for each remote call.
Both timeout values must be finite and positive.
Application output goes to separate launch log files.

## Create, save, and detach

This example creates a workspace, launches an application, saves its project, and detaches the connection.
Replace the three absolute paths with locations on your host.
The workspace path must not exist, and its parent directory must exist.
The project output directory must exist.
Detaching leaves the application running.

```python
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError, Failure, OperationResult
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.contracts.sessions import (
    CloseRequest,
    LaunchRequest,
    ProjectSaveRequest,
)
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.sessions.rips import RipsApplicationFactory
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def require[T](result: OperationResult[T]) -> T:
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


workspace_root = Path("/absolute/path/new-workspace")
executable = Path("/absolute/path/ResInsight.app/Contents/MacOS/ResInsight")
project_path = Path("/absolute/path/projects/example.rsp")
store = SqliteWorkspaceStore.create(workspace_root)
factory = RipsApplicationFactory(log_directory=workspace_root / "application-logs")
service = ResInsightSessionService(store, factory)
session = require(service.create_session(Session(session_id=SessionId.new(), name="Example")))
connection = require(
    service.launch(LaunchRequest(session_id=session.session_id, executable=executable))
)
project = require(service.inspect_project(session.session_id))
saved = require(
    service.save_project(ProjectSaveRequest(context=project.context, path=project_path))
)
require(
    service.close(
        CloseRequest(
            session_id=session.session_id,
            connection_id=connection.context.connection_id,
        )
    )
)
print(saved.last_saved_path)
```

Public service methods return `OperationResult` with either a successful value or a typed failure.
The example raises `ContractError` when an operation fails.
Request construction can instead raise a Pydantic validation error.
A launch failure can leave an application running, and its error reports the launched process and log location.
Inspect that outcome before launching again.

## Find and attach sessions

`list_sessions()` returns stored session records.
`select_session(session_id)` resolves one stored session without changing later request targets.
`list_connections()` returns runtime connection records, including lost or detached connections.
`get_connection(session_id)` returns the recorded connection for that session.
These connection lookups do not probe application health.

Use `AttachRequest(session_id=..., endpoint=Endpoint(port=...))` with `service.attach()` to connect to a running application.
`Endpoint` accepts only `127.0.0.1` and an explicit port.
Attachment verifies the listening process and the application version.
The service rejects a second binding to the same process within one Python interpreter.
Separate controller processes do not share that protection.

An application connection is runtime state, separate from the stored session.
Reopening the workspace preserves the session identity but does not reconnect an application automatically.
Every successful launch or attachment creates a new connection identifier.
Old object references cannot cross that connection boundary.

## Project operations

`inspect_project(session_id)` returns the current observed project context and service-issued object references.
`resolve_object(reference)` checks a reference against a fresh observation.
References identify observed cases, views, and wells.
They are separate from ResInsight object numbers and native addresses.

`open_project(ProjectOpenRequest(context=..., path=...))` opens an existing regular project file.
`save_project(ProjectSaveRequest(context=..., path=...))` saves to an absolute project path.
Saving rejects an existing file unless the request sets `overwrite=True`.
`close_project(ProjectCloseRequest(context=...))` closes the application project without terminating the application.
Each completed project command advances the project generation and invalidates earlier object references.

Use the returned context for the next project request.
An observed external change also advances the generation.
`ProjectState.last_saved_path` records only the last successful save through this service for its retained project state.
It does not report the application's current project filename.
A changed project state or a new connection clears that saved path.

The [workspace store](development/workspaces.md#project-checkpoints) can record project checkpoints separately.
Saving a project does not create a checkpoint or bind the file to a model revision automatically.
A saved project alone does not prove simulator input lineage.

## Errors and recovery

The service serializes operations within each application binding.
A competing operation returns `busy` without applying its change.
A remote call timeout also returns `busy`, but a timed-out mutation has an `unknown` effect.
An unknown effect means that the service cannot establish the complete outcome.
The service does not retry project commands automatically.

A lost connection or uncertain project mutation clears cached project state and marks the connection `lost`.
Attach a new connection before using that session again.
Inspect the current project before deciding whether to repeat a change.
A `stale_object` failure requires a current context or object reference.
A completed command followed by failed observation must not be treated as an unapplied command.

`close(CloseRequest(...))` detaches by default, including for applications launched by the service.
Set `action=CloseAction.TERMINATE` to request application termination.
For an attached application, trusted caller code must also supply `attached_termination_authorized=True` to `close()`.
That authorization is separate from the request record.
Termination verifies the current process lifetime and waits for confirmed exit.

## Detection limits

The service compares observed project roots and case, view, and well inventories.
It detects changes in the fields included in those observations.
It cannot detect every external edit, identical empty-project reopen, or native address reuse.
It does not lock out simultaneous changes through the application interface.
Use one controller for each application and avoid simultaneous manual project changes.
