# Create a constrained model

`SyntheticModelService` creates a complete FIELD input model through the existing OPM import service.
FIELD specifies feet, absolute pressure in psi, and surface volumes in field units.
The service validates and stores the generated inputs as a fixed model revision.
It does not start Flow or open ResInsight.
A valid model still requires separate simulation convergence checks.

Model creation is available through the Python service.
The shipped launcher does not advertise a model creation tool.

## Create the reference model

Install the parser with `uv sync --locked --extra imports`.
Run this example with `uv run --locked --extra imports python` from the repository root.
The `synthetic-workspace` directory must not exist.

```python
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError, Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Session
from resinsight_mcp.models.synthetic import (
    SyntheticModelRequest,
    SyntheticModelService,
    read_grid_id,
    read_specification,
    reference_specification,
)
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value(result):
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


store = SqliteWorkspaceStore.create(Path("synthetic-workspace").resolve())
record = Session(session_id=SessionId.new(), name="SPE1")
session = value(store.create_session(record))
receipt = value(
    SyntheticModelService(store).create_model(
        SyntheticModelRequest(
            session_id=session.session_id,
            datum="SPE1 local depth datum",
            specification=reference_specification(),
        )
    )
)
print(receipt.imported.prepared.revision.model)
with store.open_artifact(receipt.specification_source) as source:
    text = source.read().decode("utf-8")
    specification = read_specification(text)
    mapping = specification.grid.active_cells(
        receipt.imported.prepared.revision.model, read_grid_id(text)
    )
print(specification.template_version)
```

The receipt contains the import receipt, specification source artifact, and active-cell mapping.
The source artifact is the revision entrypoint.
Its `synthetic-grid-id` comment preserves the grid identity across reconstruction.
Its `synthetic-specification` comment contains the complete specification as JSON.
`read_specification` reads this metadata and rejects missing or repeated specification comments.
The reader does not validate arbitrary simulator input against those comments.
The comments describe generation inputs and do not prove the contents of later edited schedules.

## Accepted limits

The fixed `spe1-field-synthetic-v1` template uses oil, water, gas, and dissolved gas.
It retains the SPE1 fluid tables and rock compressibility.
The grid has uniform horizontal cell widths and at most 10,000 cells.
Each layer supplies thickness, porosity, and three directional permeabilities.
Every cell is active, with I varying fastest, followed by J and K.
The model contains one equilibrium region and a constant dissolved-gas ratio.

The two wells require distinct names and distinct cells inside the grid.
Each well has one open completion, a diameter, and a reference depth.
The model requires one producer and one gas or water injector.
Controls follow the [P07 supported profile](development/model-imports.md#wells-and-controls).
The fixed controls apply throughout the schedule.
The schedule contains at most 256 positive report intervals and spans at most 3,660 days.

Lengths and depths use feet, with depth increasing downward.
Pressure fields use psia, absolute pounds per square inch.
Permeability uses mD, millidarcies.
Porosity is a fraction greater than zero and less than one.
Oil and water surface rates use `stb/day`, and gas surface rates use `Mscf/day`.
The request names the local depth datum explicitly.

Unknown fields, invalid values, and unsupported controls fail typed validation.
OPM validates the generated model before publication.
The [import source limits](development/model-imports.md#source-and-resource-limits) also apply to generated sources.
An import failure retains the import service's error and publication effect.
The service creates no simulator jobs.

## Data terms and evidence

The template retains the attributed SPE1 data from the P07 fixture.
Copyright 2015 Statoil and the source data notices remain in the generated deck.
The [Open Database License 1.0](http://opendatacommons.org/licenses/odbl/1.0/) applies to the source and derived input.
The [Database Contents License 1.0](http://opendatacommons.org/licenses/dbcl/1.0/) applies to individual contents.
These data terms remain separate from the repository software license.
Retain attribution and applicable data notices with public results.

Focused tests check generated properties, active-cell order, stored specification recovery, and OPM completion cells.
The [development record](development/synthetic-models.md) records four successful reference runs and their numerical tolerances.
That numerical evidence covers the supplied two-day gas-injection reference on the pinned Flow runtime.
The [native record](development/evidence/p08-native/README.md) connects the generated result to its grid geometry and final pressure image.
