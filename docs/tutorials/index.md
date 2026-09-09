# Work with an agent

Use these tutorials to ask an MCP-enabled agent to control an existing ResInsight setup.
MCP is the Model Context Protocol for tool access.
The agent sends explicit requests and checks their outcomes before continuing.

## Start with a configured host

The supplied launcher exposes workspace tools and can enable ResInsight sessions through [documented configuration](../mcp.md#enable-resinsight-sessions).
The session tutorial uses that configuration and a compatible ResInsight application.
The model tutorial uses `--enable-models` and the pinned OPM parser.
View and job tutorials require a host integrator to supply their services and trusted inputs.
The [integration guide](../development/mcp.md) explains those additional bindings.
The [local setup guide](../development/local-setup.md) describes the development environment.

Ask your agent:

> List the available tools and read `resinsight://catalog`.
> Tell me which tutorial prerequisites this server provides.

The catalog contains the current request and response schemas.
Optional tools appear only when the host supplies their services.
If a required tool is absent, inspect the launcher configuration or the host's supplied services.
A prompt cannot enable an absent service.

## Choose a task

| Task | Required setup | Tutorial |
| --- | --- | --- |
| Find a named session and open its project | Launcher ResInsight configuration and compatible ResInsight | [Sessions and projects](sessions.md) |
| Import, create, inspect, clone, and prepare a model | Launcher model configuration and pinned OPM parser | [Model inputs](models.md) |
| Compare report times and inspect returned images | Session and view services, native capabilities, and trusted result binding | [Views and image comparison](views.md) |
| Follow or cancel an existing local job | Job controller and trusted command resolver | [Jobs and reconnect](jobs.md) |

The workspace launcher supports `session_create`, `session_list`, `session_get`, and `observation_get`.
Saved observation retrieval does not capture a new image.
The [workspace launcher guide](../mcp.md) provides the startup command.

## Read each response

A successful tool response contains `outcome.status: success` and `outcome.value`.
A failure contains `outcome.status: failure` and an error record.
Check the error code and mutation effect before retrying.
An `unknown` effect means the operation's complete outcome is uncertain.
A confirmed view edit can succeed even when its image capture fails.

The client must preserve native image content alongside response metadata.
A path or text description does not replace an image the agent can inspect.
Keep identifiers from current responses instead of reusing identifiers from these examples.
Each tutorial labels templates and historical excerpts explicitly.

## Understand the data boundary

ResInsight and the MCP server run locally.
The configured client can send prompts, tool results, metadata, and images to its model provider.
Users operate under data sharing agreements with their configured provider.
The product adds no separate approval flow for that provider transfer.

See the [operation map](../development/agent-workflows.md) for work beyond these current tutorials.
