# resinsight-mcp

This repository provides an installable Python 3.12 contracts library.
Contracts define shared data and component interfaces.
The library uses Pydantic for record validation and standard-library protocols for typed boundaries.
It has no CLI, MCP server, ResInsight adapter, or simulator adapter.

MCP is the Model Context Protocol for tool access.
The package does not expose application commands, start simulator runs, or deliver native image responses.
The separate [P01 experiments](development/platform-proof.md) preserve successful bounded runtime evidence on one macOS host.
They do not establish a supported host or simulator version matrix for this library.

Use the [shared contract guide](development/contracts.md) for data conventions and examples.
The [development guide](development/index.md) describes the repository workflow and future design.
The [local setup guide](development/local-setup.md) explains installation, tests, and documentation preview.
The [contribution policy](https://github.com/LukasMosser/resinsight-mcp/blob/main/CONTRIBUTING.md) explains how to propose a change.
