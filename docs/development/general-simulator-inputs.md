# General simulator inputs

This delivery continues [issue #57](https://github.com/LukasMosser/resinsight-mcp/issues/57) after general schedule authoring.
The owner requested PR #61 closure and continued implementation on September 13, 2026.
PR #61 is closed without merging, and this branch retains its commits.

## Implementation sequence

1. Add explicit fluid, rock, and initialization tables with regional assignments.
2. Combine compatible native connections, schedules, and these tables into simulator input files.
3. Validate compiled files with the supported OPM parser in an isolated process.
4. Publish compact validation receipts with exact source identities and resource measurements.
5. Connect prepared general models to simulator execution and bounded result queries.

The first step adds public authoring tools under `--enable-general-models`.
The [compiler delivery](general-input-compilation.md) implements assembly, isolated OPM validation, and prepared receipts.
General execution and large result queries remain separate work.
An authored physics snapshot always reports `simulation_ready: false`.
Its `complete` field only describes regional table coverage after authoring validation.
Neither value claims a successful simulation or complete engineering review.
The [public MCP evidence](evidence/general-physics/README.md) records three regions and a 70,001-row table on a million-cell model.

## Explicit physics contract

The `black_oil_disgas_rsvd` profile describes oil, water, gas, and dissolved gas using tabulated properties.
This profile makes the existing three-phase physics explicit for general geological models.
It does not introduce another simulator or infer unknown field inputs.

Each snapshot belongs to one immutable geological model.
Model coordinate units determine METRIC or FIELD simulator units.
Every numeric column has an explicit unit and a stored array reference.
The schema tool gives column names, order, numeric types, and validation rules.
The model does not infer fluid values, contact depths, region assignments, or well controls.

| Region map | Required tables | Meaning |
| --- | --- | --- |
| `PVTNUM` | `PVTW`, `ROCK`, `DENSITY`, `PVDG`, `PVTO` | Fluid properties and rock compression. |
| `SATNUM` | `SWOF`, `SGOF` | Relative permeability and capillary pressure. |
| `EQLNUM` | `EQUIL`, `RSVD` | Initial pressure, contacts, and dissolved gas. |

Relative permeability describes how fluids share pore flow.
Capillary pressure is the pressure difference between fluid phases.
`RSVD` gives dissolved gas content against depth.
Each map explicitly selects a uniform positive region or one integer per global cell.
Array maps include inactive cells and follow the model's I-fastest ordering.
All region maps are required when creating a snapshot.

Region tables use positive indices starting at one.
Coverage requires every table for each index through the largest assigned or authored index.
Unused intermediate indices still require tables because simulator tables use positional region numbering.
Sparse high indices return incomplete coverage without allocating intervening records.
There is no fixed region, table, or row ceiling.

Tables use separate numeric columns, so individual uploads remain bounded.
Repeated edits can accumulate more tables than one request permits.
The authoring policy controls working memory and request and response sizes.
Values are validated across stored blocks, including block boundaries.

`PVTO` uses repeated solution ratios to represent pressure branches.
Ratios increase between branches, pressures increase within branches, and bubble pressures increase between branches.
This profile requires two branches and explicit equilibrium flags `1, 0, 0` with `RSVD`.
Other initialization methods need explicit adapter support and remain visible capability gaps.
These restrictions describe the implemented profile and must not become permanent MCP-wide limits.

METRIC uses bar, meters, kg/m3, cP, and simulator volume ratios.
FIELD uses psia, feet, lb/ft3, and cP.
FIELD gas volume factors use rb/Mscf, while dissolved gas ratios use Mscf/stb.
These conventions were checked through the installed OPM 2025.10 parser's raw and SI values.
The [OPM SPE1 input](https://github.com/OPM/opm-common/blob/master/tests/SPE1CASE1.DATA) also labels these FIELD quantities.

## Public operations

| Tool | Result |
| --- | --- |
| `general_physics_schema` | Required columns, units, supported profile, and rules. |
| `general_physics_create` | Empty snapshot with explicit region assignments. |
| `general_physics_edit` | Immutable child with table replacements, additions, removals, or new maps. |
| `general_physics_inspect` | Compact identity, lineage, counts, and coverage. |
| `general_physics_regions` | Three explicit assignments with array references where needed. |
| `general_physics_tables` | Bounded table metadata page with column references. |

Existing array queries provide bounded access to numeric table values.
An omitted table retains its original array references.
An invalid edit does not publish a child snapshot or alter the parent.
Foreign model, parent, map, and column references fail through workspace and session ownership checks.

## Compilation contract

Compilation must require complete physics, explicit report times, and matching native connection exports for every scheduled well.
Exports must identify the exact geological model and immutable well plan.
Schedule-only changes can reuse exports when those identities remain unchanged.
Changed geometry or well targets require new native exports.

The compiler must preserve explicit units, region maps, property values, connection factors, and effective control histories.
It must derive simulator dimensions from actual tables, wells, connections, and report times.
Unknown model fields must receive explicit compilation decisions rather than silent omission.
The legacy SPE1 import admission limits must not control this new path.

An isolated OPM worker must validate the compiled files before a prepared receipt is published.
Parser validation must distinguish accepted input from a completed simulator run.
The receipt must retain source identities, parser version, file references, counts, and configured resource limits.
Native acceptance will reuse the reviewed ResInsight build and create original synthetic inputs through public MCP tools.
Large execution remains governed by the resource and evidence gates in the parent plan.
