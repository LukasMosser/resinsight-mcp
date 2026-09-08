# Testing and review

Tests must establish behavior that matters to a user.
The foundation has no application behavior to test.
Do not add placeholder application tests to increase a test count.

For a behavior change, choose evidence that exposes an incorrect result:

- Exercise the intended result with representative inputs.
- Exercise relevant failures and boundary conditions.
- Make sure that state changes affect only the intended session, model, or run.
- Make sure that reported errors describe the actual outcome.

Test coverage measures which code a test executes.
Do not pursue 100% coverage as a goal.
A passing test must establish a useful property beyond repeating the implementation.

Do not use byte-level comparisons for documentation or images.
Use document builds, visual inspection, and meaningful content assertions where they apply.
For numerical results, define justified tolerances and record the source of reference values.

A fallback is an alternate action after failure.
Do not add fallback behavior that hides a failed operation.
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
