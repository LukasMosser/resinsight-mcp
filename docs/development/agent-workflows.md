# Agent workflow capability map

resinsight-mcp provides an MCP interface for agents to operate ResInsight.
MCP is the Model Context Protocol for tool access.
The first release targets macOS and the supported OPM physics.
The [implementation plan](implementation-plan.md) owns package scope and acceptance requirements.
This map follows [issue #35](https://github.com/LukasMosser/resinsight-mcp/issues/35) and records implemented access paths and remaining acceptance work.
It does not replace runtime discovery or claim that separate service checks establish the complete workflow.

## Sources of truth

The [operation catalog](https://github.com/LukasMosser/resinsight-mcp/blob/main/src/resinsight_mcp/mcp/catalog.py) owns advertised tool names and typed request bindings.
A binding supplies a service to the MCP host.
Tool discovery and `resinsight://catalog` derive their schemas from the same records.
Before calling tools, read the connected server's tool list and catalog resource.
Only supplied services contribute their optional tools.
No tool accepts an arbitrary shell command, Python callback, or native address for trusted result binding.

The [shipped launcher](https://github.com/LukasMosser/resinsight-mcp/blob/main/src/resinsight_mcp/mcp/__main__.py) always supplies workspace storage.
Its [configuration](../mcp.md) enables these additional service groups:

| Configuration | Supplied services |
| --- | --- |
| Default workspace | Durable sessions and saved observations. |
| `--resinsight-log-directory` | Native sessions, application lifecycle, projects, and object references. |
| `--enable-models` | FIELD input import, constrained creation, inspection, preparation, and cloning. |
| `--enable-opm-workflow` with native logs | All preceding services, native wells, schedules, Flow jobs, accepted results, comparisons, and views. |

The full workflow requires the pinned OPM parser, reviewed native build, matching generated RIPS wheel, local pinned Flow image, and Docker.
An optional `--docker-executable` selects one absolute executable path within the full workflow configuration.
Startup checks required dependencies before opening workspace storage.
Startup does not launch ResInsight, start a container, or pull an image.
A custom host can also supply reviewed service bindings through `create_server()` or `serve_stdio()`.

## Current operation map

“Default” means available through the packaged workspace launcher.
“Sessions” and “Models” refer to the optional configurations above.
“OPM workflow” means the full launcher configuration.
“Python-only” means implemented library behavior without an advertised MCP tool.

| Agent operation | Current access and exact tool names | Required boundary | Guide |
| --- | --- | --- | --- |
| Create and inspect durable sessions | Default: `session_create`, `session_list`, `session_get` | Local workspace records. These tools do not connect to ResInsight. | [Workspace guide](workspaces.md) |
| Read a saved image | Default: `observation_get` | Existing observation and stored image. A configured view service also checks current scene state. | [View guide](../views.md) |
| Select sessions and inspect connections | Sessions: `session_select`, `connection_list`, `connection_get` | Explicit session identity. Selection never supplies another request's target. | [Session guide](../sessions.md) |
| Launch, attach, detach, and close applications | Sessions: `application_launch`, `application_attach`, `application_close` | Verified endpoint and process identity. Termination requires service ownership. | [Session implementation](sessions.md) |
| Inspect, open, save, and close projects | Sessions: `project_inspect`, `project_open`, `project_save`, `project_close` | Connected native application and current expected project context. | [Session tutorial](../tutorials/sessions.md) |
| Resolve current project objects | Sessions: `project_inspect`, `object_resolve` | Current service-issued object references. This is bounded discovery, not complete graphical navigation. | [Session implementation](sessions.md) |
| Import and prepare FIELD inputs | Models: `model_import`, `model_prepare` | Pinned parser, supported input profile, and explicit datum. | [Model tutorial](../tutorials/models.md) |
| Read, inspect, and clone revisions | Models: `model_get`, `model_inspect`, `model_clone` | Exact stored identity. Cloning retains inputs under a new revision identifier. | [Model tutorial](../tutorials/models.md) |
| Create a constrained layered model | Models: `model_template`, `model_create` | FIELD specification, one injector, one producer, and fixed supported fluid template. | [Model guide](../synthetic-models.md) |
| Load or restore prepared cases | OPM workflow: `model_load_case`, `model_restore_case` | Persistent grid sources, immutable receipts, exact model, and current project context. | [Well guide](../wells.md) |
| Create, update, inspect, and adopt native wells | OPM workflow: `well_create`, `well_update`, `well_inspect`, `well_adopt` | Verified case binding, FIELD coordinates, native geometry, and expected well version. | [Well guide](../wells.md) |
| Export and retrieve native completions | OPM workflow: `well_export`, `well_export_get` | Immutable native connection records tied to exact source geometry and model. | [Well guide](../wells.md) |
| Publish a child schedule | OPM workflow: `model_publish_schedule` | Verified exports and supported controls at existing report indices. | [Schedule boundary](well-schedules.md) |
| Submit, poll, and cancel Flow jobs | OPM workflow: `job_submit`, `job_poll`, `job_cancel` | Prepared fixed inputs, bounded limits, pinned image, and verified Docker ownership. | [OPM guide](../opm.md) |
| Assess and collect accepted outputs | OPM workflow: `opm_collect` | Confirmed successful job, complete outputs, exact lineage, and numerical acceptance policy. | [OPM implementation](opm.md) |
| Read, load, and restore results | OPM workflow: `result_get`, `result_load`, `result_rebind` | Immutable output files and verified native values, reports, and geometry. | [Result guide](../results.md) |
| Query cells and curves | OPM workflow: `result_cell_property`, `result_curve` | Accepted result with explicit property or curve identity and supported units. | [Result guide](../results.md) |
| Compare result scenarios | OPM workflow: `result_compare_cells`, `result_compare_curves` | Matching geometry, reports, quantities, units, and session. Cell comparison returns one common legend. | [Result guide](../results.md) |
| Discover current result views | OPM workflow: `view_list` | Current trusted loaded result and actual native case ownership. Returns cameras without changing display state. | [View boundary](views.md) |
| Apply and capture native views | OPM workflow: `view_apply`, `view_render` | Current model, result, case, view, scene version, and complete settings. | [View tutorial](../tutorials/views.md) |
| Create a native summary image | OPM workflow: `result_show_curve` | Verified curve and native summary case. Applied receipt remains separate from image outcome. | [Result guide](../results.md) |
| Reconcile stopped job supervision | Python-only: `DurableJobController.reconcile()` | Original workspace and applicable controller and supervisor leases. Active supervisors prevent reconciliation. | [Job recovery](jobs.md#reconciliation-boundary) |
| Run trusted native mutations | Python-only: `ResInsightSessionService.mutate_project()` | Trusted domain callback with session ownership and reference refresh. No callback tool exists. | [Mutation boundary](session-mutations.md) |

The [FIELD workflow tutorial](../tutorials/opm.md) orders model, well, simulation, result, comparison, and recovery operations.
A tool's presence establishes configured implementation, while separate acceptance records establish observed runtime behavior.

## Important boundaries

Model inputs, native display state, simulator execution, and MCP transport retain separate owners.
Native well edits and completion exports do not change simulator inputs.
Schedule publication creates a separate immutable child revision with explicit controls.
Selected well references record object existence and do not change visibility.

Prepared grid sources and accepted result bundles remain at their canonical paths for saved projects.
Restoration verifies current native content before issuing fresh bindings.
Case display names and old references never establish model or result identity.
The [persistent well evidence](evidence/p09/lifetime/README.md) records the bounded source and well lifetime checks.

Flow jobs use independent supervisors and survive MCP server restart.
Process success remains separate from accepted simulation results and independent numerical reference agreement.
The [P11 record](evidence/p11/README.md) preserves actual runtime trials and reference comparisons.
P12 native loading verifies output semantics and complete geometry through its separate service boundary.

Native application ownership remains with the session service that launched the application.
Before restarting that server, save the native project and terminate its owned application through the public close tool.
After reconnecting, launch a fresh owned application, reopen the saved project, and explicitly restore case and result bindings.
Old observations do not recreate confirmed native scene state.
The public catalog exposes no automatic reconciliation or attached-process termination override.

## Gaps and proposed ownership

The lead owns launcher composition and domain-tool wiring in `src/resinsight_mcp/mcp/`.
Package owners retain domain algorithms behind typed interfaces.
The [delivery plan](p13-delivery.md) records scope changes and remaining acceptance gates.

| Remaining work | Owner and completion evidence |
| --- | --- |
| Complete native result acceptance | P12 verifies real pressure, saturation, curves, comparisons, and saved project restoration with exact run identities. |
| Prove the complete public workflow | P13 runs the shipped launcher from a clean installation and preserves every domain request, response, image, and recovery result. |
| Complete broader job recovery | P16 supplies OPM recovery acceptance and any agreed reconciliation interface. Current job tools expose explicit state and cancellation. |
| Extend native navigation | The lead agrees bounded scope with session and view owners before adding further native operations. |
| Inspect repaired native editors | [Issue #34](https://github.com/LukasMosser/resinsight-mcp/issues/34) records the deferred build and editor screenshots. |
| Produce an installable release | P17 verifies supported installation and distribution after P13 and OPM recovery acceptance. |

Required checks and independent evidence review must pass before the corresponding work issues close.
The [test guide](testing-and-review.md) defines these requirements.
