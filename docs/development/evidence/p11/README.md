# P11 Flow acceptance evidence

The bounded service trials completed on September 9, 2026.
The [acceptance index](acceptance.json) identifies the source commits, results, containers, and individual trial records.
The initial trials used clean source commit `405dec28de4ea129eebc81c45fb7d36c4d69b3c1`.
The final Flow source is `cd97f2f14ea1e5ed1daccd84889ac7614a7deac2`.
The Docker termination repair is `dccf25e80c538c7ef26baba7fc5b18b817e53965`.
The corrected trials also used a clean source worktree.

## Successful runs and lineage

The [baseline](baseline-trial.json) and [changed-control trial](changed-trial.json) each completed two simulated days with 300 active cells.
Both results passed `opm-field-validity-v1` and exact output verification.
Each submission came from a separate client process that exited before polling and collection.
A fresh service reopened the workspace, confirmed the job, and collected its result.
Another service reopen returned the same result.
The raw request, submission, job, container, collection, and log records remain beside each trial.

The [changed schedule](changed-schedule.inc) reduces the producer oil target from 20,000 to 15,000 stock tank barrels per day.
The [baseline dataset](baseline-dataset.json) and [changed dataset](changed-dataset.json) preserve every returned numerical value and active-cell corner.
The two changed field oil rates equal the new target.
At the second report, producer pressure rises from 2783.45 to 3281.65 psia.
The datasets have identical geometry, active-cell order, and report dates.
Their model revisions, jobs, result identifiers, and grid identifiers remain distinct.

The [baseline assessment](baseline-assessment.json) and [changed assessment](changed-assessment.json) retain the full parsed INIT and summary references.
Their immutable producer assessments do not claim independent numerical reference agreement.
The separate assessment below records the baseline reference comparison.

## Independent reference comparison

The [reference assessment](reference-assessment.json) passes 104 checks against the preserved P08 `p07-1` outputs.
It compares every parsed numerical output array and all 7,200 active-cell corner coordinates.
All floating-point differences are zero.
The tolerance is two output-dtype increments at the largest absolute reference magnitude, with zero relative tolerance.
Parsed simulation identities also match exactly.
This earlier OPM run is not an independent physical truth or a different simulator.

The [raw comparison](reference-assessment-raw.json) retains one metadata difference in SMSPEC `RUNTIMEI`.
Its compute-start and write timestamps differ because the runs happened at different times.
The [OPM implementation](https://github.com/OPM/opm-common/blob/release/2026.04/final/opm/io/eclipse/OutputStream.cpp#L647-L682) defines those fields at indices 3 through 14.
The refined assessment records those timestamps separately and checks all remaining simulation metadata exactly.
No numerical tolerance changed after comparison.
The reference fixture and its source notices remain under `tests/simulators/opm/data/reference/`.

## Cancellation, deadlines, and failure

The [long schedule](long-schedule.inc) contains 255 reports for in-flight cancellation and one-second deadline trials.
The [memory failure](memory-failure-trial.json) used an explicit 16 MiB limit.
Docker recorded exit 137 and `OOMKilled=true` for that failure.
Collection rejected every canceled or failed job.
The raw requests and container inspections record the actual limits and disabled networking.

The original [cancellation](canceled-trial.json) and [deadline](deadline-trial.json) trials exposed a terminal status defect.
Their stored jobs reported local Docker log-reader exit 0 while the stopped containers reported 137.
The separate repair uses the inspected container exit code for these termination paths.
The corrected [cancellation](canceled-repaired-trial.json) and [deadline](deadline-repaired-trial.json) now record job and container exit 137.
The original and corrected records remain together.
The deadline wall time includes bounded stop and local cleanup after the one-second deadline.

The [cleanup record](cleanup.json) confirms verified removal of all seven stopped trial containers.
Each removal checked the saved container identifier, name, image, and ownership label.
A successful complete daemon inventory then established each container's absence.
The [cleanup log](cleanup-client.log) reports seven removals and seven confirmed absences.
The host output directories remain available for the native P12 acceptance.
Cleanup did not relaunch a simulator or open ResInsight.

## Runtime and tool versions

The [runtime preflight](runtime-preflight.json) passed with the final Docker repair source.
It confirms the pinned local image, `linux/arm64`, and Docker client and server 29.3.1.
The actual Flow banner is 2026.04 in both successful run logs and assessments.
The [environment](environment.json) records the initial source and Python package versions.
The [tool record](tool-versions.json) separately identifies versions captured during evidence curation.
Python is 3.12.13, OPM is 2025.10, and NumPy is 2.5.3.

The successful runs used two CPUs, 2 GiB, disabled networking, and a 60-second wall limit.
All other trials used one CPU and stayed within those maximum limits.
No image pull or ResInsight process occurred in this lane.
The [Flow checks](focused-checks.log) passed 27 focused tests.
The [Docker repair checks](docker-repair-checks.log) passed 11 tests.
Both final source commits passed the normal hook, which runs the shared repository command.

The integrated feature passed 570 maintained tests, Ruff, ty, and strict MkDocs through the [shared command](integration/shared-check.log).
The [integration environment](integration/environment.json) identifies the tested commit and tool versions.
The [lead review](integration/lead-evidence-review.log) independently validated saved identities, limits, complete datasets, cleanup, and reference agreement.
This integration check did not repeat the native runtime trials.

The approved [localhost browser review](browser/README.md) passed ten page visits and 85 local links.
The lead inspected all nine guide screenshots and found no layout defect.
The preview kept external requests blocked and closed its browser and server after inspection.

## Manual probe and evidence scope

The maintained manual probe is `tests/simulators/opm/manual_acceptance.py`.
It uses the public import and Flow services, preserves exact job evidence, and removes only verified owned containers.
Its read-only comparison mode passed the same 104 numerical checks against the existing baseline outputs.
The [help log](manual-probe-help.log) and [comparison log](manual-probe-reference-check.log) record those checks.
The [curation check](curation-checks.log) validates trial identities, limits, datasets, cleanup, and agreement between both comparison drivers.

The maintained probe was prepared after these trials and was not used to relaunch them.
The final runtime driver, reference driver, and cleanup driver remain as exact text records in this directory.

The final runtime driver text records the version used for the corrected reruns.
Its baseline and adverse routines also preserve the earlier trial procedure.
The recorded input requests and job submissions are the authority for each trial's actual arguments.
The [service guide](../../opm.md) documents commands for future manual runs.

This directory contains curated JSON, logs, and the two changed schedules.
It does not contain the working database or duplicate staged output files.
The original local workspace remains under `/private/tmp/resinsight-p11-runtime-20260909/workspace`.
Its baseline and changed result identifiers are recorded in the acceptance index.
A future manual run creates a new workspace and identifiers.

## Data notices

These numerical records derive from the maintained SPE1 source fixture.
Copyright (C) 2015 Statoil applies to the source data.
The database uses the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Individual contents use the [Database Contents License 1.0](https://opendatacommons.org/licenses/dbcl/1-0/).
The changed schedules retain the original source notices.
These data notices remain separate from the repository software license.
