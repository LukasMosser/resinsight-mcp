# resinsight-mcp

This repository provides an installable Python 3.12 contracts library for a ResInsight MCP integration.
Contracts define the data and interfaces that components share.
MCP is the Model Context Protocol for tool access.
The package has no CLI, MCP server, ResInsight adapter, or simulator adapter.

The library validates shared records with Pydantic and defines typed component boundaries with standard-library protocols.
The repository also provides maintained tests, a locked development environment, and documentation.
GitHub Actions runs the shared checks on Linux and macOS.
Read the [shared contract guide](docs/development/contracts.md) for conventions and examples.

The completed [P01 experiments](docs/development/platform-proof.md) record bounded ResInsight, OPM, and native-image results on one Mac.
Those experiments remain separate from the installable library and do not establish a supported host or simulator matrix.
Read the [project documentation](https://lukasmosser.github.io/resinsight-mcp/) on GitHub Pages.

## Development

Use Python 3.12 and uv for local work.
Run these commands from the repository root:

```console
uv sync --locked --all-groups
uv run pre-commit install
uv run --locked python scripts/check.py
uv run --locked mkdocs serve
```

Read the [contribution guide](CONTRIBUTING.md) before you change files.
The [local setup guide](docs/development/local-setup.md) explains the tools.
The [implementation plan](docs/development/implementation-plan.md) defines the proposed work packages.

## Project records

The repository keeps its project records in these locations:

- [Documentation source](docs/index.md)
- [Agent guide](AGENTS.md)
- [Security policy](SECURITY.md)
- [GitHub Releases](https://github.com/LukasMosser/resinsight-mcp/releases)
- [License](LICENSE)

The original project files use GPL-3.0-or-later.
Copyright 2026 Lukas Mosser and contributors.
Third-party components keep their own licenses.
