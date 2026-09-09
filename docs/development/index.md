# Development

This section contains the development workflow, implemented library behavior, and proposed integration design.
The library defines shared records, typed boundaries, a SQLite workspace store, and ResInsight session and project operations.
The MCP transport binds shared services and preserves native image responses.
Durable job supervision keeps trusted command execution independent of client connections.
Configured view services apply native settings, capture fresh images, and reject stale observations.
Simulator adapters remain separate work packages.

Start with these pages:

- [Local setup](local-setup.md) explains the development commands.
- [Shared contracts](contracts.md) documents the implemented data conventions and typed boundaries.
- [Workspaces](workspaces.md) explains durable storage, immutable cloning, and explicit recovery.
- [MCP transport](mcp.md) explains typed operations, protocol isolation, and native content.
- [Sessions](sessions.md) explains application ownership, project operations, and observed change limits.
- [Jobs](jobs.md) explains durable supervision, resource policy, and recovery limits.
- [Job evidence](p10-evidence.md) records real child processes and MCP disconnect acceptance.
- [View control](views.md) explains native settings, trusted result bindings, and fresh observations.
- [View evidence](p06-evidence.md) separates native checks, local protocol delivery, and model-facing acceptance.
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
