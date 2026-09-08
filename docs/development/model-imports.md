# OPM model imports

`OpmImportService` imports a bounded FIELD model through the Python API.
A deck is a simulator input file.
The service preserves source files and validates their model meaning through OPM.
It does not run a simulator, control jobs, or expose an MCP binding.
A valid import does not prove simulation convergence, which means the solver meets its numerical stopping criteria.
The [P07 evidence record](p07-evidence.md) records the separate native trial and its limits.

## Install and use

Install the optional parser dependency from the repository root:

```sh
uv sync --extra imports
```

The service requires exactly [`opm==2025.10`](https://pypi.org/project/opm/2025.10/).
It reports parser failures and never silently substitutes a parser or version.
The 2026.4 macOS wheel references external `cjson` and `fmt` libraries.
Its import failed on macOS 14 because `cjson` was missing.
The loader also reported a macOS 26 build despite the wheel's macOS 14 tag.
The explicit tested pin avoids version substitution.

This choice does not establish general compatibility with OPM Flow 2026.04.
The [earlier Flow trial](platform-opm.md) and P07 evidence describe bounded simulator results separately.

Run this example from the repository root with `uv run --extra imports python`.
Use a new workspace directory for each example run.

```python
from pathlib import Path

from resinsight_mcp.contracts.errors import ContractError, Failure
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import Backend, PreparationRequest, Session
from resinsight_mcp.models.imports import ImportRequest, OpmImportService
from resinsight_mcp.workspaces import SqliteWorkspaceStore


def value(result):
    if isinstance(result.outcome, Failure):
        raise ContractError(result.outcome.error)
    return result.outcome.value


store = SqliteWorkspaceStore.create(Path("import-workspace").resolve())
session = value(store.create_session(Session(session_id=SessionId.new(), name="SPE1")))
service = OpmImportService(store)
receipt = value(
    service.import_model(
        ImportRequest(
            session_id=session.session_id,
            source_root=Path("tests/models/imports/data/spe1").resolve(),
            entrypoint="SPE1.DATA",
            datum="SPE1 local datum",
        )
    )
)
print(receipt.summary.model_dump())
prepared = value(
    service.prepare(
        PreparationRequest(
            revision=receipt.prepared.revision,
            backend=Backend.OPM_FLOW,
        )
    )
)
print(prepared.revision.model)
```

`import_model` returns `OperationResult[ImportReceipt]`.
The receipt contains the prepared revision, import record artifact reference, and model summary.
The summary reports parser version, support profile, units, dimensions, active cells, wells, report steps, elapsed days, and parsed keywords.
`prepare` returns `OperationResult[PreparedModel]` and accepts only `Backend.OPM_FLOW`.
Other backends return `UNSUPPORTED_OPERATION`.
Invalid sources, unsupported model content, and parser failures return `INVALID_MODEL`.

## Preserved inputs

Import first copies the source graph into a temporary snapshot.
OPM validates that snapshot before the service stores source artifacts and saves the revision.
The service does not rewrite a supplied deck.
Each source artifact retains its original text and root-relative path.
The revision identifies every source artifact and its entrypoint.

A separate JSON log artifact uses the logical name `imports/<revision_id>.json`.
It records the model reference, entrypoint path, source artifact references, include edges, and summary.
Its `changes` array is empty because import makes no model edits.
The record itself is not a simulator input.

Preparation checks the supplied revision against the stored revision.
It reconstructs and validates the include graph from stored artifacts.
Every revision input must belong to that graph.
Preparation still works after the original source directory disappears.
It requires FIELD units, foot coordinates, and `positive_down` depth.
The caller must supply a nonempty datum, the named reference for depth measurements.

## Supported model profile

The profile identifier is `spe1-field-v1`.
It supports black-oil physics, oil, water, gas, and dissolved gas.
The grid is Cartesian, a rectangular arrangement of cells, with every cell active.
The model has one equilibrium region and declares `FIELD` exactly once.
Other unit systems and unsupported keywords fail validation.

OPM's `Parser`, `EclipseState`, and `Schedule` interpret the deck and construct its model and schedule.
The parser uses `ParseContext` with throwing actions for all reported parse conditions.
The source collector performs only narrow `INCLUDE` preflight checks.
It is not a replacement reservoir parser.
See the [official OPM Python documentation](https://opm.github.io/opm-python-documentation/release-2025.10/index.html) for upstream interfaces.

### FIELD units

The supported quantities use these [OPM 2025.10 FIELD definitions](https://github.com/OPM/opm-common/blob/release/2025.10/final/opm/input/eclipse/Units/Units.hpp#L274-L305).
Surface rates use the corresponding surface volume per day.

| Quantity | Unit |
| --- | --- |
| Length and depth | ft, feet |
| Pressure | psia, absolute pounds per square inch |
| Time | day |
| Oil and water surface rate | stb/day, stock tank barrels per day |
| Gas surface rate | Mscf/day, thousand standard cubic feet per day |
| Permeability | mD, millidarcies |
| Density | lb/ft³, pounds per cubic foot |
| Viscosity | cP, centipoise |

Conflicting unit declarations and coordinate units fail validation.
The service cannot infer mislabeled numeric values from their numbers alone.
The caller must make sure that supplied values use the declared units.

### Required keywords

Every import must contain every keyword below:

```text
RUNSPEC DIMENS OIL WATER GAS DISGAS FIELD START WELLDIMS
GRID DX DY DZ TOPS PORO PERMX PERMY PERMZ
PROPS PVTW ROCK SWOF SGOF DENSITY PVDG PVTO
SOLUTION EQUIL RSVD SUMMARY SCHEDULE
WELSPECS COMPDAT WCONPROD WCONINJE TSTEP
```

### Optional supported keywords

The complete allowlist consists of the required keywords and these optional keywords:

```text
TITLE EQLDIMS TABDIMS UNIFOUT INIT REGIONS FIPNUM
RPTSCHED RPTRST DRSDT FOPR FGOR BPR BGSAT
WBHP WGIR WGIT WGPR WGPT WOPR WOPT WWIR WWIT WWPR WWPT
```

`INCLUDE` is a source directive that OPM expands before the keyword check.
`EQLDIMS` and `TABDIMS` can appear only with defaulted items.
`EQUIL` must contain exactly one record.
`DX`, `DY`, `DZ`, `PERMX`, `PERMY`, and `PERMZ` values must be finite and positive.
`PORO` values must be finite, greater than zero, and less than one.

### Wells and controls

`WELLDIMS` requires explicit positive `MAXWELLS`, `MAXCONN`, `MAXGROUPS`, and `MAX_GROUPSIZE` values.
Their maximum values are 32, 10,000, 32, and 32, respectively.
Other explicit `WELLDIMS` items fail validation.

`WELSPECS` permits explicit `WELL`, `GROUP`, `HEAD_I`, `HEAD_J`, `REF_DEPTH`, and `PHASE` items only.
Well names and phases must be explicit.
The phase must be `OIL`, `GAS`, or `WATER`.
Repeated well declarations fail validation.

`COMPDAT` permits explicit `WELL`, `I`, `J`, `K1`, `K2`, `STATE`, and `DIAMETER` items only.
Each completion must name an already declared well.
Its explicit state must be `OPEN`, and its explicit diameter must be finite and positive.
A `SHUT` completion fails before OPM can silently close an open well.
Whole-well `SHUT` controls remain supported.

Controls require exact well names without `*`, `?`, or `[` patterns.
Each control follows its well declaration and completion.
`WCONPROD` supports `ORAT` and `BHP` modes.
`WCONINJE` supports `RATE` and `BHP` modes with explicit `GAS` or `WATER` injection type.
Both controls require explicit `OPEN` or `SHUT` status and finite, positive `BHP`.
Rate modes require an explicit finite rate, positive for `OPEN` and nonnegative for `SHUT`.

Only the well, status, mode, pressure, selected rate, and injection type can have explicit control values.
Switching a well between production and injection fails validation.
Every declared well requires completions and controls before each `TSTEP` and at the schedule end.
Every scheduled well must retain active connections at every report step.
An open well requires an open connection.

## Source and resource limits

The source root must be an absolute local directory without symlinks.
The entrypoint must sit directly inside that directory.
All source paths resolve against the source root, including paths from nested include files.
Paths must be ASCII and root-relative without aliases, absolute paths, or dot segments.
Symlinks, include cycles, and case-insensitive path collisions fail validation.
Missing sources and nonregular files also fail validation.

Each `INCLUDE` must occupy its own uppercase line.
Its record requires one single-quoted path followed by a slash:

```text
INCLUDE
 'grid/GRID.INC' /
```

Model text requires ASCII characters with ordinary spaces or tabs outside comments.
Comma separators and quoted strings across lines are unsupported.
`--` starts a comment outside single quotes.
`PATHS`, `IMPORT`, `GDFILE`, `PYINPUT`, and `PYACTION` directives are unsupported.
`END`, `ENDINC`, `SKIP`, `SKIP100`, `SKIP300`, and `ENDSKIP` directives are also unsupported.

| Resource | Maximum |
| --- | --- |
| Unique source text | 2,000,000 characters |
| Expanded source text | 2,000,000 characters |
| Unique source files | 64 |
| Include depth, including the entrypoint | 16 |
| Expanded file visits | 256 |
| Expanded numeric repetition entries | 200,000 |
| Grid cells | 10,000 |
| Wells | 32 |
| Report steps, excluding the initial state | 256 |
| Simulated duration | 3,660 days |
| Parser process time | 30 seconds |

Grid dimensions must be positive integers.
The schedule requires at least one report step and positive, finite `TSTEP` intervals.
Report times must increase, with a positive total duration.
Expanded limits count repeated includes each time they occur.

## Evidence and provenance

The [P07 evidence record](p07-evidence.md) contains the native trial, tested versions, commands, and observed results.
The [platform proof](platform-proof.md) records earlier experiments with separate acceptance boundaries.
Neither parser acceptance nor one successful simulation establishes general model support or independent numerical accuracy.

The fixture derives from OPM SPE1 and preserves its Statoil attribution.
Its source uses ODbL 1.0, and its contents use DbCL 1.0.
The fixture README records the source commit and changes made before import.
Those fixture changes remain separate from the import record's empty change list.
