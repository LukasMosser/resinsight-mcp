# Implementation plan

This plan separates delivered packages from remaining integration work.
The first target is macOS, with OPM Flow as the first simulator.
The [operation map](agent-workflows.md) records current MCP access and its acceptance evidence.

A work package is a bounded change with its own owner.
Each package needs a separate pull request against `main`.
The plan uses acceptance evidence and dependencies, without delivery estimates.

## Product boundary

The product goal is an agent-operated ResInsight workflow, from project navigation to model setup, simulation, result inspection, and recovery.
MCP is the Model Context Protocol for tool access.
The agent must perform supported domain operations through public MCP tools connected to explicit ResInsight sessions.
Python services, shared contracts, and storage support that workflow.
A model revision is a fixed set of engineering inputs.

The first engineering workflow imports a supported OPM input model.
A separate authoring workflow creates small models from a tested template.
Both workflows preserve source inputs and record the exact revision used for each run.

The first release excludes these areas:

- Arbitrary geological model construction and fault editing.
- Unrestricted Python or shell tools exposed through MCP.
- Hosted access, shared remote users, and cluster scheduling.
- Unsupported simulator physics or silent conversions between simulators.
- Automatic optimization and history matching.

## Decisions and gates

A gate is evidence required before dependent work starts.
The owner selected macOS for the first real demonstration.
The owner approved a public repository and documentation on GitHub Pages.

| Decision | Proposed choice | Evidence or owner input |
| --- | --- | --- |
| Application host | macOS | P01 must prove a build with working gRPC. |
| First client | Codex with local MCP access | P01 must prove that the model receives a native image. |
| Python baseline | Python 3.12 | P01 records the matching application and rips versions. |
| First simulator | OPM Flow | P01 must prove the selected macOS execution environment. |
| Model scope | Small Cartesian or layered grid with a tested physics template | P07 records supported keywords, phases, units, and controls. |
| OPM execution | A dedicated adapter with explicit job control | P01 compares native Jobs coverage before this choice becomes final. |
| Julia result transfer | Explicit transfer of cell data and curves | P14 must prove cell order, units, rate signs, and report times. |
| Distribution | Source first, with component license records | The owner selected GPL-3.0-or-later for original project files. |

The published macOS build instructions disable gRPC.
This is a feasibility risk for the chosen platform, not proof that every macOS build lacks it.
If P01 cannot prove Python control, stop dependent integration work and request a platform or build decision.

Do not substitute GUI automation or another host without that decision.
Do not assume that OPM runs natively on macOS because ResInsight supports OPM Jobs.
Record the exact execution environment for both applications.

## Ownership and integration

Each agent uses a separate worktree and a `codex/` branch.
The lead agent owns shared configuration and the application entry point.
Package owners add dependencies through the lead agent to avoid competing lockfile changes.

P02 owns shared types and interface definitions.
Other packages depend on those interfaces and keep simulator-specific details in their own modules.
An interface change needs a small P02 follow-up before dependent implementation changes.

The [well control follow-up](well-contracts.md) supplies common FIELD controls for P08 and P09.
Package owners keep grid creation and native well geometry separate while using these shared control records.

The [P07 materialization follow-up](model-materialization-evidence.md) supplies validated stored inputs, parser inspection, and one child publication path for P09.
The lead transferred its bounded import files, tests, and guide to the P09 owner under [issue #39](https://github.com/LukasMosser/resinsight-mcp/issues/39).
Native well and schedule services consume the reviewed interface without owning import validation or publication rules.

P02 implements the shared contracts, P03 implements workspace storage, and P04 implements application sessions and projects.
P05 implements the [MCP transport](mcp.md) against reviewed shared service contracts.
The remaining application paths below retain separate work package ownership.
Each owner also owns tests under the matching test path.
The lead agent owns combined acceptance tests and integration documentation.

[Issue #35](https://github.com/LukasMosser/resinsight-mcp/issues/35) assigns one lead integration owner for the shipped launcher, service composition, and domain MCP wiring.
Package owners retain model, well, simulator, and result algorithms behind agreed typed interfaces.
The first slice connects implemented session services through [documented launcher configuration](../mcp.md#enable-resinsight-sessions).
Its [acceptance record](launcher-evidence.md) proves public session and project operations from a clean installation.
Issue #35 remains open for view, job, and domain integration as dependent services become ready.
Users must not need to author a Python server for the completed product workflow.

The [operation map](agent-workflows.md#gaps-and-proposed-ownership) records missing MCP paths and their package owners.
P07 import services still need domain tools, while views need trusted result loading and jobs need simulator preparation and command resolution.
P08, P09, P11, and P12 retain their accepted domain scope.
P13 and P17 require the integrated launcher and public domain tools before their acceptance can pass.

| Package | Owned application paths | Dependencies |
| --- | --- | --- |
| P01 Platform proof | `experiments/platform/` | Foundation |
| P02 Shared contracts | `src/resinsight_mcp/contracts/` | P01 findings |
| P03 Workspaces | `src/resinsight_mcp/workspaces/` | P02 |
| P04 Sessions | `src/resinsight_mcp/resinsight/sessions/` | P01, P02, P03 |
| P05 MCP interface | `src/resinsight_mcp/mcp/` | P02 |
| P06 Views and images | `src/resinsight_mcp/resinsight/views/` | P04, P05 |
| P07 Imported models | `src/resinsight_mcp/models/imports/` | P02, P03 |
| P08 Synthetic models | `src/resinsight_mcp/models/synthetic/` | P07 |
| P09 Wells and schedules | `src/resinsight_mcp/models/wells/`, `src/resinsight_mcp/resinsight/wells/` | P04, P07 |
| P10 Job control | `src/resinsight_mcp/jobs/` | P02, P03 |
| P11 OPM adapter | `src/resinsight_mcp/simulators/opm/` | P01, P07, P09, P10 |
| P12 Results | `src/resinsight_mcp/results/` | P02, P04, P06, P11 |
| P13 OPM acceptance | `tests/acceptance/opm/` | P03–P12 |
| P14 Julia proof | `experiments/julia/` | P02, P07 |
| P15 Julia adapter | `src/resinsight_mcp/simulators/julia/` | P10, P12, P14 |
| P16 Recovery and boundaries | `tests/acceptance/recovery/` | P13 for OPM, P15 for the Julia extension |
| P17 Distribution | Packaging, entry point, release workflows, user guides | P13 and OPM P16 first, then the Julia acceptance evidence |

Parallel work starts after P02 defines its contracts.
P03 and P05 can then proceed independently, while P07 follows P03.
P04 and P10 can proceed together after P03, with P08, P09, and P14 following P07.

P16 and P17 each have an OPM milestone and a separate Julia extension.
The OPM release does not depend on Julia completion.
Each extension needs its own PR and the relevant backend evidence.

The lead agent integrates finished packages in dependency order.
For a conflict, the lead agent preserves both intended behaviors and runs the affected tests again.
No agent changes another owner's files without an agreed transfer of scope.

## P01: Prove the macOS path

Prove a ResInsight build with gRPC and a matching rips package on the selected macOS host.
Attach by explicit endpoint, launch an owned instance, open a small case, change a view, and export an image.
Make a bounded well edit and record whether the required completion export works.

Compare native OPM Jobs against the documented Python interface and source.
Record callable methods and gaps without inventing an API.
Prove the chosen OPM execution environment with a small supported model.

Use the actual MCP client for an image experiment.
The model must describe a randomly placed visible marker that text metadata does not reveal.
Keep prototype code outside the application package and remove it when maintained tests replace it.

Acceptance evidence includes these records:

- Application, rips, Python, OPM, macOS, and hardware versions.
- Build instructions and logs for gRPC support.
- Commands, a view screenshot, and a native MCP image result.
- The model's answer to the visual task and its known expected answer.
- A native Jobs capability table and an OPM run log.
- A component and sample-data license inventory.

## P02: Define shared contracts

Define typed identifiers for sessions, model revisions, jobs, results, and observations.
An observation is an image with its model and view context.
Define units, depth direction, cell identity, report times, and error meanings in one place.

Define interfaces for process ownership, workspace storage, rendering, model preparation, job control, and result import.
Keep these interfaces independent of rips and simulator imports.
Use focused tests for invalid combinations, state transitions, and serialization of public messages.

The lead agent adds pytest to the shared command with the first real test suite.
That change removes the foundation message about absent application tests.
CI must run the new suite before P02 can merge.

Acceptance requires reviewed examples of successful requests and clear errors.
The examples must distinguish a busy application, lost connection, stale object, invalid model, and unsupported operation.
The interfaces must also distinguish a successful edit from a failed image export.

## P03: Store workspaces and revisions

P03 implements `SqliteWorkspaceStore` for trusted local macOS and Linux filesystems.
SQLite preserves typed records, while workspace-owned directories hold immutable artifact files.
An artifact is a stored input, output, image, log, or project.
The [workspace guide](workspaces.md) documents the public API and source layout.

The store preserves original inputs and creates fixed revisions with explicit parent relationships.
Clones share unchanged artifact references and use new artifacts for replacements.
Project checkpoints bind supplied project files to revisions without proving external application contents.

Schema version 1 rejects unsupported versions without migration or overwrite.
File publication precedes the metadata commit, so interrupted writes can leave unreachable files for explicit recovery.
Expected job records prevent stale competing updates.
Recovery requires a stopped job controller and changes only explicitly selected job snapshots.

Acceptance covers fresh-process reopening, concurrent writes, isolated workspaces, rejected paths, immutable clones, and incomplete writes.
The maintained suite and review evidence establish those results separately from future application lifecycle and simulator acceptance.

## P04: Manage sessions and projects

P04 implements create, list, launch, attach, select, detach, and close operations through `ResInsightSessionService`.
Every mutation identifies its session explicitly.
Closing detaches by default, while attached process termination requires separate trusted authorization.

The service serializes application operations and distinguishes busy, lost, and failed outcomes.
Project commands and observed inventory changes invalidate object references.
The native API does not expose a complete external event history, so identical empty-project reopening and unobserved fields remain detection limits.
The [session implementation](sessions.md) records those boundaries and the supported save and reopen operations.

The [P04 record](p04-evidence.md) reports the real two-session trial, MCP disconnect behavior, and stale reference evidence.

## P05: Expose MCP operations

Use the MCP Python SDK and local standard input and output for the first transport.
Bind tools to the shared service interfaces and publish typed request descriptions.
Keep protocol state separate from durable engineering workspaces.

Define tool and resource names in one reviewed catalog.
Return stable errors without exposing raw shell execution.
Use protocol-level tests with a real SDK client for request handling and reconnect behavior.

Acceptance requires tools that resolve explicit session identifiers and preserve mixed text and image content.
An empty or hidden image result must fail the image acceptance task.
Application logs must not corrupt the protocol output stream.

## P06: Control views and return images

Support case, well, and view selection by identifier.
Configure the displayed property, report time, camera, filters, and legend bounds through one view operation.
Return native MCP image content with a unique observation identifier.

Record the session, revision, case, view, property, units, report time, and dimensions with each image.
Also record the camera, projection, vertical exaggeration, filters, and legend bounds.
Use supported image decoding to establish that an export is usable.
Do not add byte-level assertions or return an earlier image after export failure.

Acceptance requires visible changes in the real client and fixed legends for comparisons.
Test stale observations and the case where an edit succeeds but rendering fails.
Keep screenshots and decoded image properties as evidence without exact pixel comparisons.

The bounded implementation adds a reviewed native scripting patch for camera, legend, and display-filter APIs.
Its property set includes `PRESSURE`, `SWAT`, `SGAS`, `SOIL`, and `PORO`.
Pressure display currently requires proved `FIELD` inputs, and display filters use the main grid.
The host must supply session and view services and establish trusted result bindings.
The [P06 evidence](p06-evidence.md) separates those integration requirements from model-facing acceptance.

On September 9, 2026, the owner deferred the native editor visual inspection from P06 completion.
The [follow-up](https://github.com/LukasMosser/resinsight-mcp/issues/34) retains that inspection, and the evidence record does not claim a visual pass.

## P07: Import supported models

Import an OPM deck and its include files into a new revision.
A deck is the simulator's main text input file.
Use an established parser and publish the supported keywords and physics.

Reject missing includes, unsupported features, inconsistent units, and incomplete well controls.
Preserve source files and record changes separately.
Test small representative models and clear failure cases without a general text-replacement parser.

Acceptance requires a model that OPM accepts and ResInsight displays.
The record must connect the source inputs, prepared revision, and loaded case.
An invalid input must stop before simulator submission.

P07 implements isolated materialization of stored inputs and validated child revision publication for domain consumers.
Its [interface guide](model-imports.md#materialization-and-child-revisions) defines temporary ownership, geometry inspection, parent inheritance, and uncertain cleanup outcomes.
The current `spe1-field-v2` profile accepts bounded explicit completion factors without changing parser version or black-oil physics.
Earlier `spe1-field-v1` records still deserialize without rewriting their stored profile.
The [follow-up evidence](model-materialization-evidence.md) records public library checks separately from native P09 acceptance.

## P08: Create constrained models

P08 implements `SyntheticModelService` for a complete layered FIELD model with an explicit datum.
Its reusable specification includes grid dimensions, layer properties, fixed SPE1 fluids, equilibrium, one injector, one producer, controls, and report intervals.
The source preserves its template version, generation specification, and stable grid identifier.
The service delegates validation and immutable publication to P07.

The [user guide](../synthetic-models.md) states the accepted cell, schedule, physics, and control limits.
Focused tests compare properties, every active-cell position, completion indices, reconstruction, and publication failures.
Four bounded Flow trials compare the generated reference with the preserved P07 model and repeat both sources.
The [P08 record](synthetic-models.md) preserves exact parsed values, justified tolerances, commands, and runtime limits.
Its native trial verifies the generated geometry and all final pressure values, with a reviewed image and verified process cleanup.
Model creation has no public MCP operation yet and remains part of [issue #35](https://github.com/LukasMosser/resinsight-mcp/issues/35) integration.

## P09: Connect wells to simulator inputs

Create or update modeled well paths, completions, and schedules through an agreed ResInsight adapter interface.
A completion connects a well to reservoir cells.
Combine exported connections with the intended simulator names and controls.

Make depth direction and measured-depth intervals explicit.
Reject controls, names, or intervals that do not match the prepared model.
Do not rely on a visible filter unless completion export demonstrably consumes it.

Acceptance requires matching trajectories, active cells, exported connections, and simulator well records.
Include a depth-sign regression and a rejected invalid completion.
Attach screenshots and a readable connection summary to the PR.

## P10: Supervise durable jobs

P10 implements asynchronous submission through `DurableJobController` and an independent supervisor for each job.
Workspace records preserve input revision, resources, process identities, state history, logs, and exit status.
Cancellation targets only the supervisor's owned process group.
Explicit reconciliation preserves uncertain outcomes without relaunching commands or signaling stored process identifiers.

The approved `wall_time_only` policy enforces wall deadlines and records CPU and memory requests without enforcement.
The default `enforce` policy is rejected before submission because this generic controller cannot enforce all requested limits.
The [job guide](jobs.md) defines the process ownership boundary and recovery preconditions.
The [P10 record](p10-evidence.md) reports real child cancellation, stale ownership, disconnect, restart, and failure races.
Simulator preparation and numerical result acceptance remain in later packages.

## P11: Run OPM Flow

Prepare an isolated run directory from one fixed model revision.
Start the chosen OPM executable through job control and record its version and arguments.
Keep the adapter independent of MCP request handling.

Distinguish process completion from acceptable simulation results.
Record final simulated time, convergence warnings, expected outputs, and agreed numerical tolerances.
Reject outputs that do not match the submitted revision or expected model identity.

Acceptance requires successful, invalid-input, failed, and canceled runs.
Include a restart test for a recorded job and a deterministic reference comparison.
Use semantic input and result records, without byte-for-byte output tests.

## P12: Load and compare results

Load grid results and summary curves into the correct ResInsight session.
Return numerical queries with units, report times, well names, and revision identity.
Compare scenarios on aligned report times and fixed view legends.

Keep field quantities, cell properties, and well curves distinct.
Reject mismatched cell mappings or unsupported unit conversions.
Test a result set with known values and clear differences between scenarios.

Acceptance requires the same run identity in numerical queries and images.
An old job's output must not replace a newer case silently.
Show pressure, saturation, and well curves with their source run records.

## P13: Prove the OPM workflow

Start from a clean installation with the shipped launcher and documented configuration.
Discover capabilities and perform every domain setup step through public MCP tools.
Do not compose a custom server or seed model, job, result, or native case records through hidden Python setup.
The [launcher integration](https://github.com/LukasMosser/resinsight-mcp/issues/35) is an acceptance prerequisite.

Create two named sessions and import or generate a small layered model.
Create an injector and producer, show their completions, run OPM, and load the results.
Clone the scenario, change a control, run it, and compare the results.

Repeat the workflow across an MCP disconnect and project save and reopen.
Cancel a run and demonstrate the resulting state.
Make sure that session identities, model revisions, units, times, and well controls remain consistent.

Acceptance combines command logs, screenshots, native image results, and numerical comparisons.
Preserve the agent's requests and responses across setup, simulation, result loading, comparison, and recovery.
Record exact tool versions and the tested commit.
The macOS demonstration is required even when isolated tests pass on another platform.

## P14: Prove Julia result transfer

Define the supported overlap between OPM and JutulDarcy physics.
Run a small model through PyJutulDarcy in a persistent worker.
Record active-cell order, units, rate signs, report times, and well identities.

Prove an explicit transfer of cell properties and curves into matching ResInsight geometry.
Do not assume an Eclipse-compatible binary export exists.
Keep worker startup and shutdown observable in the experiment logs.

Acceptance requires known cell values in the intended cells and matching plotted curves.
Use physical reference tolerances rather than expecting identical solver outputs.
If a required quantity cannot transfer correctly, request a scope decision before P15.

## P15: Add the Julia adapter

Implement the worker protocol and result conversion established by P14.
Keep Julia startup, package versions, and numerical work outside MCP calls.
Use the shared job and result interfaces.

Support submission, progress, cancellation, and worker failure for the agreed physics subset.
Preserve logs and model lineage across worker restart.
Reject unsupported models without switching to OPM.

Acceptance repeats the agreed engineering workflow with Julia results in ResInsight.
Include reference comparisons, result mapping evidence, and cancellation logs.
Document backend differences that affect scientific interpretation.

## P16: Prove recovery and access boundaries

Complete this package for OPM after P13, then add Julia coverage after P15.
Test application crashes, service restart, busy responses, partial outputs, and human edits.
Apply explicit limits to run count, storage, and compute use.
Keep ResInsight's control endpoint local to its host.

Make project replacement and concurrent edits fail clearly when identifiers become stale.
Exercise workspace path limits and ownership rules through the real service.
Assign each fix to its module owner and keep one integration owner for the acceptance suite.

Acceptance requires no lost completed revisions and no unintended process termination.
Every failure must identify the affected session or run and explain the next valid action.
Keep evidence for recovery paths and resource-limit rejection.

## P17: Package and release

Complete an OPM release after its P16 milestone without waiting for Julia.
Add the Julia support boundary in a separate release after its acceptance tests pass.
Package the supported service and publish exact installation instructions for the proved macOS setup.
Record third-party licenses and sample-data terms before distribution.
Keep application releases separate from simulator binaries unless their distribution terms receive review.

Use a release PR for the version, supported versions, migration notes, and acceptance evidence.
Run GitHub Actions and create a draft GitHub Release from the reviewed commit.
Publish the release after the owner accepts the documented support boundary.

Acceptance requires installation in a clean environment and the complete documented demonstration.
Use the shipped launcher, documented configuration, and public MCP tools throughout that demonstration.
Do not require a custom Python server or hidden record seeding for domain setup.
The OPM release must satisfy the [launcher integration acceptance](https://github.com/LukasMosser/resinsight-mcp/issues/35).
User pages must describe only implemented behavior and known limits.
Publish documentation updates through the existing GitHub Pages workflow.

## Evidence and review

Each PR links logs from its tested commit and explains what those logs prove.
Visible features also include screenshots and native image evidence.
Tests use observable behavior, representative scientific cases, and documented tolerances.

The reviewer assesses duplicate behavior, code complexity, and maintenance cost for every code change.
The reviewer also makes sure that failures do not report false success.
Coverage guides investigation but does not set a target of 100 percent.

The [scope review](scope-review.md) contains the upstream evidence and unresolved claims.
The [architecture](architecture.md) describes the proposed service boundaries.
The [test guide](testing-and-review.md) defines the review process used by these packages.
