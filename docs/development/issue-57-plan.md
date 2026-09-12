# General model authoring plan

Status: proposed for owner review on September 12, 2026.
This plan addresses [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57).
It proposes a new supported profile, with the existing SPE1 helper retained.
It does not establish large-case acceptance or authorize expensive runs, new physics, or publication.

## Recommendation

Deliver a complete Cartesian workflow in small reviewed changes, then establish million-cell acceptance.
Start with shared array storage, explicit limits, and an early native feasibility check.
Do not begin by raising the cell limit.
Keep input authoring, native well editing, simulator execution, and MCP transport under separate owners.
MCP is the Model Context Protocol for tool access.

The first profile should support nonuniform Cartesian spacing, inactive cells, multiple wells, single-path trajectories, and independent well controls.
Corner-point geometry, faults, local refinement, branches, multilateral wells, groups, and additional physics need separate scope decisions.
A Cartesian grid uses ordered cells along three axes.
A corner-point grid specifies each cell through corner coordinates.
These recommendations resolve open choices provisionally and require owner agreement before implementation.

## Latest merge and current constraints

[PR #58](https://github.com/LukasMosser/resinsight-mcp/pull/58) merged as `0068ed27187b16d3f3b0b7407811639b267716bf`.
It adds managed workspace creation, listing, selection, and connection-local runtime routing.
Its Linux and macOS checks passed, and its recorded shared command passed 776 tests.
The inspected local commit `8554e6f` has the same file contents as that merge.
The merge explicitly leaves general models and large grids under issue #57.

| Boundary | Current source | Effect on this plan |
| --- | --- | --- |
| Managed routing | `mcp/workspace_manager.py`, `mcp/server.py` | One lock covers invocation and response encoding. Long operations can delay polling, cancellation, and workspace selection. |
| Generated models | `models/synthetic/records.py`, `grid.py`, `deck.py` | Exactly two wells, 10,000 cells, all cells active, fixed fluid tables, and one completion per well. |
| Input admission | `models/imports/_sources.py`, `_worker.py`, `service.py` | Limits include 10,000 cells, 32 wells, 2,000,000 source characters, 200,000 expanded repetitions, and 30-second validation. |
| Model inspection | `models/imports/records.py`, `mcp/_model_operations.py` | Inspection expands properties and active-cell addresses and reparses materialized input. |
| Native preparation | `resinsight/wells/service.py`, `rips.py` | Loading requires a prepared imported model. Well names must already exist in its parsed schedule. |
| Native identity checks | `models/wells/records.py`, `resinsight/wells/rips.py` | Prepared receipts contain full corner geometry. Verification can read all cells and properties. |
| Schedule publication | `models/wells/service.py`, `records.py` | Controls change at existing reports for existing wells. New reports and new declarations require a new authoring path. |
| Flow admission | `simulators/opm/service.py` | The service caps runs at two CPUs, 2,048 MiB, and 60 seconds. Output reading also has a 30-second timeout. |
| Result storage and queries | `contracts/results.py`, `simulators/opm/_reader.py`, `results/service.py` | Full arrays, cell maps, and geometry pass through nested records and JSON. Queries read complete datasets. |
| Artifact publication | `workspaces/_files.py` | Stream copying already exists, but publication holds the database writer lock during copying and flushing. |

All source paths in this table start under `src/resinsight_mcp/`.
The implementation must also remove large arrays from manifests, prepared receipts, run records, and comparison responses.
Changing only `result_cell_property` would leave several unbounded responses and repeated allocations.

## Proposed first profile

Use a versioned `general-cartesian-field-v1` profile.
Keep the existing FIELD black-oil equations and supported fluid-table families.
Black-oil models describe oil, gas, and water flow.
Accept explicit rock, fluid, equilibrium, coordinate, and schedule inputs within that declared profile.
Provide a named, versioned SPE1 fluid preset as an optional fixture input.
Never apply that preset or other engineering defaults silently.

Represent geometry with axis widths, a documented origin and depth datum, and explicit cell ordering.
Use separate directional permeability values and a porosity field.
Allow constant fields, layer bands, bounded block assignments, and references to stored arrays.
An active-cell map identifies cells included in the simulation.
Support that map in the first profile, with all cells active in the target acceptance case.
Keep more general geometry explicitly unsupported until separately accepted.

Use feet and positive-down depth for the first native trajectory boundary.
Accept permeability in Darcy or millidarcies through explicit typed units and one conversion owner.
One Darcy equals 1,000 millidarcies.
Preserve input units and converted values in the authored specification.
Other unit systems require separately tested conversions before capability discovery advertises them.

## Target fixture decisions

The case needs complete engineering inputs before execution.
The following values are fixed by the issue or proposed for review.

| Item | Required value or proposed decision |
| --- | --- |
| Dimensions | `100 × 200 × 50`, with 1,000,000 global and active cells. |
| Layer bands | One-based layers 1–25: 1,000 mD. Layers 26–35: 10 mD. Layers 36–50: 500 mD. |
| Permeability direction | Propose equal X, Y, and Z values for each requested band. Record this assumption explicitly. |
| Producer positions | Propose cell centers at zero-based `(0, 0)` and `(99, 199)`. |
| Injector position | Propose the center of cell `(49, 99)`, one of four central cells. |
| Full-height wells | Each vertical well intersects zero-based K indices `0…49`, with 50 verified connections. |
| Missing engineering values | Owner selects cell dimensions, top depth, porosity, fluids, equilibrium, well diameter, skin, injection phase, and control values. |
| Schedule | Propose four daily reports, with explicit controls at time zero and later changes for every well. |
| Native environment | Start from the P13 custom build and matching generated RIPS client, subject to the scale check. |

An even-sized grid has no unique center cell.
The geometric center lies between four columns and can make a boundary-aligned well ambiguous.
Confirm the proposed central-cell convention or choose explicit physical coordinates before producing the fixture.
Keep all three target wells vertical to establish exactly 150 connections.
Prove slanted and horizontal paths separately on small fixtures with known intersections.

## Contracts and data ownership

### Immutable authoring and preparation

An artifact is a stored file with a durable identity.
Lineage records which earlier inputs produced an output.
Reuse `ModelRef`, `ArtifactRef`, workspace ownership, and immutable child revisions.
Add a versioned authoring manifest containing geometry, properties, fluids, well declarations, trajectories, and schedule references.
The manifest is authoritative for authored intent, while compiled inputs record the exact simulator realization.
Stored parsed summaries are derived evidence and must identify their source revision and parser version.

Separate geometry validation from runnable-model preparation.
An authored grid can load into ResInsight before it has simulator completions.
Only a complete, validated simulator model can receive a `PreparedModel` receipt.
This removes the current dependency cycle between native well creation and already-completed simulator wells.
Do not insert temporary wells or fabricated completion records to pass existing validators.

Reuse native trajectory and completion services through an explicit geometry binding.
Bind completion exports to the geometry, authoring revision, well definition, and native lifetime that produced them.
Schedule-only children can reference unchanged exports when their geometry and well definitions remain compatible.
Geometry or trajectory changes require new completion exports.
Each compilation manifest records the resolved export identities and compatibility decision.

### Arrays and bounded transport

Add one typed array descriptor shared by model and result services.
It records artifact identity, shape, numeric type, units, cell ordering, grid identity, and report identity where applicable.
Use the existing artifact store and supported NumPy interfaces for numeric files.
Prefer separate uncompressed numeric files per property and report, with a small JSON manifest.
This provides range access without requiring a new database or a compressed whole-dataset read.
Confirm the format in the feasibility change before making it a public contract.

Use implicit ordering for an all-active Cartesian grid and stored mappings for inactive grids.
Define conversion between global indices, active indices, and `(i, j, k)` addresses.
Return bounded ranges, selected cells, layer summaries, and whole-field reductions through public queries.
Paginate long well, trajectory, completion, and schedule records too.
Make geometry retrieval explicit instead of attaching every corner to each property query.
Compare result fields in bounded blocks and store differences as artifacts.

A million float64 values require 8 MB of numeric storage.
Eight three-dimensional float64 corners per cell require 192 MB before container and serialization overhead.
These calculations are lower bounds, not process-memory forecasts.
Measure the complete parser, Python, native application, and Docker workloads before setting production limits.

### Capabilities, limits, and background operations

Expose supported profiles, units, controls, query forms, native capabilities, and configured resource ceilings before a large mutation.
Capabilities must identify the selected workspace and distinguish configured support from verified runtime support.
Use one configuration owner for cells, source expansion, arrays, connections, reports, response size, memory, storage, and deadlines.
Child workers receive the resolved policy instead of duplicating constants.
Users cannot raise service ceilings through a model request.

Long creation, parsing, preparation, collection, and native operations need durable operation receipts and bounded polling.
Reuse job supervision and ownership primitives where they fit.
Keep model-operation outcomes distinct from simulator-job outcomes.
Bind each operation to its originating workspace and session before work begins.
Keep selection stable for dispatch and result publication without holding the connection lock throughout expensive work.
Never resolve a background operation against a later workspace selection.

Cancellation must remain reachable while work or artifact publication is active.
Audit database writer locks, worker ownership, partial artifacts, and native calls that cannot be interrupted safely.
Return an explicit busy or cancellation-pending state when the native interface cannot confirm interruption.
Do not claim cancellation until the owned work has stopped.
Cap retained workspace caches and report which resources remain owned after switching workspaces.

## Delivery sequence

Each row represents a focused PR or a reviewed series within one feature boundary.
The lead owns shared contracts, migrations, configuration, and MCP integration.
Domain contributors receive named files after those interfaces are agreed.

| Step | Change and main files | Required evidence before the next step |
| --- | --- | --- |
| 1. Scope and feasibility | Development decision record, small experimental drivers, reviewed native API inspection. | Owner agrees on topology and fixture inputs. Measure 10,000, 100,000, and 1,000,000 cells within an approved resource budget. Verify geometry-only loading and available native array interfaces. |
| 2. Shared storage and limits | `contracts/engineering.py`, `contracts/models.py`, `contracts/results.py`, `workspaces/`, new shared array and policy modules. | Range reads, active-map alignment, immutable publication, interrupted writes, workspace isolation, and explicit version handling. |
| 3. Managed operation lifecycle | `jobs/`, `mcp/workspace_manager.py`, `server.py`, `launcher.py`, `_workflow.py`, catalog bindings. | Poll and cancel during long work. Switch workspaces without redirecting work or results. Recover operations after client and server restart. |
| 4. General Cartesian authoring | New `models/general/`, shared import compilation in `models/imports/`, `_model_operations.py`. | Public tools create and inspect layered and inactive fixtures. Compiled geometry, properties, units, and active maps match authored inputs. |
| 5. Wells and completions | `models/wells/records.py`, `resinsight/wells/`, general authoring well records. | Geometry-only preparation works. Three named wells load. Known vertical, slanted, horizontal, separated, and inactive-cell intersections pass. |
| 6. Schedule authoring | `models/wells/service.py`, shared schedule records, general compiler. | New reports and declarations work. Per-well control histories, shut-in, reopening, immutable exports, and untouched inputs remain correct. |
| 7. Flow and scalable results | `simulators/opm/`, `results/`, native result bindings and MCP operations. | Explicit run limits, bounded output collection, array queries, comparisons, native loading, and cancellation pass on increasing case sizes. |
| 8. Public acceptance and delivery | `tests/acceptance/`, user guides, developer evidence, release instructions. | Clean installed client completes the approved target workflow and recovery checks. Every issue criterion has linked evidence. |

Step 1 establishes feasibility, not product acceptance.
Its internal experimental drivers cannot substitute for step 8 public-tool evidence.
Steps 2 and 3 precede expensive public mutations.
After step 4, result-storage work can proceed alongside wells and schedules under agreed interfaces.
Wire and test public operations with each service change rather than postponing transport integration until the final step.
Do not advertise the million-cell profile until its complete acceptance passes.

### Schedule semantics for step 6

Use an ordered typed timeline rather than an unrestricted graph or arbitrary keyword passthrough.
Define a start date and one canonical sequence of elapsed report times.
Normalize supported date input once and preserve the original date representation in provenance.
Require increasing reports and reject conflicting events for the same well and report.
Carry controls forward until an explicit event changes them.
Apply existing producer ORAT/BHP and gas/water injector RATE/BHP controls first.

Support well shut-in and reopening with explicit status events.
Preserve independent well histories and retain role and injection-phase validation.
Define pressure constraints, missing-value behavior, and rate units for every supported control.
Keep groups, role switching, new physics, and additional control types unsupported until separately agreed.
Reuse the existing parser-based preservation rules without copying the current schedule writer into another implementation.
Add a bounded schedule inspection and semantic diff operation.

## Compatibility and migration

Keep SPE1 template names, existing small-model operations, and their tested behavior.
Add explicit general-profile operations or versioned requests with unambiguous schemas.
Do not silently reinterpret an existing `model_create` request.
Define how old prepared receipts, result manifests, and saved workspace records remain readable.
Use explicit schema versions and a documented migration when stored data needs conversion.
Preserve original artifacts, model identifiers, and parent relationships during conversion.

Prevent large results from entering old operations that require complete inline arrays.
Return a typed limit error with the supported bounded query operation.
Avoid maintaining separate numerical algorithms for old and new storage layouts.
The shared reader should normalize supported versions through declared interfaces.
Run existing P13 acceptance and managed-workspace regressions after contract and routing changes.
Make sure that fixed-workspace mode remains supported too.

## Acceptance matrix

| Criterion | Evidence |
| --- | --- |
| Exact million-cell geometry | Parsed dimensions, active count, positive volumes, and representative coordinates against the approved fixture. |
| Three permeability bands | Full-field comparison through bounded iteration, including both sides of layer boundaries 25/26 and 35/36. |
| Complete engineering inputs | Published fixture specification with explicit porosity, dimensions, fluids, equilibrium, datum, dates, and controls. |
| Three full-height wells | Exact expected cell sets and 50 connections per well, with units, measured depth, diameter, skin, direction, and factors. |
| Complex trajectories | Small analytic fixtures establish slanted and horizontal intersections, separated intervals, inactive gaps, and invalid paths. |
| Independent schedules | All three wells change controls over multiple reports. Shut-in, reopening, and unchanged controls retain their intended semantics. |
| Immutable lineage | Queries connect model, geometry, wells, exports, schedule, prepared inputs, job, output artifacts, and accepted results. |
| Flow outcome | Approved target run completes with accepted outputs, or records a typed diagnostic failure with its exact cause and resource measurements. |
| Native use and recovery | Fresh images and numerical queries before and after project reopen, MCP restart, and explicit native reference rebinding. |
| Bounded transport | Representative calls remain below the declared response limit. Oversized requests fail before expensive allocation or mutation. |
| Managed isolation | Long work remains bound to workspace A after selecting B. Foreign references fail, and selection cannot redirect publication. |
| Operational limits | Measured peak memory, elapsed time, storage, query latency, response size, cancellation latency, and cleanup state. |
| Public workflow | A clean installed SDK client creates all domain inputs through discovered tools, without hidden setup or private database writes. |

The issue permits a completed or explicitly rejected large Flow run.
A typed rejection proves error handling, but it cannot establish successful million-cell simulation or accepted result loading.
If the approved target fails, record the failed criterion and seek an explicit scope decision before closing the issue.
Keep automatic reference comparisons distinct from observed scenario changes and visual evidence.
Use exact identity and count checks, with justified numerical tolerances for simulator and native conversions.

## Resource and evidence gates

Before the million-cell experiment, approve separate budgets for Docker, parser workers, output readers, native memory, total disk, and wall time.
Record available host capacity and the resolved limits in the experiment manifest.
Estimate storage before admitting work, including immutable inputs, staged publication, copied bundles, reports, and evidence archives.
Measure parser expansion and native calls that materialize full arrays even when MCP responses remain bounded.
If supported native interfaces cannot meet the budget, require a separately reviewed native change or a revised acceptance scope.
Do not assume undocumented chunking methods exist.

The first feasibility record should compare the existing custom ResInsight source and generated RIPS package with their actual running versions.
Keep OPM parser and Flow versions explicit.
Do not assume the versions recorded in P13 establish current million-cell support.
Use the shared repository command for maintained checks on Linux and macOS.
Run large native and simulator acceptance separately on the approved host.
No timing claims or resource ceilings in this plan are measured acceptance results.

Keep summaries, commands, benchmarks, failure decisions, and selected original images directly reviewable.
Put bulk calls, arrays, repeated logs, and generated outputs in a compressed evidence archive.
Document its member paths and extraction instructions.
Verify parsed content and complete membership before publication.
Use visual inspection and numerical comparisons instead of byte-level tests.

## Tracking and execution

Keep issue #57 open as the parent work issue until its agreed criteria have evidence.
Propose a separate delivery milestone for general Cartesian model authoring.
Create child issues for the delivery steps after the owner accepts the scope.
Use native GitHub dependency relationships, relevant area labels, and one major feature per PR against `main`.
Keep P16 and P17 work distinct and link overlapping recovery or installation evidence explicitly.
Do not close broad issue criteria through a narrow first slice without an owner-approved scope change.

The lead owns shared records and integration decisions.
Future delegated work uses `gpt-5.6-luna` with max reasoning in separate `codex/` worktrees.
Owner-requested additional tasks use `gpt-6-astra` with extra high reasoning (`xhigh`).
Each writing agent commits one complete logical change for review and cherry-pick.
No additional task is required to review this plan.

## Owner decisions before implementation

1. Approve Cartesian geometry, inactive cells, and single-path wells as the first general profile.
2. Approve deferring corner-point grids, faults, refinement, branches, groups, and additional physics.
3. Select the missing fixture inputs and confirm the central-cell convention.
4. Approve the target host and separate memory, storage, CPU, and time budgets before scale experiments.
5. Confirm that successful million-cell simulation is required for closure, or define an acceptable documented rejection outcome.

These decisions follow the repository rule for scope, supported physics, and costly runtime requirements.
Planning and source review can continue while those decisions remain open.
Implementation should begin with the agreed contract and feasibility step, not a blanket increase of existing limits.

## Plan review

The [planning review record](evidence/issue-57-plan/README.md) preserves source references, documentation checks, and the rendered delivery sequence.
No general-model implementation or large-case runtime experiment was performed for this plan.
