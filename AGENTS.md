# Agent guide

Read this guide before you change this repository. Use Simple English in code comments, documents, commit messages, and chat. The rules apply to every agent.

## Work and ownership

Use `gpt-6-astra` with low reasoning for all subagents. Give each agent one bounded task with named files. Use a separate Git worktree and a `codex/` branch for each agent that writes files.

Commit each complete change on the agent branch. Do not switch branches in another agent's worktree. The lead agent resolves conflicts and brings reviewed commits into the feature branch.

Keep shared interfaces under one owner. Agree on interface changes before dependent agents use them. Record scope changes in the development documentation.

## Simple English

Write for a reader outside the field. Use active voice and American spelling. Define technical terms at first use, in fewer than ten words.

Use these writing rules:

- Keep instructions within 20 words per sentence and give one instruction per sentence.
- Keep descriptions within 25 words per sentence and six sentences per paragraph.
- Put a condition before its command, with a comma.
- Use simple tenses and complete grammar, without contractions.
- Use `can`, `will`, and `must` for permission, possibility, and requirements.
- Use one word for one meaning throughout a document.
- Use “make sure that” for prose about validation and “configuration” for configuration.
- Preserve code, identifiers, commands, paths, product names, quoted errors, and facts.
- Remove filler, semicolons, em dashes, and decorative emphasis.

Chat replies use prose and contain at most five sentences. Put the answer first. Do not use headings, lists, tables, or bold in chat replies.

This guide uses Plain mode from the supplied Simple English rules. It does not claim ASD-STE100 compliance. License text, code, and exact quotations keep their original wording.

## Scope and design

The foundation contains repository tools and documents. Do not add application code as part of the foundation. Follow the accepted work package before you implement a feature.

Use explicit, typed interfaces and clear failures. Do not add fallback paths, silent backend changes, byte-level checks, or byte-level tests. Use supported library interfaces and test observable behavior.

Keep ResInsight, model inputs, simulator runs, and MCP transport in separate modules. MCP is the Model Context Protocol for tool access. Do not invent upstream methods or claim that visual edits automatically change simulator inputs.

## Tests and review

Use uv, ty, Ruff, pre-commit, and the shared repository command. Follow [the test guide](docs/development/testing-and-review.md). Add focused tests for useful behavior and known failures, without a target of 100 percent coverage.

Every code review must assess these concerns:

- Find duplicate behavior and duplicate sources of truth.
- Review branching, nesting, and interface complexity.
- Assess names, ownership, coupling, and maintenance cost.
- Make sure that tests cover the change's public behavior and important failures.
- Make sure that logs and screenshots support the stated result.

Do not add tests that only repeat implementation details. Do not claim application tests passed when no application tests exist. Run the relevant checks again after a change that affects their result.

## Git and pull requests

A pull request, or PR, is a proposed change for review. Give each major feature its own PR against `main`. Include the problem, resulting behavior, scope, and evidence in the PR.

Link the work issue and use its delivery milestone and relevant labels. Follow the [project organization guide](docs/development/project-organization.md). Close the issue only when the PR completes its scope.

Keep one logical change per commit. Use a short imperative subject and a body that explains why the change exists. Describe relevant evidence and constraints in the body.

Bring agent commits into the feature branch with reviewed cherry-picks. Collapse repair commits into their logical change before merge. Use a squash merge for one logical change or a rebase merge for a reviewed logical series.

Keep `main` linear and ready for use. Do not force-push `main` or bypass required checks. Keep unrelated changes out of the PR.

## Documents and releases

MkDocs contains user and developer documentation. User pages describe current behavior. Put plans, open decisions, and unimplemented work only under `docs/development/`.

Use GitHub Actions for automation and GitHub Releases for releases. Include logs for command changes and screenshots for visible changes. Record the tested commit and tool versions with evidence.

Ask the owner when a decision changes product scope, licensing, public visibility, supported physics, or a costly runtime requirement. Continue independent work while a decision remains open. An unanswered question does not authorize publication or spending.
