# Local jobs

An agent can submit, inspect, and cancel local jobs when the MCP server has a configured job controller.
Jobs continue when the submitting client disconnects or exits.
The available MCP operations are `job_submit`, `job_poll`, and `job_cancel`.
The default command-line server does not configure this service.
An operator must supply trusted setup before these operations can execute a command.

The Python `DurableJobController` service runs trusted local commands on macOS and Linux.
A separate supervisor process manages each job after submission.
The controller requires an existing local workspace and a trusted command resolver.
A resolver maps a prepared job request to an executable command.

This API does not prepare simulator inputs or accept numerical results.
A successful job has a zero exit status and no live process group members.
A process group contains related processes managed together.
Success does not establish that a simulator result is correct.
Simulator preparation, result lineage, and loading results into ResInsight require separate services.

## Configure a controller

Import `DurableJobController` and `JobCommand` from `resinsight_mcp.jobs`.
Pass the workspace path and resolver to `DurableJobController(workspace, resolver)`.
The resolver receives a `JobRequest` and returns a `JobCommand`.
Its `argv` must contain an absolute executable path followed by arguments.
Its `working_directory` must be an absolute path to an existing directory.
Commands run without a shell.

The request must reference the exact model revision already stored in the workspace.
The adapter remains responsible for preparing inputs and selecting the command.
The default command-line server does not supply a job resolver.

## Select resource limits

`JobRequest.resource_policy` defaults to `ResourcePolicy.ENFORCE`.
This controller rejects that policy because CPU and memory enforcement are unavailable.
Select `ResourcePolicy.WALL_TIME_ONLY` explicitly to submit a job.
The controller records CPU and memory requests without enforcing them.
A separate watchdog enforces the wall time limit, including while workspace storage operations wait.
A watchdog checks a deadline independently of normal job updates.

This controller provides no process sandbox.
Commands retain the permissions of the account that starts them.
Use trusted commands and a trusted local workspace.
The host must permit process inspection and signaling.
Restricted process inspection can produce an unknown outcome even after command exit.

## Submit an existing request

This example runs a small Python command using an existing prepared request.
The JSON file must contain a valid `JobRequest` for a revision already stored in the workspace.
The example makes no simulator preparation or execution claim.

Save the following code as `submit_job.py`:

```python
import sys
from pathlib import Path

from resinsight_mcp.contracts.errors import Failure
from resinsight_mcp.contracts.jobs import (
    JobRef,
    JobRequest,
    ResourcePolicy,
)
from resinsight_mcp.jobs import (
    DurableJobController,
    JobCommand,
)

workspace = Path(sys.argv[1]).resolve(strict=True)
request_path = Path(sys.argv[2])
request = JobRequest.model_validate_json(
    request_path.read_text(),
)
request = JobRequest(
    prepared=request.prepared,
    limits=request.limits,
    resource_policy=ResourcePolicy.WALL_TIME_ONLY,
)


def resolve(request: JobRequest) -> JobCommand:
    return JobCommand(
        argv=(
            str(Path(sys.executable).resolve()),
            "-c",
            "print('local job completed')",
        ),
        working_directory=workspace,
    )


controller = DurableJobController(workspace, resolve)
submitted = controller.submit(request)
if isinstance(submitted.outcome, Failure):
    raise RuntimeError(submitted.outcome.error)
job = submitted.outcome.value
reference = JobRef(
    session_id=job.model.session_id,
    job_id=job.job_id,
)
print(reference.model_dump_json())
print(controller.poll(reference).model_dump_json())
```

Run it from the installed project environment:

```sh
uv run --locked python submit_job.py /absolute/workspace /absolute/job-request.json
```

The returned submission records `queued`, even if the supervisor has already advanced the stored state.
`poll(reference)` returns the current stored job without changing it.
Methods return an `OperationResult` containing either `Success` or `Failure`.
Constructor errors can raise `ContractError` directly.

## Cancel and inspect

Call `request_cancel(reference)` to record durable cancellation intent.
A successful request does not mean that execution has stopped.
The supervisor observes that intent and sends `SIGTERM` to its owned process group.
After a 0.5-second grace period, it sends `SIGKILL` if necessary.
It then allows up to five seconds to confirm termination.
Only confirmed termination produces `canceled`.
If completion wins a cancellation race, the final state can remain `succeeded` with cancellation intent preserved.

`failed` records a command failure or enforced wall deadline.
`unknown` means that supervision cannot establish a final outcome.
A supervisor crash can leave the command alive and its stored state outdated.
Polling does not repair that state or restart execution.

The runtime path is `workspace/jobs-runtime/<session_id>/<job_id>/`.
It contains live `stdout.log`, `stderr.log`, and `supervisor.log` files.
These spool files collect output before publication.
After confirmed execution, `Job.logs` references immutable workspace log artifacts.
Unknown outcomes can leave spool files without published artifact references.

## Recover carefully

Call `reconcile(session_id)` only after the session's supervisors have stopped.
The controller requires exclusive supervisor leases before reconciliation.
A lease is an exclusive operating system file lock.
Reconciliation marks interrupted work as uncertain without relaunching commands.
It never signals a process from its saved process identifier, or PID.

Keep the workspace and runtime lease files at their original locations.
Do not delete, replace, or move lease files while jobs can exist.
Descendant processes must remain in the command's original process group.
Recovery cannot terminate surviving commands from saved PIDs.

## MCP access

MCP means Model Context Protocol, a tool access protocol.
Production transport supports `job_submit`, `job_poll`, and `job_cancel` through optional `Bindings.jobs` configuration.
Configure that binding with a job controller and trusted resolver.
`job_poll` remains read-only.
The default command-line server has no job controller binding.

The [implementation guide](development/jobs.md) describes ownership and recovery limits.
The [P10 evidence](development/p10-evidence.md) records real child processes and MCP disconnect trials.
