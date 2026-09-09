# View control boundary

P06 lets an MCP-enabled agent apply native view settings and inspect fresh image responses.
The implementation separates session ownership, native view control, observation storage, and MCP transport.
The [user guide](../views.md) describes current operations and outcomes.

## Ownership and trusted results

`ResInsightSessionService.access_objects()` holds session access while it resolves all requested references.
`RipsViewBackend` uses that access and the existing deadline-bound `RipsApplication` client.
It does not open another channel, choose another endpoint, or own application lifetime.
Cases and views resolve through exact project object addresses.
The adapter checks the selected view's case address separately.
It does not use the upstream case-filtered view helpers.

`ResInsightViewService.bind_result(LoadedResult)` is a trusted loader boundary.
It verifies that the supplied result equals the stored result and associates that result with the loaded case.
It cannot establish file provenance from a caller-provided case identifier alone.
The host integration must establish that relationship before calling it.
No MCP operation exposes arbitrary result binding.
Bindings and confirmed scene versions belong to the service instance.

The service verifies the result, revision, grid identity, report membership, units, and coordinate metadata before native edits.
`PRESSURE` supports only stored `FIELD` inputs with `psi`.
`SWAT`, `SGAS`, `SOIL`, and `PORO` require unit `1`.
Pressure and saturations use `DYNAMIC_NATIVE`, while porosity uses `STATIC_NATIVE`.
Unit metadata comes from the trusted revision rules, not an invented native unit getter.

## Bind the services

This function accepts an existing workspace and its application session service.
The host must create or attach the application and establish trusted result bindings before serving view requests.
The example does not invent a result loader or open another native connection.

```python
from resinsight_mcp.contracts.interfaces import WorkspaceStore
from resinsight_mcp.mcp import Bindings
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.views import ResInsightViewService
from resinsight_mcp.resinsight.views.rips import RipsViewBackend


def bind_views(
    store: WorkspaceStore,
    sessions: ResInsightSessionService,
) -> tuple[Bindings, ResInsightViewService]:
    views = ResInsightViewService(store, sessions, RipsViewBackend())
    bindings = Bindings(workspaces=store, sessions=sessions, views=views)
    return bindings, views
```

The returned service accepts `bind_result(loaded_result)` after the trusted loader establishes the case relationship.
Make sure that this operation succeeds before exposing the view to callers.
Pass the bindings to the existing `create_server()` or asynchronous `serve_stdio()` entry point.
These bindings expose `view_apply`, `view_render`, and current-scene observation retrieval.

## Model provider boundary

Application control, rendering, and MCP transport run locally in this configuration.
A configured API client can send prompts, tool results, metadata, and rendered images to its model provider.
The product assumes that users have appropriate data sharing agreements for that provider.
This data boundary does not create an additional approval step in view operations.
The P06 observer uses the existing authenticated OpenAI/Codex account with public SPE1-derived images and required view metadata.

## Native patch requirements

The adapter requires a rebuilt application and the generated RIPS package from that build.
Matching the released package version alone does not establish these capabilities.
The [source patch](evidence/p06/native/view-controls.patch) targets ResInsight commit `197d58a750dd0bc243025b3939ab2a8a01a2c709`.
Apply it before building with the [proved macOS configuration](platform-resinsight.md#approved-build-path).
The [native record](p06-evidence.md#native-controls) identifies the tested source and generated client.
The native extension exposes these supported APIs:

- `validate_view_controls()` rejects unsupported native control states before mutation.
- `set_camera_projection()` sets projection, field of view, and full parallel projection height.
- `actual_camera_field_of_view_y_degrees` and `actual_camera_parallel_projection_height` report native camera values.
- `cell_result().result_var_legend_definition_list()` resolves legends through `result_variable_usage`.
- Legend fields expose explicit bounds, mapping mode, precision, centering, and actual mapper bounds.
- `range_filters().cell_filters()` exposes display filters through their supported native collection.
- Filter fields expose `filter_type` and zero-based `grid_index`.

The adapter requires explicit capabilities and rejects their absence.
Projection changes validate numeric arguments before native mutation.
The camera matrix uses CAF row-major text serialization and OpenGL look-at geometry.
Readback rejects matrices whose direction disagrees with their point of interest.
Camera coordinates remain native display coordinates, with no physical coordinate conversion.

The legend uses `USER_DEFINED_MAX_MIN`, `LinearContinuous`, `center_legend_around_zero=False`, and precision `15`.
Changing the range mode precedes a fresh legend read and a separate bounds update.
This avoids the native mode transition replacing newly supplied bounds.
Readback uses `actual_minimum` and `actual_maximum`, rather than treating stored inputs as rendered bounds.

Display filters support the main grid and the collection's `AND` mode.
Contract indices are zero-based and inclusive, while native range starts are one-based.
Each filter specifies `INCLUDE` or `EXCLUDE`.
Selected imported or modeled wells resolve against project well path addresses and remain provenance metadata.
Selection does not claim a visibility API or a simulator edit.

## Confirmed scenes and capture

Validation precedes mutation under session access.
After an edit, native readback must agree with the requested supported state before the service records a receipt.
Uncertain mutation failures retain effect `unknown`.
Connection and deadline errors retain their typed failure codes.
A confirmed edit remains successful when its later observation capture fails.

The capture path creates a new export directory for each observation.
It requires exactly one PNG, decodes it, and checks the requested dimensions.
The service checks native state again after export before publishing the observation.
Stored metadata includes result identity, scene context, actual display settings, dimensions, and UTC capture time.
No failure reads an earlier image as a new observation.

Render and observation retrieval compare the saved context with current native state.
A failed inspection invalidates the scene, including failures that cannot return a comparable context.
External edits therefore require a new complete apply request.
Scene state is not reconstructed from saved observations after service restart.

## Scope and evidence

P06 required upstream API additions for projection control, actual camera values, legends, filter access, and native control validation.
The native patch also initializes newly scripted filters and switches legends when script calls load another result.
These additions preserve ownership of simulator inputs and result loading outside the view adapter.
The bounded property set and `FIELD` pressure restriction avoid unsupported unit claims.

Maintained tests cover service outcomes, capture failures, camera geometry, and fixture-only native validation.
Those tests do not establish real application rendering or reservoir model acceptance.
Native runtime evidence must identify the rebuilt application, matching generated client, inputs, tested commit, logs, and inspected images.
Model acceptance remains separate from successful view control and image decoding.
Follow the [test guide](testing-and-review.md) before integrating changes.
