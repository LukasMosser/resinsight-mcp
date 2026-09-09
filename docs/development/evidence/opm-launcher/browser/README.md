# Rendered OPM launcher guide review

This review tested source `8e21fe376e054ca881bc8c3523ffaf2db1c17b62` from a clean worktree.
The owner approved a localhost-only preview for the PR55 guides.
The scope covers connection configuration, the FIELD workflow tutorial, view recovery, and launcher evidence with relevant navigation.
The linked installed OPM record was also checked for its pending acceptance statement.
No MCP application server, ResInsight process, Docker command, or simulator ran during this browser review.

## Commands and environment

The [build log](build.log) records a passing strict documentation build.
The [helper](review.cjs) uses the previously reviewed localhost browser pattern.
It starts Python's HTTP server on `127.0.0.1` with a free local port.
It blocks browser requests outside that exact origin and closes its browser and server in `finally`.
The [manifest](manifest.json) identifies eleven screenshot targets across five pages.

```sh
uv sync --locked --offline
uv run --locked mkdocs build --strict
NODE_PATH=/Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  /Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /private/tmp/resinsight-mcp-browser-output/review.cjs \
  /private/tmp/resinsight-mcp-browser-review \
  /private/tmp/resinsight-mcp-browser-output \
  /private/tmp/resinsight-mcp-browser-output/manifest.json
```

The helper starts this preview command:

```sh
/private/tmp/resinsight-mcp-browser-review/.venv/bin/python \
  -u -m http.server 0 --bind 127.0.0.1 \
  --directory /private/tmp/resinsight-mcp-browser-review/site
```

The build used MkDocs `1.6.1` and Material `9.7.7`.
The [browser record](review.json) identifies Chrome `152.0.7977.84`, Playwright `1.62.1`, and Node `v24.19.0`.
Its tested source predates this evidence-only commit.

## Results and visual review

All eleven visits and 92 unique local article and navigation destinations returned HTTP 200.
The browser reported no page errors, missing article images, document overflow, or overflowing article code and table regions.
The viewport was 1440 by 1050.
The [server log](server.log) preserves local requests.
Google Fonts, MathJax, and GitHub metadata requests were blocked and recorded.
No file URLs or external network fallback supplied content.

The reviewer inspected all eleven screenshots.
The connection guide presents optional configuration and the installed command without clipped lines.
The workflow tool table wraps long identifiers and keeps each task aligned with its tools.
The tutorial shows ordered public operations, changed-scenario identity, explicit restoration, and cancellation outcomes.
The view guide separates scene recovery, stale bindings, successful edits, and failed images.
The side navigation exposes the FIELD tutorial, view guide, launcher evidence, and installed OPM checks.

The launcher evidence distinguishes the earlier native session trial from later installed discovery checks.
The installed OPM page explicitly keeps full P13 simulation, comparison, cancellation, and project recovery acceptance pending.
The screenshot positions were adjusted to show complete recovery paragraphs and the pending acceptance statement.
No concrete rendering defect required a guide correction.

- [Connection guide](connection-guide.png)
- [Installed OPM configuration](opm-configuration.png)
- [Workflow tool table](workflow-tool-table.png)
- [FIELD workflow start](workflow-start.png)
- [Scenario comparison](scenario-comparison.png)
- [Workflow recovery](workflow-recovery.png)
- [View guide](view-guide.png)
- [View recovery](view-recovery.png)
- [Launcher evidence](launcher-evidence.png)
- [Installed OPM evidence](opm-evidence.png)
- [Pending acceptance](pending-acceptance.png)

This review completes the rendered documentation check on the recorded desktop viewport.
It does not establish P12 native results or P13 runtime acceptance.
The native acceptance records and owner review remain separate.
