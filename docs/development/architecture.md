# Architecture

The repository implements shared contracts, workspace storage, and ResInsight session and project operations as a Python library.
The [contract guide](contracts.md) defines their current behavior and conventions.
Its seven protocols cover sessions, process control, workspace storage, rendering, model preparation, jobs, and result import.
The [workspace guide](workspaces.md) describes the implemented SQLite record store and immutable artifact files.

The [session guide](sessions.md) describes the implemented lifecycle service and native adapter.
The [MCP transport](mcp.md) binds shared services through typed operations and preserves native image content.
The [job controller](jobs.md) supervises trusted commands through durable records and owned process groups.
Rendering and simulator adapters remain separate work packages.

The [scope review](scope-review.md) records external evidence and open questions.
The [P05 record](mcp-evidence.md) proves blind synthetic-image delivery through the production transport.

## Responsibilities

An adapter translates between the service and an external system.
The proposed service coordinates application sessions, model revisions, simulation runs, and observations.
The simulator performs the numerical calculation.

The workspace store already preserves engineering sessions, model revisions, artifacts, and run-related records.
It does not control application processes or parse simulator inputs.
Job supervision uses that store for submissions, process identities, state history, and immutable logs.
Recovery requires stopped supervisors and never signals a process from a saved identifier.

The session service already controls application connections, ownership, project operations, and object reference validity.
Its observed change detection has explicit [limits](sessions.md#project-observations).
The remaining runtime responsibilities are:

- A view adapter obtains fresh rendered observations.
- A simulator adapter prepares, starts, and monitors runs.

A backend is the simulator selected for a run.
The service must report unsupported backend capabilities before submission.
It must never silently switch backends or drop unsupported model features.

## Session identity and ownership

A session identifies one durable engineering workspace.
An MCP connection, an application process, and a simulation run have separate identities.
A disconnected client must not erase the run record.

Every operation that changes state must include an explicit `session_id`.
A selected session provides convenience without replacing that requirement.
The service must resolve the identifier to a known application connection.

The session record must distinguish an attached process from a service-owned process.
Closing an attached session must detach without terminating the user's application.
Process termination requires explicit ownership and an authorized operation.

The service must serialize changes within an application instance.
Opening another project must invalidate identifiers from the previous project.
A busy application must remain distinguishable from a terminated process.

## Models and run history

A model revision is an immutable record of simulation inputs.
Each run must reference exactly one model revision.
A later edit creates a new revision and must not change an earlier run's inputs.

Run records must retain this evidence:

- Immutable input file identities.
- Model revision and selected backend.
- Simulator version and launch arguments.
- Resource limits and execution environment.
- Logs, exit status, and output file identities.
- Reported simulation time and numerical acceptance results.

Lineage links an output to its inputs and transformations.
The service must preserve model and run lineage when it loads results into ResInsight.
A successful process exit must remain separate from acceptance of the numerical result.

## Engineering data

An active-cell mapping links grid cells to simulator array entries.
Model conversion must define this mapping and preserve it through result import.
Visual alignment alone does not establish a correct mapping.

Every supported conversion must define these properties:

- Units for physical quantities.
- Coordinate axes and the sign of depth.
- Grid cell identifiers and active-cell mappings.
- Well identities, connections, and depth intervals.
- Phase meanings and report times.
- Supported controls and physical assumptions.

A visible well trajectory does not establish valid simulation inputs.
Acceptance must connect the intended well to exported connections, controls, and numerical results.
Unsupported conversions must fail with an explanation of the missing capability.

## Native image observations

A native image is an MCP content item with `type: image`.
The MCP encoder includes native image content and its media type.
A filename or image URL in ordinary text does not satisfy this contract.

Each observation must identify its engineering context:

- Session, model revision, case, view, and frame identifiers.
- Property, units, and report time.
- Camera, projection, and vertical exaggeration.
- Filters and legend limits.
- Image dimensions and media type.

The service must reject empty, failed, or stale render output.
If a change succeeds but its observation fails, the response must preserve that distinction.
A client must not repeat a successful change because its image failed.

An end-to-end test must use the actual client and model.
The test must require recognition of a visible change that text metadata does not reveal.
That evidence must precede a claim of working visual feedback.

## Decision gates

A decision gate requires evidence before dependent implementation proceeds.
A fixture is a stable input used by tests.
The initial design requires the following decisions.
Each decision must record its environment, evidence, limits, and effect on the plan.

| Decision | Required evidence |
| --- | --- |
| ResInsight control | A tested application and Python API pair with session isolation and project lifecycle behavior. |
| Native jobs or external supervision | Supported API coverage for job start, progress, cancellation, logs, and result loading. |
| Desktop observation | Fresh native images received and interpreted through the actual client. |
| OPM Flow support | A bounded model fixture with correct well connections, run history, and imported results. |
| Julia result conversion | Demonstrated cell ordering, units, phase meanings, and report times for the supported model subset. |
| Headless rendering | Fresh 3D observations on the intended deployment environment. |

The completed [P01 experiments](platform-proof.md) provide bounded evidence for the selected macOS build, imported-well edit, OPM run, and native image path.
The [P04 record](p04-evidence.md) separately establishes bounded session and project lifecycle results.
These records do not establish general simulator support or complete external change detection.
The remaining decision gates require runtime fixtures as their implementations begin.
Source inspection and protocol declarations alone cannot close a runtime decision gate.
