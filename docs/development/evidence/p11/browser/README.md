# P11 rendered guide review

The browser review passed on September 9, 2026, against clean source `11c4acd1dfc6aabe562406da0136134cd73837df` for PR #52.
The review covered the OPM user guide, developer guide, runtime evidence, and local navigation.
No guide correction was needed.
The [shared check](shared-check.log) passed Ruff, ty, 570 maintained tests, and the strict documentation build after evidence was added.
This evidence records documentation rendering, without repeating Flow or ResInsight acceptance.

## Build and browser result

The [strict build log](mkdocs.log) records a successful MkDocs build.
The [browser record](review.json) identifies the clean tested source, exact preview origin, versions, page checks, and local link checks.
Ten page visits across four paths returned HTTP 200.
All 85 local article and navigation links returned HTTP 200.
The browser reported no page errors, failed page images, or document overflow at 1440 by 1050 pixels.

The preview listened only on `127.0.0.1` and used no file URLs.
The browser context rejected every request outside that preview origin.
The record lists blocked Google Fonts, MathJax, and GitHub API requests.
The browser used Google Chrome 152.0.7977.84, Playwright 1.62.1, and Node.js v24.19.0.
The build used Python 3.12.13, MkDocs 1.6.1, and uv 0.9.18.

The [driver](review.cjs) derives from `/private/tmp/resinsight-p08-correction-review.cjs`.
The review read that helper before use.
The bounded changes record blocked requests and check primary navigation links alongside article links.
The [manifest](manifest.json) records every page visit, heading target, and screenshot name.
The [command result](command.log) and [server log](server.log) preserve observed execution output.

The commands below used the clean writer checkout before these evidence files were added:

```sh
cd /private/tmp/resinsight-p11-browser-review
uv sync --locked
uv run --locked mkdocs build --strict \
  > /private/tmp/resinsight-p11-browser-mkdocs.log 2>&1
NODE_PATH=/Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  /Users/lmoss/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /private/tmp/resinsight-p11-browser-review.cjs \
  /private/tmp/resinsight-p11-browser-review \
  /private/tmp/resinsight-p11-browser-output \
  /private/tmp/resinsight-p11-browser-manifest.json \
  > /private/tmp/resinsight-p11-browser-command.log 2>&1
```

The committed driver and manifest preserve those temporary command inputs.
The driver closed its browser and stopped its local server after review.
The [cleanup record](cleanup.json) records a subsequent listener check with no listener remaining on the preview port.
No Docker command, container, or ResInsight process was launched for this review.

## Visual inspection

The reviewer opened and inspected all nine saved screenshots.
Headings, prose, links, code highlighting, and both navigation columns remained legible.
The long image digest and Python lines use contained code scroll regions, with no whole-page overflow.
The user guide keeps numerical validity separate from independent reference agreement.
The evidence page keeps original failures, corrected trials, cleanup, and reference limitations visible.

| Screenshot | Inspected content |
| --- | --- |
| [User guide](user-guide.png) | FIELD profile, runtime pin, dependencies, and the selected user navigation entry. |
| [Python workflow](python-workflow.png) | Import and submission example, code highlighting, and contained horizontal code regions. |
| [Result policy](result-policy.png) | Accepted result meaning, separate reference agreement, immutable artifacts, and explicit failures. |
| [Developer guide](developer-guide.png) | Runtime limits, collection behavior, and the selected developer navigation entry. |
| [Output verification](output-verification.png) | Exact verification, maintained checks, and the link to runtime evidence. |
| [Manual runtime](manual-runtime.png) | Recorded trials, future manual commands, and the distinction between maintained and observed evidence. |
| [Runtime evidence](runtime-evidence.png) | Tested source identities, changed-control results, and the selected runtime navigation entry. |
| [Reference comparison](reference-comparison.png) | Numerical agreement, timestamp separation, tolerance, and reference limitations. |
| [Termination evidence](termination-evidence.png) | Original and repaired exit codes, owned cleanup, runtime versions, and integrated checks. |

This desktop browser review does not establish mobile layout or external resource availability.
The screenshots show the localhost preview with external requests blocked.
