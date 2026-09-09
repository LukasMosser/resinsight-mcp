# Run OPM Flow from Python

OPM Flow runs the supported fixed FIELD model profile through `OpmFlowService`.
FIELD uses feet, pounds per square inch, and stock tank barrels.
The service accepts immutable model revisions prepared by `OpmImportService`.
The [model import design](development/model-imports.md) describes the supported input boundary.
This page describes the public Python API.

The profile supports oil, water, gas, and dissolved gas.
It requires a rectangular grid with every cell active and one equilibrium region.
Unsupported keywords and other unit systems fail validation.

## Check the local runtime

The runtime requires Docker and an existing local image for `linux/arm64`.
The image contains Flow 2026.04 and uses this fixed digest:

```text
openporousmedia/opmreleases@sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1
```

The service never pulls an image.
The Python environment requires the package's `imports` extra, which supplies the supported OPM readers.
The repository development environment includes these readers.

`FlowConfiguration` defaults to `/Applications/Docker.app/Contents/Resources/bin/docker`.
If Docker uses another location, pass its absolute path as `docker=Path("/absolute/path/to/docker")`.
Call `check_dependencies()` before creating workspace storage.
It checks the Docker client, daemon, local image digest, and platform without starting a container.
An unavailable or mismatched runtime raises `ContractError`.
Each Docker check has a ten-second timeout.

## Import, submit, and collect

Use Python 3.12 with the repository environment.
Replace the workspace and source paths in this example.
Use a new workspace path whose parent exists.
The example source is the repository's supported SPE1 fixture.
The workspace path must not contain commas.

```python
import time
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError, Failure, OperationResult
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.jobs import (
    JobRef,
    JobRequest,
    JobState,
    ResourceLimits,
    ResourcePolicy,
)
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.simulators.opm import FlowConfiguration, OpmFlowService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def require[T](response: OperationResult[T]) -> T:
    if isinstance(response.outcome, Failure):
        raise ContractError(response.outcome.error)
    return response.outcome.value


configuration = FlowConfiguration()
configuration.check_dependencies()
workspace = Path("/absolute/path/to/new-workspace")
store = SqliteWorkspaceStore.create(workspace)
session = require(store.create_session(Session(session_id=SessionId.new(), name="Flow example")))
receipt = require(
    OpmImportService(store).import_model(
        ImportRequest(
            session_id=session.session_id,
            source_root=Path("/absolute/path/to/repository/tests/models/imports/data/spe1"),
            entrypoint="SPE1.DATA",
            datum="SPE1 local depth datum",
        )
    )
)
service = OpmFlowService(workspace, configuration)
job = require(
    service.submit(
        JobRequest(
            prepared=receipt.prepared,
            limits=ResourceLimits(cpu_count=2, memory_mib=2048, wall_time_seconds=60),
            resource_policy=ResourcePolicy.ENFORCE,
        )
    )
)
job_ref = JobRef(session_id=session.session_id, job_id=job.job_id)
while job.state in {JobState.QUEUED, JobState.RUNNING}:
    time.sleep(0.2)
    job = require(service.poll(job_ref))
if job.state != JobState.SUCCEEDED:
    raise RuntimeError(f"Flow did not finish successfully: {job.state}")
result = require(service.collect(job_ref))
print(result.model_dump_json(indent=2))
```

Each request requires positive CPU, memory, and wall-time limits.
The maximum values are two CPUs, 2048 MiB, and 60 seconds.
Docker enforces CPU and memory limits, and the job controller enforces the deadline.
The container has no network access.
It receives read-only inputs and a separate writable output directory.

## Cancel or reopen a job

To request cancellation, call this method before the job finishes:

```python
job = require(service.request_cancel(job_ref))
```

Cancellation is a request, and container termination must be confirmed.
Continue polling until the job stops or reports `UNKNOWN`.
An `UNKNOWN` state means that the controller cannot confirm the current outcome.
The [Docker job guide](development/docker-jobs.md) explains reconciliation and ownership checks.

The controller preserves jobs after the submitting process exits.
Save `job_ref` and the workspace path for later use.
A fresh service can poll the saved job and collect its successful result:

```python
service = OpmFlowService(workspace, configuration)
job = require(service.poll(job_ref))
if job.state == JobState.SUCCEEDED:
    result = require(service.collect(job_ref))
```

## Understand the result

A successful process exit establishes execution success only.
Collection requires confirmed success and complete EGRID, INIT, UNRST, SMSPEC, and UNSMRY files.
These files contain geometry, initial properties, restart properties, summary definitions, and summary values.
The service saves these outputs, a numerical dataset, and assessment evidence as immutable workspace artifacts.

An accepted result follows the `opm-field-validity-v1` policy.
It requires trusted execution, complete scheduled reports, matching identities and units, finite values, positive absolute pressures, and valid phase saturations.
Phase saturation means the fluid fraction of pore space.
The assessment preserves small permitted rounding differences without clipping values.

`NumericalAssessment.ACCEPTED` does not establish agreement with an independent numerical reference.
The producer evidence keeps `numerical_reference_assessed` false.
The [recorded acceptance trials](development/evidence/p11/README.md) contain a separate reference comparison.
The [service design](development/opm.md) explains the validity checks, numerical tolerances, and geometry limits.

Collection preserves result, grid, model, job, and report identities across retries and service restarts.
Each new run reserves separate result and grid identities.
Missing outputs, invalid values, mismatched metadata, and unsuccessful jobs cause explicit failures.
A publication failure can report an uncertain mutation effect without creating a successful result record.
An unchanged collection retry can finish publication using the reserved artifacts.
Inspect the returned failure before deciding whether to retry.

For a materialized output directory, `service.verify_outputs(result, directory)` returns a verified numerical dataset through `OperationResult`.
The directory must contain the five original output basenames.
Verification compares parsed values and metadata against the immutable collected references.
