# Workspace journal deletion evidence

This repair addresses [issue 31](https://github.com/LukasMosser/resinsight-mcp/issues/31).
Concurrent SQLite journal deletion caused a valid workspace read to return `invalid_path` on September 8, 2026.
The initial pathname check rejected a regular sidecar with zero links.
The later descriptor check already accepted that state.
Both checks now use the same sidecar policy.
The main database and artifact files still require one link.

## Original failure

The failure appeared during `test_recovery_refuses_live_supervisor` in a shared repository check.
That run reported one failure and 328 passing tests.
The supervisor recorded `Execution outcome: cancel; exit status: -15`.
The client failed while polling the stored result after requesting cancellation.

The [original reproduction log](reproduction-original.log) preserves the separate journal deletion trial.
The [exact script](reproduction-script.txt) runs one SQLite writer beside repeated file checks in a new temporary workspace.
It wraps the regular-file check to report metadata and then calls the unchanged check.
It does not fabricate metadata or signal processes.
The original trial failed after 213 file checks and 39 commits.
The rejected metadata reported zero links and regular-file mode `0o100600`.

The script catches its exception and returns status zero even when the guard fails.
Read its `FAILURE` output when assessing the outcome.
Its `unlinked_handles` counter includes pathname and descriptor metadata, despite the original label.
The [repaired trial](reproduction-after.log) uses the same script.
Counts depend on scheduling and do not define an acceptance threshold.

## Maintained regression

The regression uses public `get_session()` with a controlled metadata boundary.
A real SQLite commit deletes an open journal before that boundary returns its actual metadata.
The read must return the committed session on its first attempt.
Separate cases reject an unlinked main database, hard links, symbolic links, directories, and named pipes.

The [before log](regression-before.log) records one failed regression and nine passing rejection cases.
The [after log](regression-after.log) records all ten cases passing with the repaired guard.
The before run used the original guard.

## Repository checks

The [environment record](environment.json) lists the source baseline, host, and tool versions.
The tested source commit is `ef8b7df8f1c285764475b2d033694e16185abecd`.
The [source commit log](source-commit.log) records its passing repository pre-commit hook.
The [affected tests](affected-tests.log) passed all 94 workspace and job cases.
The [shared check](shared-check.log) passed Ruff, formatting, ty, all 282 tests, and the strict documentation build.
These runs used macOS 14.2.1, Python 3.12.13, and SQLite 3.50.4.
They exercised local child processes but did not launch ResInsight or a simulator.

## Commands and scope

The deterministic runs used the locked repository environment:

```sh
.venv/bin/python -m pytest tests/workspaces/test_database_files.py -q
```

The affected and shared checks used these commands:

```sh
UV_CACHE_DIR=/private/tmp/resinsight-mcp-uv-cache LC_ALL=en_US.UTF-8 \
  uv run --locked pytest tests/workspaces tests/jobs -q
UV_CACHE_DIR=/private/tmp/resinsight-mcp-uv-cache LC_ALL=en_US.UTF-8 \
  uv run --locked python scripts/check.py
```

Run the separate scheduling trial with the preserved input:

```sh
.venv/bin/python - < docs/development/evidence/workspace-journal/reproduction-script.txt
```

The trial creates only a new `/private/tmp/p06-journal-census-*` workspace and retains it for inspection.
This evidence covers local SQLite file handling and public reads.
It does not establish power-loss durability or network filesystem support.
