# Local jobs

An agent can submit, inspect, and cancel prepared local jobs through a configured MCP connection.
MCP is the Model Context Protocol for tool access.
The available operations are `job_submit`, `job_poll`, and `job_cancel`.
Jobs continue when the submitting client disconnects or exits.
The [job tutorial](tutorials/jobs.md) shows requests for submission, polling, cancellation, and reconnecting.

## Configure a controller

Job operations require a configured job controller and a trusted command resolver.
A resolver maps a prepared request to an executable command.
The shipped launcher provides workspace operations only.
An operator must provide the [job service configuration](development/jobs.md#configure-a-controller) before these operations can execute work.

The local controller supports macOS and Linux with a trusted local workspace.
The request must reference the exact model revision already stored there.
It does not prepare simulator inputs, provide an OPM execution adapter, or accept numerical results.
Prepared requests and approved commands must come from trusted setup.

## Select resource limits

Each submission must explicitly select `wall_time_only` as its resource policy.
The default `enforce` policy is rejected because CPU and memory enforcement are unavailable.
The controller records CPU and memory requests without enforcing them.
It enforces the wall time limit independently of normal job updates.

Commands retain the permissions of the account that starts them.
The controller provides no process sandbox.
The host must permit process inspection and signaling.
Restricted process inspection can produce an unknown outcome even after command exit.

## Submit an existing request

Ask the agent to submit the prepared request with `job_submit` and retain its returned job reference.
The reference identifies both the session and job.
Submission returns `queued`, even if execution has already advanced.
Use `job_poll` with that reference to read current stored state.

A successful job has a zero exit status and no live members in its process group.
A process group contains related processes managed together.
Success does not establish that a simulator result is correct or loaded into ResInsight.
The [developer example](development/jobs.md#submit-an-existing-request) shows submission from trusted Python setup.

## Cancel and inspect

Ask the agent to call `job_cancel` for the exact job reference.
That operation records cancellation intent and does not confirm that execution stopped.
Continue using `job_poll` until the stored outcome establishes termination or uncertainty.
The supervisor, a separate process that manages execution, stops only its owned process group.

Only confirmed termination produces `canceled`.
If completion wins the cancellation race, the final state can remain `succeeded` with cancellation intent preserved.
`failed` records command failure or an enforced wall deadline.
`unknown` means that supervision cannot establish a final outcome.

Job records reference published log artifacts after confirmed execution.
Unknown outcomes can leave live log files without published artifact references.
An operator can inspect those files through the [runtime log guide](development/jobs.md#logs-and-failures).
Log output alone does not establish a final job outcome.

## Recover carefully

After reconnecting to a configured service, use `job_poll` with the saved job reference.
Polling reads stored state without restarting work or repairing it.
A supervisor crash can leave the command alive and its stored state outdated.
Do not submit a replacement solely because the client disconnected or state stopped advancing.

There is no MCP job reconciliation operation.
Reconciliation records uncertainty after interrupted supervision.
An operator must follow the [reconciliation procedure](development/jobs.md#reconciliation-boundary) after supervisors stop.
It does not relaunch commands or terminate surviving commands from saved process identifiers.

Keep the workspace and runtime lease files at their original locations.
A lease file supports exclusive process ownership checks.
Do not delete, replace, or move those files while jobs can exist.
Descendant processes must remain in their command's original process group.

## MCP access

The configured service exposes `job_submit`, `job_poll`, and `job_cancel` only.
Simulator preparation, OPM execution integration, and ResInsight result loading remain outside these operations.
The [implementation guide](development/jobs.md) describes ownership and recovery limits.
The [P10 evidence](development/p10-evidence.md) records real child processes and MCP disconnect trials.
