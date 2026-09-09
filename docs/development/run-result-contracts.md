# Run and result contracts

This prerequisite supports P11 execution and P12 result access.
It extends existing records without adding a database table or schema version.
The contracts do not launch Docker, parse simulator files, or claim numerical acceptance.

## Execution ownership

`JobSubmission.execution` optionally records a `DockerExecution`.
Its image uses a pinned SHA256 digest.
The record includes the platform, container name, ownership token, runtime versions, command, mounts, and container working directory.
`program_version` records the expected program version for the pinned image.
The producing service must compare the actual run version with this expectation.
Docker client and server versions describe the observed runtime.

`DockerMount` records an absolute host source, absolute container target, and read-only setting.
Mount targets must be unique.
Mount paths cannot contain commas because Docker mount arguments use commas as separators.
For Docker execution, `JobSubmission.argv` contains only the absolute Docker executable path.
The controller builds container commands from the typed execution record.

`JobSubmission.run_metadata` optionally identifies an immutable `METADATA` artifact.
The workspace verifies that this artifact belongs to the job session.
A stored submission cannot change.
`Job.container_id` records the confirmed container identity once and cannot change or disappear.
A new job cannot claim a container identity before publication.
Container identity requires Docker execution metadata.

## Result manifest

`Result.manifest` optionally contains a `ResultManifest`.
Each manifest requires exactly one EGRID, INIT, UNRST, SMSPEC, and UNSMRY output.
Each output points to an immutable `OUTPUT` artifact.
Artifact records remain the only source of filenames.
The manifest also identifies numerical data and assessment evidence as separate `METADATA` artifacts.
All referenced artifacts must have distinct identities within the result session.

The active-cell map must match the result model and grid.
Restart report steps must increase and match the number of result reports.
`Result.report_series` remains the result's report-time record.
The workspace requires the exact successfully completed job before publishing a result.
Publication checks artifact existence and kinds, but does not parse numerical data or assessment evidence.
The producing and consuming services validate artifact content before use.

## Numerical data

`ResultDataset` defines the numerical data artifact's JSON structure.
It records the job, exact model revision, active-cell map, and report series.
These fields form an identity envelope that consumers compare with the stored result.
They do not create a second independently editable result record.

`CellPropertySeries` contains a name, unit, and report-major arrays.
Each array must match the active-cell count.
`SummaryCurve` contains a field or well scope, keyword, unit, and report-aligned values.
Only well curves require a well name.
Property names and curve identities must be unique.
All values must be finite.

`Unit.STOCK_TANK_BARREL_PER_DAY` represents `stb/day` with the volume-rate dimension.
The contract does not infer units from property or curve names.
The parser must verify each reported unit before publishing data.
Consumers must compare dataset identity and reports with the stored manifest and result.

## Checkpoints and compatibility

`ProjectCheckpoint.result_ids` records unique, stored results in the checkpoint session.
A comparison project can contain results from multiple model revisions.
Each result retains its exact lineage.
`ProjectCheckpoint.model` remains the primary revision association for the saved project.

Older records omit these new fields and remain readable through explicit defaults.
An absent manifest does not prove that outputs are available or validated.
P12 consumers must reject absent manifests instead of guessing files or using another result.
Existing error codes describe missing artifacts, invalid relationships, and immutable-record conflicts.

## Verification

Focused contract tests exercise serialization, output roles, session ownership, array shapes, curve identities, and Docker command metadata.
Workspace tests exercise output kinds, missing artifacts, immutable execution identity, result publication, and comparison checkpoints.
The shared repository command checks formatting, typing, maintained tests, and the documentation build.
These tests do not establish simulator or ResInsight acceptance.

On September 9, 2026, the shared command passed with 527 maintained tests and a strict documentation build.
After the fresh-process persistence tests changed, all nine focused tests passed again.
The tools were uv 0.9.18, Ruff 0.16.6, ty 0.0.79, pytest 9.1.1, and pre-commit 4.6.2.

The lead repeated the shared command after adding navigation and the delivery plan.
The [raw log](evidence/run-result-contracts/shared-check.log) records another pass with 527 maintained tests.
The [environment record](evidence/run-result-contracts/environment.json) identifies the tested source commit, documentation overlay, host, and tool versions.
The [browser record](evidence/run-result-contracts/review.json) covers four rendered pages and their local links.
The lead inspected every saved screenshot and found readable text and tables without page overflow.
The [contract page](evidence/run-result-contracts/run-result-contracts.png) and [delivery plan](evidence/run-result-contracts/p13-delivery.png) show representative layouts.
