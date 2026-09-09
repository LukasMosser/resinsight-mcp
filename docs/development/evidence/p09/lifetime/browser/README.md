# Rendered well guide review

The browser review tested source `c7c3629cd3fcf634d922176eee44ce3e96c86bb6` from a clean worktree.
The owner explicitly approved a localhost preview after the earlier browser restriction.
This record completes that rendered guide review and does not repeat native application acceptance.
No ResInsight process or simulator was launched.

## Commands and environment

The preview used Python's HTTP server bound to `127.0.0.1` on an assigned free port.
The [browser helper](review.cjs) starts that server and closes its browser and server in `finally`.
The helper uses the lead's reviewed preview pattern with same-page navigation handling and explicit blocked-request recording.
The [manifest](manifest.json) identifies all six screenshot targets.

```sh
uv sync --locked --offline
uv run --locked mkdocs build --strict
NODE_PATH=/Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  /Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /private/tmp/resinsight-well-browser-output/review.cjs \
  /private/tmp/resinsight-well-browser-review \
  /private/tmp/resinsight-well-browser-output \
  /private/tmp/resinsight-well-browser-output/manifest.json
```

The server command inside the helper was:

```sh
/private/tmp/resinsight-well-browser-review/.venv/bin/python \
  -u -m http.server 0 --bind 127.0.0.1 \
  --directory /private/tmp/resinsight-well-browser-review/site
```

The strict build passed with MkDocs `1.6.1` and Material `9.7.7`.
The [browser record](review.json) identifies Chrome `152.0.7977.84`, Playwright `1.62.1`, and Node `v24.19.0`.
Its source record predates this evidence-only commit.

## Browser results

All six page visits returned HTTP 200 at a 1440 by 1050 viewport.
All 102 unique local article and navigation destinations returned HTTP 200.
All article images loaded with positive native dimensions.
No page errors, document overflow, or overflowing article code and table regions occurred.
The [server log](server.log) records local requests.

The helper blocked every browser request outside the preview origin.
The record lists blocked Google Fonts, MathJax, and GitHub metadata requests.
These well pages remained readable with local styling and available fonts.
No file URLs or external network fallback supplied page content.

Two initial helper attempts stopped before completing the review.
The first exposed a null navigation response when only the same-page fragment changed.
The second used an exact sentence locator that did not match its longer paragraph.
The accepted helper resets each visit and locates the native image by its accessible label.
Neither helper correction changed a guide or an application file.

## Visual review

The reviewer opened and inspected all six saved screenshots.
The user guide has readable prose, wrapped identifiers, a clear operation list, and visible navigation.
The lifetime section presents retained sources, receipt lookup, explicit case restoration, well adoption, and stale references without overlap.
The developer section keeps persistence and restoration details under the expected heading.
The acceptance page separates historical trials, installed provenance, exact saved-project results, and scope limits.

The embedded native image appears at its intended aspect ratio with its caption nearby.
Its three-layer slice, PROD marker, and color legend remain visible.
Opaque cells still conceal the interior well segment, as the accompanying text states.
The navigation exposes both the user guide and persistent lifetime evidence.
No concrete guide defect required a source correction.

- [User well guide](user-guide.png)
- [Working case restoration](lifetime-restoration.png)
- [Developer lifetime section](developer-lifetime.png)
- [Acceptance record](acceptance-record.png)
- [Saved-project evidence](saved-project-evidence.png)
- [Embedded native result](native-result-image.png)

This review covers rendered documentation on the recorded desktop viewport.
It does not establish new native behavior or full public MCP workflow acceptance.
