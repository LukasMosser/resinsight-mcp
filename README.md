# resinsight-mcp

This repository contains the development foundation for a ResInsight MCP integration.
MCP is the Model Context Protocol for tool access.
There is no application server or installable application release in this repository.

The foundation provides a locked Python tool environment, code review rules, and documentation.
GitHub Actions runs repository checks and builds the documentation.
Developer plans describe the proposed application separately from current behavior.

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
