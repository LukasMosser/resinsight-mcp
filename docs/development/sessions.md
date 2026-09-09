# Session implementation

P04 implements `ResInsightSessionService` against the shared `SessionService` protocol.
The [user guide](../sessions.md) describes current agent operations and outcomes.
The service coordinates durable workspace records, verified application connections, project commands, and object reference validation.
It does not provide an MCP transport or change simulator input revisions.

## Configure and use the service

The shipped launcher configures workspace operations only.
A host must supply `Bindings.sessions` with this service to expose application and project operations.
The [MCP guide](mcp.md) describes transport bindings.

Install the optional ResInsight dependencies from the repository:

```sh
uv sync --locked --extra resinsight
```

The adapter requires `lsof` to verify the process listening at an explicit local endpoint.
ResInsight must expose gRPC, its remote procedure call interface.
The application and `rips` package must have matching major and minor versions.
The optional dependency fixes `rips` at `2026.9.0.1`.
The [platform record](platform-resinsight.md) describes the custom application build on macOS 14.2.1.

Use a trusted local workspace and an absolute application executable path.
`RipsApplicationFactory` takes a log directory, a launch timeout, and a timeout for each remote call.
The default timeouts are 120 seconds for launch and 30 seconds for each remote call.
Both timeout values must be finite and positive.
Application output goes to separate launch log files.

## Create, save, and detach

This example creates a workspace, launches an application, saves its project, and detaches the connection.
Replace the absolute paths with locations on your host.
The workspace path must not exist, and its parent directory must exist.
The project output directory must exist.
Detaching leaves the application running.

```python
from pathlib import Path

from resinsight_mcp.contracts.errors import (
    ContractError,
    Failure,
    OperationResult,
)
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
app_root = Path("/absolute/path/ResInsight.app")
executable = app_root / "Contents/MacOS/ResInsight"
project_path = Path("/absolute/path/projects/example.rsp")
store = SqliteWorkspaceStore.create(workspace_root)
factory = RipsApplicationFactory(
    log_directory=workspace_root / "application-logs",
)
service = ResInsightSessionService(store, factory)
record = Session(session_id=SessionId.new(), name="Example")
session = require(service.create_session(record))
launch_request = LaunchRequest(
    session_id=session.session_id,
    executable=executable,
)
connection = require(service.launch(launch_request))
project = require(service.inspect_project(session.session_id))
save_request = ProjectSaveRequest(
    context=project.context,
    path=project_path,
)
saved = require(service.save_project(save_request))
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

## Ownership and boundaries

`service.py` owns session coordination and application context generations.
`_backend.py` defines the internal `Application` and `ApplicationFactory` protocols.
`rips.py` implements remote calls and host process verification.
Importing the service alone does not import the optional native backend.
The shared contracts remain independent of `rips` and `psutil`.

`WorkspaceStore` owns durable session records.
The service owns runtime connections, locks, observed project state, and service-issued references.
Protocol clients do not own application lifetimes.
Selecting a session resolves its record without setting an implicit mutation target.
Creating another service does not restore runtime connections from stored workspace records.

The process identity combines a process identifier and its start marker.
The adapter checks the listening endpoint through `lsof` and verifies process lifetime through `psutil`.
Attachment uses an explicit localhost endpoint without scanning for another application.
The application and `rips` major and minor versions must match.
Launch records application output in a separate log and uses the application's reported port.
Each launched application has its own process group, separate from the MCP server process group.

## Serialization and reconnects

A session lock rejects overlapping operations with `busy`.
The service also reserves each application process within the Python interpreter.
A second service cannot bind that reserved process until its binding is released.
Separate controller processes do not share these reservations or locks.
The reservation does not prevent a human from editing the application.

Each successful attachment or launch receives a new `ConnectionId`.
Its `ApplicationContext` combines the durable session identifier, connection identifier, and project generation.
A lost connection cannot become ready without a new verified connection identity.
Detachment releases the client channel and preserves the application process.
Default close behavior also detaches an owned application.

Termination checks request identity and trusted ownership before contacting the application.
An attached application requires `attached_termination_authorized=True` through trusted caller code.
The adapter verifies process lifetime before requesting exit and waits for exit confirmation.
The service retires the connection before channel cleanup, preserving detachment if cleanup fails.

## Project observations

`ProjectSnapshot` contains the native project root address and a sorted object inventory.
Case observations include the native address, name, case identifier, and file path.
View observations include the native address and view identifier.
Well observations include the native address and name.
Native names can be empty, and the service preserves them.
The adapter obtains these fields through supported `rips` interfaces.

The service compares each observation with its previous snapshot.
An observed difference advances the project generation and replaces all service-issued object references.
Every completed service open, save, or close command also advances the generation, even when the observed inventory remains equal.
`resolve_object()` observes the application before accepting a reference.
References must match both the current context and an object issued for that context.

These observations do not provide a complete external event history.
Native pointer reuse, identical empty-project reopening, and changes to unobserved fields can remain undetected.
Multiple remote calls collect a snapshot without an atomic lock against application interface edits.
Documentation and acceptance records must distinguish observed changes from complete change detection.
The P04 implementation does not claim complete detection of arbitrary external project changes.

`last_saved_path` records the service's successful save destination for retained project state.
It is not a query of the native project filename.
A changed observation, project replacement, or reconnection clears the field.
A successful save sets it after the application command and output file check succeed.
Workspace checkpoints remain separate records and do not receive automatic model revision bindings.

## Failure semantics

Lock contention returns `busy` with `not_applied` effect.
Remote call deadlines bound individual calls and do not trigger automatic command retries.
A mutation timeout can return `busy` with `unknown` effect because the application may have applied the command.
A lost connection or uncertain project mutation marks the connection lost and clears its cached project state.
The caller must attach again and inspect current state before deciding whether another change is valid.

A completed project command can still fail during its following observation or saved-file check.
Those failures preserve uncertainty instead of claiming rollback.
A launch failure can leave a process running and reports available process and log details.
A successful save requires an accessible output file but does not establish its model lineage.
No saved project is substituted after a failed command.

## Evidence and review

Session tests exercise public behavior through an independent application boundary.
Relevant cases include explicit session targets, duplicate bindings, competing operations, reconnects, stale references, and uncertain mutations.
Backend tests exercise remote failure mapping, process identity checks, launch behavior, and project observations.
Those isolated tests do not establish real application acceptance.

The [P04 evidence record](https://github.com/LukasMosser/resinsight-mcp/blob/main/docs/development/p04-evidence.md) records tested commits, commands, versions, and acceptance results.
Real acceptance requires two applications with separate projects, save and reopen behavior, and surviving applications after client disconnect.
The evidence must also distinguish detected external changes from the observation limits described above.
Review includes duplicate behavior, state ownership, interface complexity, and truthful mutation outcomes.
