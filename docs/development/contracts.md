# Shared contracts

The library provides validated records and typed interfaces introduced by P02 and extended for P03 workspace storage and P04 sessions.
A contract defines data or behavior shared between components.
[Pydantic](https://docs.pydantic.dev/latest/concepts/models/) validates records, while standard-library protocols describe component interfaces.
The runtime requirement is `pydantic>=2.13.5,<3`, with the installed version fixed by the lockfile.
Import records from their named `resinsight_mcp.contracts` modules.

The shared contracts do not import external application backends.
The [session service](sessions.md) implements ResInsight connections separately from these records.
The [architecture](architecture.md) describes component responsibilities.

## Component boundaries

The component protocols live in `resinsight_mcp.contracts.interfaces`.
A protocol describes methods required by a typed implementation.
P03 implements the workspace boundary through [SqliteWorkspaceStore](workspaces.md).
P04 implements application lifecycle and project operations through [ResInsightSessionService](sessions.md).

| Protocol | Main responsibility and operations |
| --- | --- |
| <code style="white-space: nowrap">ProcessController</code> | Launch, attach, and close application connections under trusted process ownership. |
| `SessionService` | Extend process control with durable session lookup, runtime connections, and explicit project operations. |
| `WorkspaceStore` | Store session records, revisions, artifacts, jobs, results, observations, and checkpoints, with explicit recovery. |
| `Renderer` | Render a fresh image with actual view context. |
| `ModelPreparer` | Prepare a fixed revision for the selected backend. |
| `JobController` | Submit jobs, poll execution state, and request cancellation. |
| `ResultImporter` | Load results with their exact engineering lineage. |

Operations return typed `OperationResult` records, except `open_artifact()`.
That method provides a binary stream through a context manager and raises `ContractError` for inaccessible artifacts.
A context manager controls resource entry and cleanup.
The workspace store preserves immutable revisions and rejects conflicting writes under an existing identity.
Protocol declarations do not enforce storage, process, or renderer behavior by themselves.

## Record validation

Public records reject unknown fields, nonfinite numbers, and unsupported coercion.
Record fields cannot be reassigned after validation.
The provided engineering and lifecycle records use immutable nested records and tuples.
Use a new validated record to represent a changed state.
Immutability does not provide a database, transaction, or persistent history.

Python construction uses the declared types, including enum members, date objects, and tuples.
JSON serialization uses their JSON representations.
The [serialization section](#serialization) explains that boundary.

## Identifiers

Each identifier type has a distinct prefix followed by 32 lowercase hexadecimal digits.
The `new()` class method creates a fresh UUID-based value of that type.
UUID means a universally unique identifier.
Identifiers serialize as strings and remain separate from external application object numbers.
Treat them as opaque values rather than extracting meaning from their digits.

| Type | Prefix | Record identified |
| --- | --- | --- |
| `SessionId` | `session_` | Engineering session. |
| `RevisionId` | `revision_` | Model revision. |
| `JobId` | `job_` | Execution job. |
| `ResultId` | `result_` | Simulator result. |
| `ObservationId` | `observation_` | Observation. |
| `ConnectionId` | `connection_` | Application connection. |
| `GridId` | `grid_` | Grid. |
| `ArtifactId` | `artifact_` | Stored artifact. |
| `EditId` | `edit_` | Applied edit. |
| `CheckpointId` | `checkpoint_` | Saved-project checkpoint. |

`ModelRef` pairs a session identifier with a revision identifier.
A shared reference identifies context without providing a storage implementation.

## Session and process ownership

`Session` identifies a durable engineering workspace independently of an MCP client or application process.
`ApplicationContext` adds a connection identifier and project generation to the session identifier.
`ObjectRef` identifies a case, view, or well within that context.
Its `require_current()` method rejects a different session, connection, or project generation with `stale_object`.
The session service observes current application state before accepting a service-issued object reference.

`Endpoint` requires the explicit localhost address `127.0.0.1` and a port from 1 through 65,535.
`LaunchRequest` requires an absolute executable path.
Neither record starts a process or probes a port.
`Connection` distinguishes owned processes from attached processes and requires a `ProcessIdentity` for owned connections.
That identity combines a process identifier with a host-derived start marker for one process lifetime.

Its states are `ready`, `busy`, `lost`, and `detached`.
A lost connection can become detached, while reconnection needs a new verified connection identity.

`CloseRequest` defaults to detaching.
`authorize_close()` checks the request against a trusted connection record.
Termination of an attached process requires explicit owner authorization supplied separately from the request.
Every termination requires `verified_process` to match the recorded identity and a connection that is not detached.
The application adapter must verify the process identity immediately before requesting termination.
Stored identity data alone does not prove current ownership or grant permission.

The helper returns an allowed action or raises `ContractError`.
It does not terminate a process or acquire authorization itself.

## Model and result lineage

`ModelInputs` requires unique input artifact identifiers and an entrypoint that belongs to those inputs.
`ModelRevision` combines those inputs with a model reference, unit system, and coordinate frame.
An optional parent must belong to the same session and cannot identify the revision itself.
Creating a new revision does not change its parent record.
Record construction does not verify that referenced artifacts or parent revisions exist.
The workspace store checks these relationships when saving a revision.

`PreparedModel` pairs a fixed revision with its selected backend.
`Backend` names `opm_flow` and `julia`, but those enum values do not establish available adapters.
`Result` retains its job identifier, exact model reference, grid, and report series.
Its numerical assessment defaults to `not_assessed` and can separately record `accepted` or `rejected`.
A successful process exit does not establish numerical acceptance.

`ResultImportRequest` requires a successful job and matching job, model, and session lineage.
`LoadedResult` requires a case reference in the result's session.
These checks validate recorded relationships without opening an external result file.

## Units and depth

`Quantity` requires a finite value, a unit, and its physical dimension.
A pressure unit cannot describe a length quantity.
The supported units are deliberately small:

| Dimension | Units |
| --- | --- |
| Length | `m`, `ft` |
| Pressure | `Pa`, `bar`, `psi` |
| Time | `s`, `day` |
| Dimensionless | `1` |

`UnitSystem` names `FIELD`, `METRIC`, and `SI` conventions.
A unit-system label does not convert values or replace an explicit quantity unit.
The library does not implement unit conversion.

`CoordinateFrame` identifies a local datum, length unit, and positive-up or positive-down depth direction.
A datum names the coordinate reference.
No depth sign is inferred from a field called Z.

`MeasuredDepthInterval` describes distance along a well from its measured-depth origin.
Its start must be nonnegative, and its end must exceed its start.
Its unit must describe length.
Measured depth is distinct from vertical depth, even when they agree for a vertical well.

The [P01 control record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/controls.md) illustrates why explicit depth conventions matter.
That experiment uses FIELD feet and verifies imported trajectory data against the intended cell column.
The shared types do not perform that external verification themselves.

## Cells and report times

`CellIndex` uses zero-based I, J, and K values.
`CellAddress` combines an index with a grid identifier.
`ActiveCellMap` records the model reference, grid dimensions, and ordered active cells.
Each cell must fit the grid and appear only once.
The tuple order defines the zero-based active-array index.
Do not assume that inactive cells occupy positions in that array.

`cell_at(active_index)` resolves the array index to a grid address.
Negative indices, boolean indices, and indices outside the mapping fail.
An adapter must explicitly translate external one-based cell addresses into this convention.
P02 does not implement that adapter.

`ReportTime` records a nonnegative report index, elapsed days, and a simulator calendar date.
The calendar date has no implied timezone.
`ReportSeries` requires at least one report.
Report indices and elapsed days must increase, while calendar dates cannot move backward.
Report indices may have gaps, and multiple reports may share a calendar date.

## Job states

`JobRequest` contains a prepared model and explicit CPU, memory, and wall-time limits.
All three limits must be positive.
`Job` keeps execution state separate from numerical assessment and cancellation intent.
Its transition helper accepts only these changes:

| Current state | Allowed next states |
| --- | --- |
| `queued` | `running`, `failed`, `canceled`, `unknown` |
| `running` | `succeeded`, `failed`, `canceled`, `unknown` |
| `unknown` | `running`, `succeeded`, `failed`, `canceled` |
| `succeeded`, `failed`, `canceled` | None |

A succeeded job requires a recorded zero exit code.
A failed job requires an error record.
A canceled job requires confirmation that no job process remains.
Active and unknown states cannot carry terminal exit, error, or termination evidence.
Unknown means that the execution outcome is unresolved, not that the job failed.
An interrupted launch can leave a queued job unknown before running was confirmed.

`request_cancel()` records intent and leaves the execution state unchanged.
It does not signal a process or promise that execution has stopped.
The caller must obtain execution evidence before invoking `transition()`.
Transition helpers produce a new validated record and preserve the original record.
They do not implement a job supervisor or enforce resource limits on a host.

## Observation context

`ViewContext` records the model, result, grid, case, view, and scene version.
It also records property units, report time, coordinate frame, camera, vertical exaggeration, legend bounds, and filters.
Case and view references must have the correct kinds and share an application context.
The model must belong to that session, and filters must name that grid.

`RenderRequest` includes the stored `Result` and checks the requested context against it.
`ViewContext.require_result()` checks the model, result identifier, grid, and report time.
The workspace store repeats this check against its stored result before saving an observation.
It also requires an existing image artifact, without claiming decoded image validity.

A camera needs a nonzero viewing direction and a nonparallel up vector.
Perspective projection requires a field of view between 0 and 180 degrees.
Orthographic projection instead requires a positive parallel scale.
Legend bounds use the property's unit and must increase.
Cell filters use the same zero-based convention as grid addresses.

`ImageArtifact` declares PNG metadata with positive dimensions and an artifact reference.
It does not contain image data or verify an existing file.
`Observation` combines that artifact with the captured context and a timezone-aware UTC timestamp.
The image artifact must belong to the observation's session.
The renderer must decode fresh output and verify its actual context before reporting success.
P02 does not perform that external rendering or native MCP delivery.

## Applied edits and failed observations

`PerforationEditRequest` identifies a well, model context, measured-depth interval, and expected scene version.
A visual well edit does not create or change a simulator input revision.
`EditReceipt` records an applied edit and requires its scene version to advance.
`EditedView` pairs that receipt with a separate observation outcome.
A successful observation must match the edited model, application context, and resulting scene version.

The example below represents an already applied edit followed by a failed render.
Constructing these records does not execute either operation.
The failure contains no previous image, and the applied receipt survives JSON serialization.
A client must not repeat the successful edit because its observation failed.

```python
from resinsight_mcp.contracts.engineering import MeasuredDepthInterval, ModelRef, Unit
from resinsight_mcp.contracts.errors import Error, ErrorCode, Failure, OperationResult
from resinsight_mcp.contracts.identifiers import ConnectionId, EditId, RevisionId, SessionId
from resinsight_mcp.contracts.observations import (
    EditedView,
    EditReceipt,
    Observation,
    PerforationEditRequest,
)
from resinsight_mcp.contracts.sessions import ApplicationContext, ObjectKind, ObjectRef

session_id = SessionId.new()
model = ModelRef(session_id=session_id, revision_id=RevisionId.new())
context = ApplicationContext(
    session_id=session_id,
    connection_id=ConnectionId.new(),
    project_generation=0,
)
request = PerforationEditRequest(
    model=model,
    well=ObjectRef(context=context, kind=ObjectKind.WELL, object_id="P01IMPORT"),
    interval=MeasuredDepthInterval(start=8326.0, end=8424.0, unit=Unit.FOOT),
    expected_scene_version=7,
)
response = EditedView(
    edit=EditReceipt(edit_id=EditId.new(), request=request, scene_version=8),
    observation=OperationResult[Observation](
        outcome=Failure(
            error=Error(code=ErrorCode.RENDER_FAILED, message="The new frame was not produced.")
        )
    ),
)
restored = EditedView.model_validate_json(response.model_dump_json())
print(restored.edit.effect, restored.observation.outcome.status)
```

The output is `applied failure`.
The edit receipt identifies the applied change, while the error describes the failed observation operation.

## Typed errors

`Error` carries a stable `ErrorCode`, a nonblank message, and a mutation effect.
A code identifies the kind of failure without requiring clients to parse its message.

The following examples define the five required operational distinctions.
They describe error records, without claiming a working external adapter.

| Code | Example condition and message | Mutation effect |
| --- | --- | --- |
| `busy` | Another view operation is active. Wait for the application to become ready. | `not_applied` |
| `lost_connection` | The connection was lost before the well edit was acknowledged. Inspect current state before retrying. | `unknown` |
| `stale_object` | The case belongs to an earlier project generation. Obtain a current case reference. | `not_applied` |
| `invalid_model` | The result names another input revision. Select a result from the requested revision. | `not_applied` |
| `unsupported_operation` | The selected backend cannot perform this requested operation. | `not_applied` |

Other codes cover `invalid_transition`, `render_failed`, `not_found`, and `execution_failed`.

`MutationEffect.NOT_APPLIED` states that the failed operation did not apply its change.
`MutationEffect.UNKNOWN` preserves uncertainty about whether a change occurred.
An unknown effect does not authorize a retry or imply rollback.
A runtime implementation must resolve that uncertainty before repeating a state change.

`ContractError` exposes its serializable `Error` through the `error` attribute.
Record validation failures instead use Pydantic's validation errors.
`OperationResult[T]` contains either `Success[T]` or `Failure` under `outcome`.
Their `status` values distinguish `success` from `failure` during JSON validation.
Use validated records or other immutable values as generic result payloads.

## Serialization

Pydantic provides `model_dump_json()` and `model_validate_json()` for record round trips.
The JSON representation carries explicit enum values and identifier strings.
Validation still applies when loading JSON.
A JSON record does not establish that a referenced external object still exists.

## Workspace contract additions

P03 extends the shared workspace interface and implements persistent storage through [SqliteWorkspaceStore](workspaces.md).
`Artifact` associates an opaque file identity with its kind and relative model filename.
The filename must not contain absolute paths, dot segments, or platform-specific separators.
`ProjectCheckpoint` binds a supplied saved-project artifact to an exact model revision.
It does not prove that an external application saved matching project contents.

`WorkspaceStore` adds artifact writes, enumeration, revision cloning, checkpoints, and explicit recovery.
Clones remain within one session and preserve the source as their parent.
`JobRef` pairs a session identifier with a job identifier for lookup.
Changing a stored job requires its expected prior record, so competing updates can fail visibly.
An equal retry returns the existing record without another change.

Opening a workspace must not reconcile jobs automatically.
The caller must stop its job controller before requesting recovery for selected job snapshots.

Workspace errors include `conflict`, `invalid_path`, `storage_failed`, `corrupt_workspace`, and `unsupported_schema`.
The existing `busy` code also covers database lock timeouts.
The [workspace error table](workspaces.md#errors) explains their conditions and mutation effects.
`RecoveryReport` identifies reconciled jobs, removed orphan artifacts, and unavailable committed artifacts.
An orphan artifact is a file without a committed record.
Recovery must not infer process termination or replace missing data.

## Session service additions

P04 adds `SessionService`, which extends `ProcessController` without duplicating lifecycle request records.
Its session operations create, list, and resolve durable workspace identities.
Connection operations list and retrieve runtime records separately from those workspace identities.
`select_session()` does not provide a default session for later mutations.
Closing with `CloseAction.DETACH` supplies the explicit detach operation.

`ProjectState` contains an `ApplicationContext`, observed `ProjectObject` records, and an optional `last_saved_path`.
Every project object must share the project context, and object references must be unique.
The saved path must be absolute and describes only a successful service save for the retained state.
It does not identify the application's current project filename.

`ProjectOpenRequest` and `ProjectSaveRequest` require the expected application context and an absolute path.
Saving defaults to `overwrite=False`.
`ProjectCloseRequest` requires the expected context without a file path.
Project operations reject stale contexts, while inspection and object resolution observe application state.

Service project commands and detected observation changes advance the project generation.
New connections invalidate references through their new connection identifier.
The [session implementation guide](sessions.md#project-observations) defines observable fields and the limits of external change detection.
These runtime operations do not automatically create workspace checkpoints or prove model revision lineage.
