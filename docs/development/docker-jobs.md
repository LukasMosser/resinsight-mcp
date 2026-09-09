# Docker job ownership

The generic job supervisor supports a typed Docker execution record.
The adapter supplies a pinned image, container command, mounts, and version records.
The supervisor constructs Docker commands without parsing caller-supplied Docker arguments.
Container networking is disabled, and CPU and memory limits are enforced.

The supervisor creates a named container with a random ownership token before starting it.
It stores the confirmed container identifier before requesting execution.
An uncertain identifier write leaves the container stopped.
Docker acknowledges detached start before the supervisor follows its logs.
The existing independent supervisor keeps execution separate from the MCP client lifetime.

Cancellation and deadlines inspect the saved container identity, image, name, and ownership label.
They stop the container before terminating its local log reader.
A terminal cancellation requires both container and local process termination evidence.
An unavailable Docker response produces an unknown outcome rather than confirmed cancellation.
Each Docker command has a bounded timeout.
A Docker daemon failure can prevent confirmation or enforcement of a stop request.

Stopped containers remain available as execution evidence.
Explicit removal checks the same ownership fields and rejects running containers.
Reconciliation requires stopped supervisors and stops verified containers before marking interrupted jobs unknown.
Reconciliation does not claim that an interrupted simulation succeeded.

The maintained tests use separate command processes that model the Docker lifecycle.
They exercise completed execution, nonzero exit, cancellation, deadline enforcement, durable reopening, and rejected ownership.
These tests do not establish real Docker runtime behavior.
P11 acceptance must separately record actual container execution.

## Scope and review

[Issue #47](https://github.com/LukasMosser/resinsight-mcp/issues/47) owns this generic job prerequisite for P11.
The [run contracts](run-result-contracts.md) define its immutable submission and container records.
The Flow adapter retains model staging, simulator configuration, and numerical assessment.

Review identified remote cleanup failures that could skip local process cleanup.
The supervisor now attempts verified local cleanup independently and preserves the uncertain container outcome.
Review also identified a delayed inspection that could start execution after the deadline.
The controller now passes an absolute deadline and checks remaining time after inspection.

Eleven focused lifecycle tests exercise successful and failed exits, cancellation, deadlines, durable reopening, and foreign ownership.
They also cover uncertain identity publication, supervisor loss, unavailable Docker, verified absence, foreign names, and delayed startup inspection.
These tests use real separate local command processes with a typed Docker fixture.

## Evidence

The lead integration passed 538 maintained tests, Ruff, ty, and the strict documentation build.
The [check log](evidence/docker-jobs/shared-check.log) and [environment record](evidence/docker-jobs/environment.json) preserve the command, source, and versions.
The [browser record](evidence/docker-jobs/review.json) covers navigation, links, page errors, and horizontal overflow.
The lead visually inspected the [controller guide](evidence/docker-jobs/docker-jobs.png) and [developer index](evidence/docker-jobs/development.png).
