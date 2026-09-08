# Testing and review

Tests must establish behavior that matters to a user.
The maintained pytest suite exercises the contracts library's public behavior and important validation failures.
Do not add placeholder tests to increase a test count.

The shared command `scripts/check.py` runs Ruff, ty, pytest, and the strict documentation build.
The CI jobs use that same command on Linux and macOS.
The contract tests do not launch external applications or establish adapter behavior.

For contract changes, exercise valid records, rejected inputs, serialization, and relationships between identifiers and states.
Make sure that a successful edit remains distinguishable from a failed observation.
Protocol typing establishes interface shape, not a working external implementation.
The [contract guide](contracts.md) defines these boundaries.

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
