# ResInsight views

The view service applies complete display settings and returns a new image with its observed context.
A scene version identifies one confirmed set of display settings.
Every request identifies its model revision, stored result, case, view, and scene version.
View edits do not change simulator inputs or run a simulator.

## Requirements

Use the rebuilt ResInsight application and its matching generated RIPS client.
RIPS is the Python client for ResInsight remote calls.
The unmodified released client does not provide all required view capabilities.
The [developer guide](development/views.md) lists the required native APIs.
The [session guide](sessions.md) describes application connections and process checks.

A trusted application loader must bind the loaded case to its stored result before view operations.
This binding is an application integration responsibility.
The MCP tools do not create this binding from caller claims.
MCP is the Model Context Protocol for tool access.

## Supported settings

`PRESSURE` requires a stored `FIELD` revision and uses `psi`.
`SWAT`, `SGAS`, `SOIL`, and `PORO` use the dimensionless unit `1`.
The native case must contain the requested property in its supported result category.
The report index, calendar date, and elapsed days must match the native case and stored result.
The coordinate metadata must match the stored revision.

The camera uses native display coordinates.
Its position and target do not provide a conversion from reservoir coordinates.
Perspective cameras require a field of view in degrees.
Orthographic cameras require `parallel_scale`, which equals half the visible vertical extent.
Vertical exaggeration controls the native grid Z scale.

Legend bounds use the property's unit.
The adapter selects a continuous linear legend without centering its range around zero.
The returned context records the actual native legend bounds.
Display filters use zero-based, inclusive I, J, and K bounds on the main grid.
The collection uses `AND`, with an explicit include or exclude choice for each range.

`selected_wells` records resolved modeled-well identities.
It does not change well visibility, geometry, or simulator inputs.
The selected view must belong to the selected case.
Linked views, controlled views, and unsupported native filter states prevent view control.

## Apply and render

Use `view_apply` with a complete `ViewUpdateRequest`.
Use scene version `0` for a view without a confirmed edit in the current service.
For later edits, use the version from the last edit receipt.
An optional `expected_observation_id` requires that observation's scene to remain current.

A successful edit advances the scene version once.
Its receipt contains the actual native context after the edit.
The operation then exports a fresh PNG at the requested dimensions.
The service decodes the image and checks its dimensions before saving an observation.
It also checks native scene state after export.

Use `view_render` to capture the current confirmed context without applying settings.
Reuse the returned context rather than reconstructing it from an earlier request.
`observation_get` retrieves a saved observation without rendering a new frame.
With the view service bound, retrieval also requires the observation's native scene to remain current.

## Failures and recovery

A changed native scene makes earlier observations stale.
Reconnecting, replacing the project, or using another result can also invalidate object references.
A stale observation cannot serve as proof of the current scene.
Apply a new complete request using current references and the latest confirmed scene version.

A rejected request returns a typed failure.
`invalid_model` reports inconsistent requested metadata or filter bounds.
`unsupported_operation` reports unsupported properties, unit systems, or missing native capabilities.
`busy` and `lost_connection` report native call failures.
An uncertain edit has effect `unknown`, so it must not be treated as an unchanged view.

An image failure after a confirmed edit preserves the successful edit receipt.
In that outcome, `EditedView.observation` contains a failure instead of an image.
The service never substitutes an earlier PNG for a failed capture.
Make sure that both the edit outcome and observation outcome succeed before using an image as evidence.
