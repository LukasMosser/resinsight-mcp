# resinsight-mcp

resinsight-mcp connects an MCP-enabled agent to ResInsight workflows.
MCP is the Model Context Protocol for tool access.
Through a configured host, an agent can manage sessions and projects, inspect objects, change views, and examine fresh native images.

The project builds an agent interface for ResInsight-based modeling, simulation, and result analysis.
The [first-release plan](docs/development/implementation-plan.md#product-boundary) targets macOS and OPM Flow with explicit model and physics limits.
The [operation map](docs/development/agent-workflows.md) separates current tools from the remaining work toward that workflow.

## Start with an agent

Read the [connection guide](docs/mcp.md), then use capability discovery to find the tools your host supplies.
The supplied launcher provides workspace tools and optional [ResInsight session configuration](docs/mcp.md#enable-resinsight-sessions).
Its [model configuration](docs/mcp.md#enable-model-tools) enables supported FIELD imports and constrained model creation.
Its [OPM workflow configuration](docs/mcp.md#enable-the-opm-workflow) supplies native wells, bounded Flow jobs, verified result loading, comparisons, and native images.

The [tutorials](docs/tutorials/index.md) explain the available agent tasks:

- Manage named sessions, open and save projects, and resolve project objects.
- Create FIELD inputs and native wells, run a baseline and changed scenario, and compare their results.
- Change properties, report times, cameras, filters, and legends, then inspect native images.
- Monitor configured local jobs, request cancellation, and inspect state after reconnecting.

The [model tutorial](docs/tutorials/models.md) uses public tools to create, import, inspect, clone, and prepare fixed revisions.
The [model guide](docs/synthetic-models.md) describes the constrained layered specification and Python interface.
Its numerical acceptance compares generated inputs with the preserved reference under documented tolerances.
The [well guide](docs/wells.md) describes native well edits and separate publication of immutable simulator schedules.
The [FIELD workflow tutorial](docs/tutorials/opm.md) uses public tools for simulation, result inspection, comparison, and explicit project restoration.

Native application control and rendering run locally.
Your configured client can send prompts, tool results, metadata, and images to its model provider.
The product assumes that users have appropriate provider data sharing agreements.
The [data boundary](docs/views.md#data-boundary) explains this configuration.

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
The [development guide](docs/development/index.md) explains the service architecture, contracts, storage, tests, and acceptance evidence.
GitHub Actions runs the shared checks on Linux and macOS.

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
