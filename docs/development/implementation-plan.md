# Implementation plan

This plan describes proposed work, not current application behavior.
The first target is macOS, with OPM Flow as the first simulator.
The repository contains shared contracts, workspace storage, session operations, development tools, and runtime evidence.

A work package is a bounded change with its own owner.
Each package needs a separate pull request against `main`.
The plan uses acceptance evidence and dependencies, without delivery estimates.

## Product boundary

The proposed service controls named ResInsight sessions through rips.
It manages model revisions, simulator runs, numerical results, and native MCP images.
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

P02 implements the shared contracts, P03 implements workspace storage, and P04 implements application sessions and projects.
P05 implements the [MCP transport](mcp.md) against reviewed shared service contracts.
The P06 and later application paths below remain separate work packages.
Each owner also owns tests under the matching test path.
The lead agent owns combined acceptance tests and integration documentation.

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

## P08: Create constrained models

Define one tested model specification for a small Cartesian or layered grid.
Include rock properties, fluids, initial state, wells, controls, and reporting times.
Generate both visualization geometry and simulator inputs from that specification.

Do not treat grid geometry as a complete simulation model.
Use explicit units and record the physics template version.
Test active-cell mapping, generated properties, and a small deterministic reference run.

Acceptance requires an injector and producer in the intended active cells.
Numerical results must meet documented tolerances for the reference case.
The user guide must state the accepted model limits.

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

Submit jobs asynchronously and return a durable job identifier.
Record process identity, resources, state changes, logs, and exit status.
Keep jobs independent of MCP connections.

Cancel the owned process group and preserve a clear terminal state.
Reconcile interrupted runs after service restart without relaunching them silently.
Test these behaviors with small real child processes before simulator integration.

Acceptance requires cancellation without a surviving child process.
Disconnect and restart tests must preserve job identity and input revision.
A stale process identifier must never authorize termination of an unrelated process.

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

Create two named sessions and import or generate a small layered model.
Create an injector and producer, show their completions, run OPM, and load the results.
Clone the scenario, change a control, run it, and compare the results.

Repeat the workflow across an MCP disconnect and project save and reopen.
Cancel a run and demonstrate the resulting state.
Make sure that session identities, model revisions, units, times, and well controls remain consistent.

Acceptance combines command logs, screenshots, native image results, and numerical comparisons.
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
