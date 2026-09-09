# Agent workflow capability map

resinsight-mcp provides an MCP interface for agents to operate ResInsight.
MCP is the Model Context Protocol for tool access.
The mission covers sessions, projects, navigation, views, supported model and well setup, simulations, results, comparison, and recovery.
The eventual goal covers full ResInsight workflows.
The first release remains bounded to macOS and the supported OPM physics.

This audit covers `main` at `40b9b9f`, after P06, P07, and P10 merged.
It supports [issue #29](https://github.com/LukasMosser/resinsight-mcp/issues/29).
The [implementation plan](implementation-plan.md) owns package scope and delivery status.
This page maps that scope to current access paths and integration gaps.
It does not define tool arguments or replace runtime discovery.

## Sources of truth

The [operation catalog](https://github.com/LukasMosser/resinsight-mcp/blob/main/src/resinsight_mcp/mcp/catalog.py) owns advertised tool names and typed request bindings.
A binding supplies a service to the MCP host.
The server derives tool schemas and the `resinsight://catalog` resource from that same catalog.
Before calling tools, read the connected server's tool list and catalog resource.
Only supplied services contribute their optional tools.

The [default launcher](https://github.com/LukasMosser/resinsight-mcp/blob/main/src/resinsight_mcp/mcp/__main__.py) supplies only `Bindings.workspaces`.
Its configuration accepts an absolute `--workspace-root` and optional `--create-workspace`.
Creating a workspace does not launch ResInsight or compose other services.
A configured host calls `create_server()` or `serve_stdio()` with explicit service bindings.
Native sessions require the optional `resinsight` dependency and an explicitly configured application backend.
The [MCP guide](mcp.md) explains that boundary.

## Current operation map

“Default” means available through the packaged workspace launcher.
“Configured” means available only when a host supplies the named service.
“Python-only” means implemented library behavior without an advertised MCP tool.
“Unimplemented” means the complete operation has no current production implementation.

| Agent operation | Current access and exact tool names | Required configuration or native capability | Guide and evidence |
| --- | --- | --- | --- |
| Create and inspect durable sessions | Default: `session_create`, `session_list`, `session_get` | Local workspace storage. These tools alone do not connect to ResInsight. | [MCP guide](../mcp.md), [workspace boundary](workspaces.md), [P05 evidence](mcp-evidence.md) |
| Read a saved image observation | Default: `observation_get` | An existing observation and its stored image artifact. This does not render a new frame. | [View guide](../views.md), [P05 evidence](mcp-evidence.md) |
| Select an explicit session and inspect connections | Configured: `session_select`, `connection_list`, `connection_get` | `Bindings.sessions` with `ResInsightSessionService`. Selection does not set a default mutation target. | [Session guide](../sessions.md), [P04 evidence](p04-evidence.md) |
| Launch, attach, detach, or close ResInsight | Configured: `application_launch`, `application_attach`, `application_close` | Session service and native backend. Launch needs an application executable. Attach needs an explicit local endpoint. Termination requires verified ownership. | [Session implementation](sessions.md), [P04 evidence](p04-evidence.md) |
| Inspect, open, save, and close projects | Configured: `project_inspect`, `project_open`, `project_save`, `project_close` | Session binding and a connected native application. Mutations require the expected project context. | [Session guide](../sessions.md), [P04 evidence](p04-evidence.md) |
| Navigate known project objects | Configured: `project_inspect`, `object_resolve` | Service-issued object references and the current project context. This is object discovery and resolution, not general graphical navigation. | [Session implementation](sessions.md), [P04 evidence](p04-evidence.md) |
| Apply camera, property, report step, legend, and display filters | Configured: `view_apply` | `Bindings.views`, a connected session, trusted result binding, patched ResInsight, and its matching generated RIPS client. | [View guide](../views.md), [view boundary](views.md), [P06 evidence](p06-evidence.md) |
| Render a fresh view image | Configured: `view_render` | `Bindings.views` or `Bindings.renderer`, plus an exact stored result context. The native view service needs the P06 setup. | [View guide](../views.md), [P06 evidence](p06-evidence.md) |
| Read an observation against current native scene state | Configured: `observation_get` | With `Bindings.views`, retrieval checks current scene state. The default workspace binding only reads stored observations. | [Confirmed scenes](views.md#confirmed-scenes-and-capture), [P06 evidence](p06-evidence.md) |
| Import and prepare supported model inputs | Python-only: `OpmImportService.import_model()` and `OpmImportService.prepare()` | Optional `imports` dependency, exactly `opm==2025.10`, explicit datum, and the bounded `spe1-field-v1` profile. No MCP import tools exist. | [Import guide](model-imports.md), [P07 evidence](p07-evidence.md) |
| Submit, inspect, and cancel prepared jobs | Configured: `job_submit`, `job_poll`, `job_cancel` | `Bindings.jobs`, `DurableJobController`, trusted `CommandResolver`, and prepared stored inputs. The implemented policy requires explicit `wall_time_only`. | [Job guide](../jobs.md), [job boundary](jobs.md), [P10 evidence](p10-evidence.md) |
| Reconcile stopped job supervision | Python-only: `DurableJobController.reconcile()` | Original local workspace and applicable controller and supervisor leases. Active supervisors prevent reconciliation. No MCP reconciliation tool exists. | [Recovery boundary](jobs.md#reconciliation-boundary), [P10 evidence](p10-evidence.md) |

The [session guide](../sessions.md), [view guide](../views.md), and [job guide](../jobs.md) describe the available access paths.
Their configuration requirements remain part of each workflow.
A tool's presence does not establish native capabilities or simulator readiness.

## Important boundaries

P06 requires a trusted loader to establish the relationship between stored results and loaded native cases.
`ResInsightViewService.bind_result()` checks the supplied stored record, but cannot prove file provenance from a caller's case identifier.
No MCP tool exposes arbitrary result binding.
The [native requirements](views.md#native-patch-requirements) identify the source patch and generated client requirements.
The released RIPS package alone does not provide the added view APIs.

P06 native checks and model-facing image acceptance passed in their recorded environments.
The native editor visual inspection remains deferred to [issue #34](https://github.com/LukasMosser/resinsight-mcp/issues/34).
No native editor visual pass is claimed.
The [P06 evidence](p06-evidence.md) separates these outcomes and records the tested builds.

P07 preserves and validates supported inputs through Python services.
Its native trial ran Flow and loaded results through explicit acceptance setup.
That trial does not supply a production MCP import operation, simulator adapter, or result loader.
Its supported input physics remain the bounded black-oil profile, with oil, water, gas, and dissolved gas.
The [import guide](model-imports.md#supported-model-profile) owns the exact support restrictions.

P10 proves durable command supervision through configured production MCP transport.
Its acceptance commands are small Python processes, not simulator runs.
CPU and memory requests remain unenforced under `wall_time_only`, while the controller enforces the wall deadline.
A successful process exit does not establish numerical acceptance.
The [P10 evidence](p10-evidence.md) records those limits.

View edits change display state, not simulator inputs.
Selected well references remain view provenance metadata, which records the source of a view.
They do not create well geometry, completions, or simulator controls.
Saved observations also do not reconstruct confirmed view service state after restart.

## Gaps and proposed ownership

These assignments propose integration work within the [existing packages](implementation-plan.md#ownership-and-integration).
They do not add tool names, broaden supported physics, or authorize publication.
[Issue #35](https://github.com/LukasMosser/resinsight-mcp/issues/35) tracks launcher composition and domain MCP wiring.
This documentation change does not implement that integration.
The lead integration owner owns launcher composition and all domain-tool wiring in `src/resinsight_mcp/mcp/`.
Domain-tool wiring connects model, simulator, and result services to MCP.
Package owners supply domain services and evidence through agreed typed interfaces.
The lead integration owner also owns the combined agent acceptance sequence and configuration documentation.

| Gap | Current limit | Proposed package owner and completion evidence |
| --- | --- | --- |
| Compose the agent host | The default launcher supplies only workspace tools. Native sessions, views, and jobs require custom host composition. | Lead integration owner, with P05 transport and P17 packaging. Prove documented configuration against the advertised catalog and real native services. |
| Expose supported import and preparation | P07 has Python services without MCP tools. | P07 owner supplies import contracts and failure evidence. Lead integration owner owns catalog wiring and agent acceptance. |
| Create constrained models | No production model creation service or MCP operation exists. | P08 owner supplies supported model creation and stored revision evidence. Lead integration owner owns later MCP wiring. |
| Create wells and edit simulator schedules | View well references do not implement well setup or simulator input edits. | P09 owner supplies native well and model input services. Evidence must connect geometry, completions, controls, and immutable revisions. |
| Run OPM through prepared jobs | P10 supervises trusted commands. It does not prepare simulator commands or accept numerical results. | P11 owner supplies the OPM adapter and trusted command resolution. Lead integration owner joins preparation to the configured job tools. |
| Load results with trusted lineage | General result import and native case binding remain absent. Acceptance setup does not implement these services. | P12 owner supplies result import and verified native loading. Lead integration owner connects those services to views and MCP. |
| Compare revisions and results | No production result comparison operation exists. | P12 owner supplies comparison services and compatibility checks. Evidence must cover units, cell identity, report times, and revision relationships. |
| Extend native navigation | Current discovery and resolution do not cover full ResInsight navigation or every native feature. | Lead integration owner records bounded follow-up scope with the session and view owners before implementation. |
| Complete agent recovery | Job reconnection works, but no MCP reconciliation operation or complete workflow recovery exists. | P16 owner supplies OPM recovery acceptance. Lead integration owner owns any agreed recovery wiring and combined session, job, and result checks. |
| Prove the complete OPM agent workflow | Separate P04, P06, P07, and P10 evidence does not prove one complete production workflow. | P13 owner supplies real OPM acceptance. Lead integration owner verifies import, setup, run, loading, inspection, comparison, and recovery boundaries. |
| Inspect repaired native editors | P06 completed with the visual check deferred. | Issue #34 owner records the build and editor screenshots. This remains separate from launcher and domain integration. |

Future packages must retain explicit failures and distinct ownership of model inputs, native views, simulator execution, and MCP transport.
The integration owner must make sure that tutorials describe only operations available in their stated configuration.
The [test guide](testing-and-review.md) defines required checks and evidence review.
