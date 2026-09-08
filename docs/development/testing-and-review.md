# Testing and review

Tests must establish behavior that matters to a user.
The maintained pytest suite exercises contracts, workspace storage, session coordination, and the native client's remote call boundary.
Do not add placeholder tests to increase a test count.

The shared command `scripts/check.py` runs Ruff, ty, pytest, and the strict documentation build.
The CI jobs use that same command on Linux and macOS.
The backend tests start separate protocol fixture processes and exercise the native client with supported remote calls.
The default suite does not launch ResInsight or a simulator.
The [P04 record](p04-evidence.md) reports separate real application acceptance.
MCP tests launch real SDK client and server processes with explicit test services.
The [P05 record](mcp-evidence.md) reports separate blind image acceptance through the production transport.

For contract changes, exercise valid records, rejected inputs, serialization, and relationships between identifiers and states.
Make sure that a successful edit remains distinguishable from a failed observation.
Protocol typing establishes interface shape, not a working external implementation.
The [contract guide](contracts.md) defines these boundaries.

Workspace tests use real temporary databases and files through the public store API.
For storage changes, exercise fresh-process reopening, competing writes, immutable clones, rejected paths, and interrupted artifact writes.
Use parsed text or JSON to establish meaningful file content.
Recovery tests must distinguish stopped-controller reconciliation from merely opening another store.
The [workspace guide](workspaces.md) defines the supported filesystem boundary and recovery preconditions.

For a behavior change, choose evidence that exposes an incorrect result:

- Exercise the intended result with representative inputs.
- Exercise relevant failures and boundary conditions.
- Make sure that state changes affect only the intended session, model, or run.
- Make sure that reported errors describe the actual outcome.

Test coverage measures which code a test executes.
Do not pursue 100% coverage as a goal.
A passing test must establish a useful property beyond repeating the implementation.

Do not add byte-level checks or comparisons.
Use document builds, visual inspection, and meaningful content assertions where they apply.
For numerical results, define justified tolerances and record the source of reference values.

A fallback is an alternate action after failure.
Do not add fallback behavior.
A failed render must not return a previous image as a new observation.

Review the change for these concerns:

- Remove unnecessary duplication.
- Reduce complexity that obscures behavior.
- Keep responsibilities clear enough for later maintenance.
- Make failures visible and state transitions understandable.
- Keep dependencies and abstractions proportional to the current need.

Run `uv run --locked python scripts/check.py` before submitting a change.
Record the command outcome and any limits in the review description.
For rendered content, inspect the affected pages in a browser.

Separate source inspection from runtime evidence.
A documented API does not prove that an integration works.
For external applications, record the tested versions, environment, inputs, commands, and observed outputs.

The [P01 platform record](platform-proof.md) contains the completed experiments on one macOS host.
Those runtime records do not replace maintained library tests or prove future adapters.
Report observed test results and their scope, rather than inferring success from test files or interface declarations.
