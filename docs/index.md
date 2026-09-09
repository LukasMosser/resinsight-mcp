# resinsight-mcp

resinsight-mcp connects an MCP-enabled agent to ResInsight workflows.
MCP is the Model Context Protocol for tool access.
Through a configured host, an agent can manage sessions and projects, inspect objects, change views, and examine fresh native images.

The project builds an agent interface for ResInsight-based modeling, simulation, and result analysis.
The [first-release plan](development/implementation-plan.md#product-boundary) targets macOS and OPM Flow with explicit model and physics limits.

## Start with your connection

Use the [connection guide](mcp.md) to connect an MCP client and discover its available tools.
The supplied launcher provides workspace tools and optional [ResInsight session configuration](mcp.md#enable-resinsight-sessions).
Its [model configuration](mcp.md#enable-model-tools) enables supported FIELD imports and constrained model creation.
Its [OPM workflow configuration](mcp.md#enable-the-opm-workflow) adds native wells, bounded Flow jobs, verified results, comparisons, and fresh images.

The [operation map](development/agent-workflows.md) records the current tools, required configuration, evidence, and remaining integration work.

## Choose a task

The [tutorials](tutorials/index.md) use implemented tools and identify the setup each task requires.

- [Manage sessions and projects](tutorials/sessions.md): open, save, reopen, and find the objects your agent will use.
- [Create and prepare models](tutorials/models.md): import or generate FIELD inputs, inspect them, and clone immutable revisions.
- [Run the FIELD workflow](tutorials/opm.md): publish native completions, run a baseline and changed scenario, compare results, and restore project bindings.
- [Inspect and change views](tutorials/views.md): compare properties and report times with fixed legends, filters, cameras, and native images.
- [Monitor local jobs](tutorials/jobs.md): inspect progress, request cancellation, and recover the same job identity after reconnecting.

The [session reference](sessions.md), [view reference](views.md), and [job reference](jobs.md) describe outcomes and supported limits.
The [model guide](synthetic-models.md) describes the constrained specification, fixed physics template, and Python interface.
The [well guide](wells.md) describes native well edits and separate publication of immutable simulator schedules.
The [OPM guide](opm.md) and [result guide](results.md) explain runtime limits, accepted outputs, exact result identity, and numerical comparisons.

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
