# resinsight-mcp

This Python 3.12 library provides shared contracts, local workspace storage, and ResInsight session and project operations.
Contracts define shared data and component interfaces.
The library uses Pydantic for record validation and standard-library protocols for typed boundaries.
The optional ResInsight adapter launches or attaches to verified local application processes.

MCP is the Model Context Protocol for tool access.
The package does not yet include a production MCP transport or simulator adapter.
The separate [P01 experiments](development/platform-proof.md) preserve successful bounded runtime evidence on one macOS host.
They do not establish a supported host or simulator version matrix for this library.

The workspace store preserves sessions, immutable revisions, artifact files, jobs, results, observations, and project checkpoints.
It uses SQLite on trusted local macOS or Linux filesystems.
The [workspace guide](development/workspaces.md) explains storage, cloning, and explicit recovery.
The [session guide](sessions.md) explains application ownership, project operations, and observed change limits.

Use the [shared contract guide](development/contracts.md) for data conventions and examples.
The [development guide](development/index.md) describes the repository workflow and future design.
The [local setup guide](development/local-setup.md) explains installation, tests, and documentation preview.
The [contribution policy](https://github.com/LukasMosser/resinsight-mcp/blob/main/CONTRIBUTING.md) explains how to propose a change.
