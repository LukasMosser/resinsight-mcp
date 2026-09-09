# OPM workflow delivery

The accepted goal completes [P11](https://github.com/LukasMosser/resinsight-mcp/issues/12), [P12](https://github.com/LukasMosser/resinsight-mcp/issues/13), and [P13](https://github.com/LukasMosser/resinsight-mcp/issues/14).
P11 runs Open Porous Media (OPM) Flow against one immutable model revision.
P12 validates, loads, queries, and compares the resulting data.
P13 proves the full workflow through the shipped launcher and public MCP tools.
This plan records scope, ownership, and remaining acceptance gates.

The [P11 record](evidence/p11/README.md) now establishes bounded Flow execution and verified numerical output through the Python service.
Native P12 and complete public MCP P13 acceptance remain separate gates.

## Shared prerequisites

[Issue #46](https://github.com/LukasMosser/resinsight-mcp/issues/46) owns the [run and result contracts](run-result-contracts.md).
One contract owner defines Docker execution identity, output roles, numerical data, and result references in saved project checkpoints.
P11 produces those records, while P12 validates and consumes them.
Workspace storage checks record relationships and immutable artifact ownership.
Domain services remain responsible for parsing and numerical acceptance.

Review found that separate runs receive different grid identifiers, even when their physical geometry matches.
The shared dataset therefore records active-cell geometry for explicit comparison, with one common contract owner.

[Issue #47](https://github.com/LukasMosser/resinsight-mcp/issues/47) extends the generic job controller for Docker execution.
The P11 owner implements container identity, cancellation, deadlines, lost-controller recovery, and their tests in a separate change.
Docker commands use typed execution records and a pinned image.
The controller must distinguish unavailable runtime state from verified absence.
The P11 adapter retains Flow input preparation and output assessment.

## Domain ownership

| Owner | Files and responsibilities |
| --- | --- |
| P11 | `src/resinsight_mcp/simulators/opm/`, matching tests, and the OPM user and developer guides. |
| P11 prerequisite | Docker support in `src/resinsight_mcp/jobs/`, matching tests, and its developer guide. |
| P12 | `src/resinsight_mcp/results/`, matching tests, and the results developer guide. |
| P07 and P09 follow-up | Persistent prepared grids, restored case verification, and explicit adoption of existing native wells. |
| Lead integration | Launcher configuration, MCP operations, dependency pins, combined acceptance, navigation, and delivery evidence. |

Each writing owner uses a separate worktree and `codex/` branch.
The lead reviews and integrates complete commits through separate feature PRs.
Shared interface changes require agreement before dependent implementation.

## Public workflow integration

[Issue #35](https://github.com/LukasMosser/resinsight-mcp/issues/35) owns the shipped launcher and domain tool composition.
The launcher must validate required dependencies before advertising enabled operations.
Public model tools must support import, creation, inspection, preparation, and immutable cloning.
Public well tools must expose native paths, completion exports, and child schedule publication.
Public run and result tools must preserve exact session, model, job, and result identities.
The transport must deliver native grid and summary plot images with their observations.

Prepared well-editing grids use persistent EGRID and property files through the reviewed native FIELD export command.
The follow-up is recorded in [issue #48](https://github.com/LukasMosser/resinsight-mcp/issues/48).
Its [lifetime acceptance](evidence/p09/lifetime/README.md) preserves all corners, properties, trajectories, and completions across two reopen cycles.
Restoration rejects stale references and verifies restored cases before explicit well adoption.
The public recovery request uses the current project context, exact model, and immutable receipt to locate a unique native case.
This lookup avoids ambiguous display names and retains the complete restoration checks.
The lead owns launcher composition of the reviewed follow-up interfaces.

## Acceptance gates

P11 evidence must distinguish process exit from accepted numerical output.
It must record the actual Flow version, exact inputs, final simulation time, warnings, output roles, and justified numerical tolerances.
P11 acceptance includes a successful run, invalid inputs, execution failure, cancellation, restart, and a deterministic reference case.
The recorded runs passed the reference comparison and verified cleanup of all seven owned containers.
The trials exposed a container exit-code defect, whose separate repair passed real cancellation and deadline reruns.

P12 evidence must verify native pressure and saturation grids, summary curves, units, report times, and exact result lineage.
Comparison requires aligned reports, compatible grids, equal units, signed changes, and fixed legends.
Loading one result must preserve previously loaded results.
Saved project restoration must verify every selected result again.

P13 starts from a clean installation with documented launcher configuration.
Every domain step must use public MCP tools without hidden record creation or a custom server.
The workflow creates two named sessions, a layered model, and injection and production wells with visible completions.
It runs and loads a baseline, then clones a scenario, changes a control, runs again, and compares results.
It repeats relevant operations across MCP disconnection and project save and reopen, and it cancels an owned run.
Evidence must preserve requests, responses, native images, numerical checks, tested commits, tool versions, and the macOS environment.

P11, P12, and P13 close only after their reviewed PRs complete the corresponding acceptance criteria.
Required CI checks and documentation deployment must pass after integration.
This goal does not add Julia support or unrelated native editors.
