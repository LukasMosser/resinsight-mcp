# Development

This section explains the implementation behind an agent-operated ResInsight workflow.
The [operation map](agent-workflows.md) connects user tasks to current tools, configuration, evidence, and remaining integration work.
The [architecture](architecture.md) separates ResInsight control, simulator inputs, job supervision, and MCP transport.

The Python 3.12 library validates shared records with Pydantic and defines typed boundaries with standard-library protocols.
Its SQLite workspace store preserves sessions, immutable model revisions, artifacts, jobs, results, observations, and project checkpoints.
The MCP transport binds these services and preserves native image responses.
Session and view adapters control verified application connections and capture fresh observations.
Model import and job services provide additional domain components.
Constrained model creation supplies validated layered inputs through the model import boundary.

Model materialization supplies isolated stored inputs and validated child revisions for domain consumers.
Well services create native paths, export fixed connections, and publish child schedules through separate operations.
The supplied launcher exposes workspace tools and can configure native session services.

Start with these pages:

- [Local setup](local-setup.md) explains the development commands.
- [Agent workflows](agent-workflows.md) maps current tools and assigns the remaining integration work.
- [Shared contracts](contracts.md) documents the implemented data conventions and typed boundaries.
- [Workspaces](workspaces.md) explains durable storage, immutable cloning, and explicit recovery.
- [MCP transport](mcp.md) explains typed operations, protocol isolation, and native content.
- [Launcher evidence](launcher-evidence.md) records native session control from a clean installation.
- [Sessions](sessions.md) explains application ownership, project operations, and observed change limits.
- [Project mutations](session-mutations.md) defines the trusted callback boundary, refreshed references, and failure evidence.
- [Jobs](jobs.md) explains durable supervision, resource policy, and recovery limits.
- [Job evidence](p10-evidence.md) records real child processes and MCP disconnect acceptance.
- [View control](views.md) explains native settings, trusted result bindings, and fresh observations.
- [View evidence](p06-evidence.md) separates native checks, local protocol delivery, and model-facing acceptance.
- [Constrained models](synthetic-models.md) explains generated inputs, stored specifications, and numerical acceptance.
- [Model materialization evidence](model-materialization-evidence.md) covers isolated inputs, child revision publication, and cleanup failures.
- [Native wells](wells.md) explains prepared cases, native well edits, completion exports, and acceptance evidence.
- [Well schedules](well-schedules.md) explains control overlays, FIELD values, immutable child revisions, and preservation checks.
- [Platform proof](platform-proof.md) records completed P01 experiments and their runtime limits.
- [GitHub organization](project-organization.md) explains labels, milestones, dependencies, and work issue links.
- [Testing and review](testing-and-review.md) explains the evidence for a change.
- [Architecture](architecture.md) separates implemented contracts and storage from proposed runtime responsibilities.
- [Implementation plan](implementation-plan.md) records the work sequence and acceptance criteria.
- [Scope review](scope-review.md) records source findings and unresolved questions.
- [Releases](releases.md) explains release evidence and approval.

Repository policies remain in their source files.
Read [CONTRIBUTING.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/CONTRIBUTING.md) before a contribution.
Read [AGENTS.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/AGENTS.md) before agent work.
Use [SECURITY.md](https://github.com/LukasMosser/resinsight-mcp/blob/main/SECURITY.md) for security reports.
