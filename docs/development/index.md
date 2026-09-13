# Development

This section explains the implementation behind an agent-operated ResInsight workflow.
The [operation map](agent-workflows.md) connects user tasks to current tools, configuration, evidence, and remaining integration work.
The [architecture](architecture.md) separates ResInsight control, simulator inputs, job supervision, and MCP transport.

The Python 3.12 library validates shared records with Pydantic and defines typed boundaries with standard-library protocols.
Its SQLite workspace store preserves sessions, immutable model revisions, artifacts, jobs, results, observations, and project checkpoints.
The MCP transport binds these services and preserves native image responses.
Session and view adapters control verified application connections and capture fresh observations.
Model import and job services provide additional domain components.
The OPM adapter runs the fixed FIELD profile in owned containers and publishes verified numerical results.
Constrained model creation supplies validated layered inputs through the model import boundary.
Result services connect accepted immutable outputs to verified native cases, aligned numerical queries, and summary plot observations.

Model materialization supplies isolated stored inputs and validated child revisions for domain consumers.
Well services create native paths, export fixed connections, and publish child schedules through separate operations.
The supplied launcher configures workspace, native session, model, and complete OPM workflow services through explicit options.
The OPM option joins native wells, bounded Flow jobs, verified results, comparisons, and views without moving their algorithms into transport code.

Start with these pages:

- [Local setup](local-setup.md) explains the development commands.
- [Agent workflows](agent-workflows.md) maps current tools and assigns the remaining integration work.
- [Shared contracts](contracts.md) documents the implemented data conventions and typed boundaries.
- [Run and result contracts](run-result-contracts.md) defines execution ownership, output roles, numerical data, and comparison checkpoints.
- [OPM workflow delivery](p13-delivery.md) connects P11, P12, and P13 scope, ownership, and acceptance evidence.
- [Public OPM acceptance](opm-acceptance.md) describes the reviewed clean-installation driver and completed native trial.
- [Public OPM evidence](evidence/p13/public-workflow/README.md) preserves complete calls, numerical comparisons, native images, recovery, and cancellation.
- [Workspaces](workspaces.md) explains durable storage, immutable cloning, and explicit recovery.
- [MCP transport](mcp.md) explains typed operations, protocol isolation, and native content.
- [Launcher evidence](launcher-evidence.md) records native session control from a clean installation.
- [Sessions](sessions.md) explains application ownership, project operations, and observed change limits.
- [Project mutations](session-mutations.md) defines the trusted callback boundary, refreshed references, and failure evidence.
- [Jobs](jobs.md) explains durable supervision, resource policy, and recovery limits.
- [Docker job ownership](docker-jobs.md) explains container identity, deadlines, cancellation, and explicit recovery.
- [OPM execution](opm.md) explains pinned Flow preparation, limits, output verification, and accepted result publication.
- [OPM runtime evidence](evidence/p11/README.md) records actual runs, failures, cancellation, deadlines, and reference agreement.
- [Result services](results.md) explains verified native loading, aligned queries, comparisons, and summary plot receipts.
- [Job evidence](p10-evidence.md) records real child processes and MCP disconnect acceptance.
- [View control](views.md) explains native settings, trusted result bindings, and fresh observations.
- [View evidence](p06-evidence.md) separates native checks, local protocol delivery, and model-facing acceptance.
- [Constrained models](synthetic-models.md) explains generated inputs, stored specifications, and numerical acceptance.
- [Model materialization evidence](model-materialization-evidence.md) covers isolated inputs, child revision publication, and cleanup failures.
- [Native wells](wells.md) explains prepared cases, native well edits, completion exports, and acceptance evidence.
- [Persistent well lifetime](evidence/p09/lifetime/README.md) records full FIELD case and well restoration across two project reopen cycles.
- [Well schedules](well-schedules.md) explains control overlays, FIELD values, immutable child revisions, and preservation checks.
- [Platform proof](platform-proof.md) records completed P01 experiments and their runtime limits.
- [GitHub organization](project-organization.md) explains labels, milestones, dependencies, and work issue links.
- [Testing and review](testing-and-review.md) explains the evidence for a change.
- [Architecture](architecture.md) separates implemented contracts and storage from proposed runtime responsibilities.
- [Implementation plan](implementation-plan.md) records the work sequence and acceptance criteria.
- [General model plan](issue-57-plan.md) records the approved geometry, well, schedule, and resource work for issue #57.
- [Scope review](scope-review.md) records source findings and unresolved questions.
- [Releases](releases.md) explains release evidence and approval.

Repository policies remain in their source files.
Read [CONTRIBUTING.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/CONTRIBUTING.md) before a contribution.
Read [AGENTS.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/AGENTS.md) before agent work.
Use [SECURITY.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/SECURITY.md) for security reports.

The [general geological authoring record](general-model-authoring.md) describes the first implementation and its remaining scope.
The [general well record](general-wells.md) describes native paths and immutable connection exports on authored grids.
The [general schedule record](general-schedules.md) describes independent histories and immutable report timelines.
