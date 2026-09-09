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
The separate OPM acceptance records actual container execution.
