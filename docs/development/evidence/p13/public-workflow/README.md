# P13 public workflow acceptance

Trial 04 completed the generated FIELD workflow through the shipped public MCP launcher.
The [lead acceptance decision](trial-04/lead-acceptance.json) confirms runtime acceptance after independent numerical, lifecycle, and image reviews.
The [automated record](trial-04/acceptance.json) preserves its earlier status before those reviews finished.
Required GitHub checks, evidence integration, and the P13 pull request remain separate delivery steps.
This folder also retains failed trials 02 and 03 without claiming their acceptance.

## Accepted trial

The [exact command](trial-04/command.json) ran on September 9, 2026.
The [versions](trial-04/versions.json) record macOS 14.2.1 on arm64, Python 3.12.13, and noneditable application and RIPS installations.
The original command record (archive member `trial-04/original-command-record.json`) retains the launch configuration recorded beside the installed runtime.
The driver source (archive member `trial-04/driver-source/run.py.txt`) and its six helper files preserve the exact executed Python code as text.

| Component | Tested source or version |
| --- | --- |
| Public driver | `b2724755ab223990a7bb19f425ad3fa064c64ff8` |
| Installed application source | `b4c414beee91a0fa419f04e7c7874d2b2108a5a7` |
| Native source | `9c920334e338dab4908aa4dabdfae22803e70411` |
| RIPS client | `2026.9.0.1` |
| OPM output reader | `2025.10` |
| Flow simulator | `2026.04` |
| Docker client and server | `29.3.1` |

The [merged P12 native record](https://github.com/LukasMosser/resinsight-mcp/blob/e84dfb300f7161d6d1ae9d1e7f34552f57bae662/docs/development/evidence/p12/native/README.md) preserves the native patches, builds, and trial 07 acceptance.
Its final `native-render-04` records identify this same native source.
This curation references those records without copying the separate native repair archive.
The recorded custom build is required and is not a released native distribution.

| Evidence | Accepted trial total |
| --- | ---: |
| Public request and response pairs | 354 |
| Passing automated checks | 854 |
| Expected negative tool outcomes | 13 |
| Original accepted PNGs | 29 |
| Complete numerical records | 6 |
| Cell values in those records | 10,800 |
| Curve values in those records | 36 |
| Signed comparisons | 18 |
| Exact retained export replies | 4 |
| Named sessions | 2 |
| SDK connections | 2 |
| Owned native lifetimes | 2 |
| Owned jobs and stopped containers | 3 |

The checks (archive member `trial-04/checks.json`) and events (archive member `trial-04/events.jsonl`) preserve the full observed sequence.
The public specification (archive member `trial-04/public-specification.json`) defines the generated `10 × 10 × 3` grid with 300 active cells.
The workflow creates PROD and INJ, exports their native completions, and publishes the baseline schedule.
It clones a scenario, reduces the producer oil target by 25 percent, and compares both accepted runs.
It verifies project reopening, SDK reconnection, session isolation, and cancellation through public tools.
The 13 expected negative outcomes confirm rejected foreign identities, stale references, and collection of the canceled run.

## Numerical effects

The baseline (archive member `trial-04/baseline-numerical.json`) and scenario (archive member `trial-04/scenario-numerical.json`) retain every requested cell value and summary point.
The same records remain exact after project reopening (archive member `trial-04/project-reopened-0-numerical.json`) and MCP restart (archive member `trial-04/mcp-restarted-0-numerical.json`).
Each grid contains 7,200 corner coordinates.
The independent exact specification comparison found zero corner difference.
The driver comparison against converted layer depths reached `1.8189894035458565e-12` feet within its declared `0.001` foot tolerance.

| Quantity | Day 1 | Day 2 |
| --- | ---: | ---: |
| Baseline field oil rate, stb/day | 20,000 | 20,000 |
| Scenario field oil rate, stb/day | 15,000 | 15,000 |
| Baseline PROD pressure, psi | 2834.9462890625 | 2713.801025390625 |
| Scenario PROD pressure, psi | 3322.380859375 | 3229.165771484375 |
| PROD pressure change, psi | 487.4345703125 | 515.36474609375 |
| INJ pressure change, psi | 0 | 0 |
| Grid pressure change range, psi | 0 to 53.89501953125 | 0 to 87.21044921875 |
| Water saturation change range | -4.027038812637329e-05 to 0 | -6.521493196487427e-05 to 0 |

All 18 public signed comparisons matched scenario values minus baseline values.
All four retrieved immutable exports matched their original records exactly.
Fresh completion intervals changed only through endpoint rounding after native project serialization.
Their maximum change was `1.8189894035458565e-12` feet under relative tolerance `1e-12` and zero absolute tolerance.
Cell identity, count, order, factors, permeability length, diameter, skin, status, and direction remained exact.
These checks establish data transport and scenario response without replacing an independent simulator reference comparison.

## Images

The lead and P12 reviewer each opened all 29 original PNGs.
The [image review](trial-04/lead-image-review.json) lists every file and records its visual limits.
There are two initial grid images and three comparison groups containing nine images each.
Each comparison group contains eight grid images and one summary image.
All images are `1200 × 800` pixels, and all 12 grid pairs retain common camera and legend settings.

[Initial pressure](trial-04/calls/0053-view_apply-0.png), [scenario pressure](trial-04/calls/0117-view_apply-0.png), and [scenario well pressure](trial-04/calls/0139-result_show_curve-0.png) show the first comparison stage.
The [reopened summary](trial-04/calls/0232-result_show_curve-0.png) and [restarted summary](trial-04/calls/0341-result_show_curve-0.png) preserve the scenario curve after both recovery steps.
The small top-down grid leaves broad margins and does not show the three layers separately.
Pressure units remain in observation metadata rather than native grid legends.
Subtle water saturation changes require the numerical comparisons.
The complete image list remains in the original review record.

## Recovery and cleanup

The driver saves the first project (archive member `trial-04/project-before-reopen.rsp`), reopens it, restores prepared receipts, and explicitly adopts the native wells.
It later saves the disconnect project (archive member `trial-04/project-before-disconnect.rsp`) and terminates its first owned native process.
The third job remains running across two SDK connections with the same container identity.
Public cancellation then records exit code `137` and confirmed termination, and result collection is rejected.
The second native lifetime restores the saved project and repeats numerical and image comparisons before saving the final project (archive member `trial-04/accepted-project.rsp`).

The [process review](trial-04/lead-process-verification.json) confirms both owned PIDs were absent after public termination.
The [container review](trial-04/lead-container-verification.json) confirms all three exact containers stopped with matching ownership labels and enforced limits.
The two accepted jobs exited with code zero.
The [public cleanup](trial-04/public-cleanup.json) and [job cleanup](trial-04/normal-job-cleanup.json) report no errors, unresolved jobs, or emergency actions.
Stopped containers remain because the public API does not remove them.
Saved projects retain their original absolute paths and require those original source files for reopening.

## Reproducible run inputs

The [bundle map](run-bundles.json) connects each retained output bundle to its exact job, result, model, grid, and output artifacts.
The baseline deck (archive member `trial-04/run-bundles/baseline/inputs/SCHEDULE.DATA`) and scenario deck (archive member `trial-04/run-bundles/scenario/inputs/SCHEDULE.DATA`) preserve the generated schedules.
Each accepted bundle retains EGRID, INIT, UNRST, SMSPEC, and UNSMRY outputs, plus Flow diagnostic and print logs.
The canceled job retains its input deck (archive member `trial-04/run-bundles/canceled/inputs/SYNTHETIC.DATA`) without presenting partial binary outputs as accepted results.
The baseline job (archive member `trial-04/baseline-job.json`) records the pinned image digest, platform, command, mounts, and resource limits.
The scenario job (archive member `trial-04/scenario-job.json`) preserves the same provenance for its independent run.

## Earlier failed trials

Trial 02 failed after public reopening and successful well adoption because the driver required exact floating-point definition equality.
Its [failure](failed-trial-02/failure.json) identifies `clone-PROD-adopted`, and its checks (archive member `failed-trial-02/checks.json`) retain that failed assertion.
The command (archive member `failed-trial-02/command.json`), driver source, raw calls, logs, and local reviews preserve this trial as failed.
It recorded 160 public calls, 198 checks, and 11 images without establishing complete acceptance.

Trial 03 accepted the rounded definition but failed an exact comparison of newly generated completion endpoints.
Its [failure](failed-trial-03/failure.json) identifies `project-reopened-PROD-immutable-export`.
The command (archive member `failed-trial-03/command.json`), checks (archive member `failed-trial-03/checks.json`), driver source, raw calls, logs, and local review remain unchanged.
It recorded 174 public calls, 478 checks, and 11 images without establishing complete acceptance.
Trial 04 separates exact stored exports from the narrowly allowed rounding in fresh endpoints.

## Raw evidence archive

Download [raw-evidence.tar.gz](raw-evidence.tar.gz) for the bulk generated records.
The [archive index](archive-index.json) identifies its source commit, retained files, and original manifest.
Archive member paths use this evidence folder as their root.
Extract the archive into an empty directory to inspect its original records.

```sh
mkdir extracted-evidence
tar -xzf raw-evidence.tar.gz -C extracted-evidence
```

The archive preserves full calls, arrays, source snapshots, run bundles, projects, failed images, and logs without changing their contents.
The accepted images and final review decisions remain directly readable.
The retained files and archive together preserve the complete original payload.
The browser screenshots record the earlier expanded evidence layout.

## Curated payload

The manifest (archive member `manifest.json`) maps every copied record and source snapshot to its origin.
The accepted trial has 29 original PNGs.
The archive retains 22 earlier failed-trial PNGs, and both failure records remain directly readable.
The payload excludes mutable workspace databases, installed wheels, repeated materializations, unneeded caches, and incomplete canceled binary outputs.
The native project sidecar is retained with its saved project snapshot.
The lead reviewed this folder locally before the owner authorized evidence integration.
The original runtime decisions and inputs remain unchanged for reviewed integration.

## Rendered documentation review

The lead reviewed the acceptance guide, evidence overview, and numerical section in the in-app browser with a `396 × 858` screenshot size.
The [browser record](browser/browser-review.json) preserves the source state, original screenshots, and cleanup report.
The [guide](browser/acceptance-guide.png), [overview](browser/evidence-overview.png), and [numerical section](browser/evidence-numerics.png) use normal horizontal table overflow at that narrow screenshot size.
These three documentation screenshots are separate from the 29 native acceptance images.
The lead closed the browser tab and preview server after review.
