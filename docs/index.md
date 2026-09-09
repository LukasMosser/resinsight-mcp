# resinsight-mcp

resinsight-mcp connects an MCP-enabled agent to ResInsight workflows.
MCP is the Model Context Protocol for tool access.
Through a configured host, an agent can manage sessions and projects, inspect objects, change views, and examine fresh native images.

The project builds an agent interface for ResInsight-based modeling, simulation, and result analysis.
The [first-release plan](development/implementation-plan.md#product-boundary) targets macOS and OPM Flow with explicit model and physics limits.

## Start with your connection

Use the [connection guide](mcp.md) to connect an MCP client and discover its available tools.
The supplied launcher currently provides workspace tools.
ResInsight sessions, views, and local jobs require a separately configured host with their required services.
A complete model-to-simulation workflow is not yet available through the supplied launcher.

The [operation map](development/agent-workflows.md) records the current tools, required configuration, evidence, and remaining integration work.

## Choose a task

The [tutorials](tutorials/index.md) use implemented tools and identify the setup each task requires.

- [Manage sessions and projects](tutorials/sessions.md): open, save, reopen, and find the objects your agent will use.
- [Inspect and change views](tutorials/views.md): compare properties and report times with fixed legends, filters, cameras, and native images.
- [Monitor local jobs](tutorials/jobs.md): inspect progress, request cancellation, and recover the same job identity after reconnecting.

The [session reference](sessions.md), [view reference](views.md), and [job reference](jobs.md) describe outcomes and supported limits.

## Know where information goes

ResInsight control, rendering, and MCP tools can run locally while the client uses a remote model API.
Depending on the client configuration, prompts, tool results, metadata, and images can reach the model provider.
The product assumes that users have appropriate provider data sharing agreements.
The [data boundary](views.md#data-boundary) explains this configuration.

## Develop and verify

The [development guide](development/index.md) covers the architecture, shared contracts, storage, and package ownership behind the agent tools.
Its acceptance records distinguish service tests, native application trials, and model-visible image evidence.
The [local setup guide](development/local-setup.md) explains installation, tests, and documentation preview.
The [contribution policy](https://github.com/LukasMosser/resinsight-mcp/blob/main/CONTRIBUTING.md) explains how to propose a change.
