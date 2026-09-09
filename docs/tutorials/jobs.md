# Follow a job across a reconnect

This tutorial uses a configured local job controller and trusted command resolver.
A resolver maps a prepared request to an executable command.
The server must advertise `job_submit`, `job_poll`, and `job_cancel`.
The default workspace launcher does not configure them.
See the [job integration guide](../development/jobs.md) for host setup.

## Start from a prepared request

The host must provide a complete prepared model record for an exact revision already stored in the workspace.
The current MCP catalog has no simulator preparation tool.
The command resolver chooses the executable and arguments outside the MCP request.
A request cannot supply an arbitrary shell command.
The controller runs trusted commands without a shell.

Ask your agent:

> Submit the prepared request supplied by this host with a 60-second wall limit.
> Retain the returned job reference so we can check it after reconnecting.

Use this argument template:

```text
job_submit({
  "prepared": PREPARED_MODEL,
  "limits": {"cpu_count": 1, "memory_mib": 128, "wall_time_seconds": 60},
  "resource_policy": "wall_time_only"
})
```

`PREPARED_MODEL` means the complete trusted prepared model object, not a string or file path.
Read its required fields from the current `resinsight://catalog` schema.
Do not invent revision or artifact identifiers to fill it.
These example resource values must fit the host's prepared command.

The controller requires explicit `wall_time_only` because CPU and memory enforcement are unavailable.
It records CPU and memory requests without enforcing them.
Its independent watchdog enforces the wall deadline.
The default `enforce` policy is rejected.
This controller provides no process sandbox.

A successful submission returns a job recorded as `queued`.
The independent supervisor can already have advanced its stored state.
Retain `outcome.value.job_id` and `outcome.value.model.session_id` together.
No job-list tool is currently advertised.

## Read status and progress

Ask your agent:

> Check the submitted job and explain its current state and latest events.

Replace both placeholders with the identifiers retained from submission:

```text
job_poll({"session_id": "<SESSION_ID>", "job_id": "<JOB_ID>"})
```

The response provides `state`, timestamped `events`, cancellation intent, process records, and available log references.
It has no numerical progress percentage or simulator convergence report.
Polling reads stored state without repairing supervision.

| State | Meaning |
| --- | --- |
| `queued` | Submission exists, but execution is not yet recorded as running. |
| `running` | The supervisor recorded command startup. |
| `succeeded` | The command exited with zero status and no live process group members. |
| `failed` | A command failure or enforced wall deadline is recorded. |
| `canceled` | Cancellation ended with confirmed termination. |
| `unknown` | Supervision cannot establish a final outcome. |

A process group contains related processes managed together.
A successful command does not establish numerical result quality.
It also does not load results into ResInsight.

`Job.logs` contains immutable artifact references after publication.
The MCP catalog has no general log-reading tool.
The host operator can inspect live `stdout.log`, `stderr.log`, and `supervisor.log` files under the job's runtime directory.
The [runtime log guide](../development/jobs.md#logs-and-failures) describes their paths and publication limits.

## Reconnect without submitting twice

Ask your agent:

> After reconnecting, check the same job identifier.
> Do not submit another job to recover its status.

Reconnect to the same workspace through the configured host.
Call `job_poll` with the retained session and job identifiers.
Client disconnection does not cancel a job.
A host restart must restore the job service configuration to expose its tools again.
Restarting the MCP server does not restart the command.

The [P10 protocol acceptance record](../development/evidence/p10/mcp-jobs.json) preserves completed and canceled jobs after disconnect and restart.
Its completed job contains this verified outcome excerpt:

```json
{
  "state": "succeeded",
  "cancel_requested": false,
  "exit_code": 0
}
```

The recorded command was a controlled Python child process.
Its `backend: opm_flow` field does not establish OPM Flow execution.
This tutorial makes no MCP simulator submission or preparation claim.
The [P10 evidence guide](../development/p10-evidence.md) explains the tested scope.

## Cancel and confirm

Ask your agent:

> Cancel this job and check until its outcome confirms whether execution stopped.

Use the same retained reference:

```text
job_cancel({"session_id": "<SESSION_ID>", "job_id": "<JOB_ID>"})
job_poll({"session_id": "<SESSION_ID>", "job_id": "<JOB_ID>"})
```

Cancellation first records `cancel_requested: true`.
That flag does not confirm termination.
Only a final `canceled` state with `termination_confirmed: true` establishes completed cancellation.
The P10 cancellation record contains those values.
If completion wins the race, the final state can remain `succeeded` with cancellation intent preserved.

## Handle an uncertain or failed job

If polling reports `unknown`, ask the host operator to inspect supervision before submitting replacement work.
A crashed supervisor can leave a command running and stored state outdated.
Polling does not repair that condition.
The catalog exposes no `job_restart` or reconciliation tool.

Host reconciliation requires stopped supervisors and exclusive leases.
A lease is an exclusive operating system file lock.
Reconciliation records uncertainty without restarting commands or signaling saved process identifiers.
The [recovery guide](../development/jobs.md) describes the operator's responsibilities.

If another execution is needed, submit a new trusted prepared request after resolving the original job's outcome.
Retain the new job identifier separately.
Do not describe a new submission as resuming the old process.
