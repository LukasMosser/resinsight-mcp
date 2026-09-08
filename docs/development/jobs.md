# Durable job implementation

The `jobs` package executes trusted commands in one local workspace on macOS and Linux.
`DurableJobController` owns submission, stored observation, cancellation intent, and explicit reconciliation.
A separate supervisor owns each command's lifetime.
The resolver owns command selection through the public `CommandResolver` and `JobCommand` interfaces.
Simulator preparation and numerical acceptance remain outside this package.

## Submission and persistence

Submission checks the explicit resource policy and exact stored model revision before resolving the command.
The controller saves a `queued` job before it launches the supervisor.
The saved submission includes arguments, working directory, limits, policy, and submission time.
It returns that recorded job after supervisor launch.
An uncertain launch does not authorize another launch.

A session controller lease coordinates submission with reconciliation.
A job supervisor lease passes to the new supervisor through an inherited file descriptor.
The lock uses `flock`, an operating system file locking API.
Closing the controller's descriptor preserves the supervisor's inherited lock.
The supervisor makes sure that the inherited descriptor identifies the expected lease file.
These locks require the same local workspace and unchanged lease files.

Stored updates use compare-and-swap, a write conditional on the previous record.
Conflicting updates repeat only when storage confirms that the attempted write did not apply.
Uncertain writes do not repeat automatically.
This preserves concurrent cancellation intent during supervisor updates.
`poll` only reads storage.
`request_cancel` records intent and leaves terminal jobs unchanged.

## Process ownership

The supervisor launches the command without a shell in a new process group.
It retains the direct child without reaping it until the group has no live members.
Reaping collects a stopped child's exit status.
The retained child anchors ownership before each group signal.
Saved PIDs alone never authorize signals or attachment.

The supervisor must exclusively own child reaping and retain default `SIGCHLD` handling.
`SIGCHLD` reports changes in child process state.
Commands and descendants must remain in their original process group.
Processes that escape that group fall outside the supported execution boundary.
This design provides lifecycle ownership, not a process sandbox.

Group inspection checks process identities and live membership.
An empty observation requires two matching process identity inventories.
Process churn can prevent a stable observation and produce an unknown outcome.
An unavailable ownership check cannot establish termination.
The controller does not replace uncertain observations with success claims.

## Deadlines and cancellation

`ResourcePolicy.ENFORCE` remains the request default and is rejected by this controller.
`ResourcePolicy.WALL_TIME_ONLY` explicitly accepts unenforced CPU and memory requests.
The submission and supervisor log record those requests.
A timer starts after command launch, before storage publishes the running state.
The timer enforces the wall deadline independently of storage waits.

The supervisor reads durable cancellation intent during observation.
Cancellation and wall expiry share serialized stop handling.
Stop handling sends `SIGTERM`, waits 0.5 seconds, and sends `SIGKILL` when needed.
It then waits up to five seconds for an empty group observation.
Signals require current ownership checks.
An unconfirmed stop produces uncertainty instead of a canceled claim.

A confirmed cancellation produces `canceled`.
A wall deadline or nonzero exit produces `failed`.
A zero exit with no live group members produces `succeeded`.
Execution success does not accept numerical results.
Cancellation can complete before command launch when the supervisor first observes the request.

## Logs and failures

Each runtime directory contains separate stdout, stderr, and supervisor spool logs.
Spool files remain mutable while their writers run.
The supervisor publishes immutable workspace artifacts before recording the final execution state.
`Job.logs` contains those artifact references.
Spool output alone does not establish a persisted terminal outcome.

Command launch failures can produce `failed` with an execution error.
Supervision or publication failures attempt to record `unknown`.
Storage failure can also prevent that uncertainty from being recorded.
A supervisor crash can leave both a live command and an outdated stored job.
No automatic restart or recovery signal follows that crash.

## Reconciliation boundary

Reconciliation acquires the session lease and all applicable supervisor leases before invoking workspace reconciliation.
An active supervisor causes a busy failure.
A missing required runtime directory causes a failure.
Stopped supervisors do not prove that their commands stopped.
Reconciliation records uncertainty and never relaunches commands or signals stored PIDs.

Keep lease files unchanged and in the original workspace.
Moving or replacing runtime files breaks the ownership boundary.
Do not use reconciliation as a cleanup mechanism for surviving commands.
Operators must establish surviving process ownership independently before any external cleanup.

## Transport and review

Optional `Bindings.jobs` supplies the production MCP job service.
The transport exposes `job_submit`, `job_poll`, and `job_cancel` through that service.
The default command-line server supplies no resolver or job binding.
Transport polling does not reconcile or mutate jobs.
The [user guide](../jobs.md) shows the narrow library workflow.

Review public outcomes, concurrent cancellation, controller exit, supervisor failure, and storage uncertainty.
Make sure that tests distinguish cancellation intent from confirmed termination.
Make sure that process tests exercise live descendants and failed ownership observations.
Assess duplicate state ownership and branching before adding recovery behavior.
Use the [test guide](testing-and-review.md) for shared checks and evidence requirements.
