# Session-owned project mutations

[Issue #41](https://github.com/LukasMosser/resinsight-mcp/issues/41) extends P04 for trusted domain services that change native projects.
The lead transferred the session boundary, focused tests, and this guide to one owner for this change.
The P09 owner agreed to the interface described here.
Native well behavior, model records, and MCP wiring remain outside this change.
MCP is the Model Context Protocol for tool access.

## Interface and ownership

`ResInsightSessionService.mutate_project(context, change)` accepts an explicit `ApplicationContext` and a trusted Python callback.
The callback has the type `Callable[[ApplicationAccess], T]`.
The method returns `ProjectMutation[T]` and raises `ContractError` on reported failure.
`ProjectMutation` contains the callback's `value` and a refreshed `access` mapping.
These records belong to the internal application boundary in `sessions._backend`.
This interface does not expose arbitrary callbacks through MCP.

The optional keyword-only `validate` callback receives `ProjectMutation[T]` after reference refresh and before ownership ends.
Domain services use it to check that returned native addresses exist in the new mapping.
This P09 review addition keeps final result failures within session failure handling.

The service verifies the connected process lifetime and current project context before invoking the callback.
It holds the existing session and application locks through both the callback and the final observation.
The callback receives the application, complete project state, and corresponding native objects in matching order.
An empty project supplies an empty object mapping, so creation does not require a preexisting object reference.
Another session connected to another application can continue independently.

After the callback succeeds, the service advances the project generation and issues new object references before releasing ownership.
Generation means the version of the session's observed project.
This refresh occurs even when the observed object inventory stays identical.
It invalidates references after edits that the inventory cannot reveal.
The returned mapping lets callers match native addresses to the new references.
Callers must reacquire `access_objects` with those references before subsequent native work.

The returned application handle does not extend the mutation's lock lifetime.
The existing `access_objects` interface still requires explicit nonempty object references.
Its behavior and the view service remain unchanged.

## Failure behavior

A stale context fails before the callback, with `STALE_OBJECT` and `NOT_APPLIED`.
A changed process identity also prevents the callback and retires the connection through the existing connection rules.
Known callback `ContractError` failures keep their error and mutation effect.
An unexpected callback exception becomes `EXECUTION_FAILED` with effect `UNKNOWN`.
An uncertain mutation retires the connection and requires attachment again before further native work.

If final observation fails after a completed callback, the service reports `UNKNOWN` and retires the connection.
A known observation error keeps its error code while receiving the uncertain effect.
An unexpected observation exception becomes `EXECUTION_FAILED` with effect `UNKNOWN`.
The service does not claim rollback or reuse the previous project mapping as a fresh result.

If final validation fails, the service reports `UNKNOWN` and retires the connection because the mutation already completed.
Known validation errors keep their code, while unexpected errors become `EXECUTION_FAILED`.

## Tests and evidence

The new tests exercise the public service boundary with controlled application doubles.
They cover creation from an empty project, complete mapping, and renewed access through fresh references.
They reject stale contexts and changed process lifetimes before callbacks run.
They make sure that mutation, refresh, and validation exclude same-session access while another session remains usable.
They also cover invisible edits, known unapplied failures, uncertain callback failures, and failed observation after completed changes.
No test launches a native process.

The [focused test log](evidence/session-mutations/focused-tests.log) records ten passing cases.
The [final validation log](evidence/session-mutations/final-validation/focused-tests.log) records twelve passing cases after the P09 review addition.
Its [environment record](evidence/session-mutations/final-validation/environment.json) identifies the changed source and failure coverage.

The [shared check log](evidence/session-mutations/shared-check.log) records repository checks, including existing session and view tests.
The [environment record](evidence/session-mutations/environment.json) contains commands, versions, source base, and working state.
The [dependency log](evidence/session-mutations/dependency-sync.log) records the locked environment installation.
The source base is `02edbd4`, with the mutation implementation and tests recorded as local changes before their commit.

The initial review retained the preliminary mutation implementation.
P09 review then added final result validation under ownership and two failure cases.
An [independent public probe](evidence/session-mutations/final-validation/independent-probe.json) distinguishes stale failures before edits from failures after completed mutation.
Its [test log](evidence/session-mutations/final-validation/independent-tests.log) records twelve passing focused cases.

It assessed duplicate behavior, control flow, names, ownership, coupling, failure handling, and public tests.
The change reuses the existing lock, observation, generation, and connection-retirement paths.
These library tests do not establish native P09 acceptance or Linux and macOS CI results.
