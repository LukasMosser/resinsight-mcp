# GitHub organization

Work issues record planned changes and their acceptance evidence.
A milestone groups issues and pull requests by delivery outcome.
A pull request, or PR, contains a concrete change for review.

The [implementation plan](implementation-plan.md) defines the work package scope.
GitHub records the current issue state, dependencies, and review progress.
The [milestone list](https://github.com/LukasMosser/resinsight-mcp/milestones?state=all) shows the delivery groups without invented due dates or priorities.

## Labels

A kind label describes the type of work.
An area label identifies the affected part of the project.
The repository manages these labels and retains the existing support labels.

| Label | Meaning |
| --- | --- |
| `bug` | Existing behavior does not meet its stated contract. |
| `enhancement` | Add or extend application behavior. |
| `documentation` | Change guides, plans, or reference pages. |
| `maintenance` | Change repository tools, automation, or packaging. |
| `research` | Resolve a technical question with recorded evidence. |
| `dependencies` | Update external packages or workflow actions. |
| `area:core` | Shared contracts, workspaces, protocol handling, or job control. |
| `area:resinsight` | Application sessions, views, images, or application integration. |
| `area:models` | Model inputs, generated models, wells, or schedules. |
| `area:opm` | OPM execution and its acceptance evidence. |
| `area:julia` | Julia execution and result transfer. |
| `blocked` | An external prerequisite or an unresolved decision prevents progress. |

Give each work issue a primary kind label.
Add area labels that identify its scope.
Keep package identifiers in issue titles instead of creating a label for each package.

## Milestones and work issues

The Foundation milestone covers the repository foundation and this organization update.
Close it after both PRs merge.
Keep later milestones open until their acceptance evidence exists.

| Milestone | Work issues |
| --- | --- |
| [Foundation](https://github.com/LukasMosser/resinsight-mcp/milestone/1) | [Foundation PR #1](https://github.com/LukasMosser/resinsight-mcp/pull/1) and the organization PR. |
| [macOS feasibility and contracts](https://github.com/LukasMosser/resinsight-mcp/milestone/2) | [P01](https://github.com/LukasMosser/resinsight-mcp/issues/2), [P02](https://github.com/LukasMosser/resinsight-mcp/issues/3). |
| [Sessions and native images](https://github.com/LukasMosser/resinsight-mcp/milestone/3) | [P03](https://github.com/LukasMosser/resinsight-mcp/issues/4), [P04](https://github.com/LukasMosser/resinsight-mcp/issues/5), [P05](https://github.com/LukasMosser/resinsight-mcp/issues/6), [P06](https://github.com/LukasMosser/resinsight-mcp/issues/7). |
| [OPM first release](https://github.com/LukasMosser/resinsight-mcp/milestone/4) | [P07](https://github.com/LukasMosser/resinsight-mcp/issues/8), [P08](https://github.com/LukasMosser/resinsight-mcp/issues/9), [P09](https://github.com/LukasMosser/resinsight-mcp/issues/10), [P10](https://github.com/LukasMosser/resinsight-mcp/issues/11), [P11](https://github.com/LukasMosser/resinsight-mcp/issues/12), [P12](https://github.com/LukasMosser/resinsight-mcp/issues/13), [P13](https://github.com/LukasMosser/resinsight-mcp/issues/14), [P16-OPM](https://github.com/LukasMosser/resinsight-mcp/issues/17), [P17-OPM](https://github.com/LukasMosser/resinsight-mcp/issues/18). |
| [Julia support](https://github.com/LukasMosser/resinsight-mcp/milestone/5) | [P14](https://github.com/LukasMosser/resinsight-mcp/issues/15), [P15](https://github.com/LukasMosser/resinsight-mcp/issues/16), [P16-Julia](https://github.com/LukasMosser/resinsight-mcp/issues/19), [P17-Julia](https://github.com/LukasMosser/resinsight-mcp/issues/20). |

P16 and P17 each have separate OPM and Julia issues.
This split keeps the OPM release independent of later Julia delivery.
Milestone order does not prevent Julia research from starting while OPM work continues.

## Dependencies and blockers

A dependency is work that another issue needs first.
Use GitHub's native `blocked by` relationships for dependencies between work issues.
Keep the issue body clear about the evidence that each dependency supplies.

Use the `blocked` label only for an external prerequisite or unresolved decision.
Name the blocker and the condition that clears it in the issue body.
Remove the label when that condition clears.

Do not copy all package dependencies into `blocked` labels.
Those labels require manual updates and can misstate readiness after a dependency closes.
Read the native issue relationships when choosing work that can start.

## Pull requests

Create a feature PR when a concrete change exists.
Link its work issue in the description.
Use the same milestone and relevant kind and area labels as the work issue.

A closing reference closes a linked issue when a PR merges.
Use a closing reference only when the PR completes the issue's acceptance criteria.
For partial work, use an ordinary issue link and state what remains.

Include the acceptance evidence that reviewers need to assess the change.
Follow the [testing and review guide](testing-and-review.md) for that evidence.
Do not create empty PRs for future packages or close application issues through documentation changes alone.
