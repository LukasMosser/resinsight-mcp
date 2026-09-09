# P08 numerical acceptance

Four isolated Flow trials passed on September 9, 2026.
The tested source commit is `f289e8eee5ea500f1a1f32535c6a262b35abaf16`, with a clean worktree.
Two runs used the preserved P07 SPE1 fixture, and two used `reference_specification()` through `SyntheticModelService`.
Each run used a fresh input directory and output directory.
The [acceptance record](acceptance.json) identifies the host, packages, runtime, and limits.

## Result

Every trial completed both report intervals and reached January 3, 2015, after two simulated days.
All compared parsed values agreed across repeated runs and between the generated model and P07.
The maximum absolute difference was zero for every compared quantity.
The [comparison record](comparison.json) preserves every tolerance and outcome.
The [numerical values](numerical-values.json) preserve all compared cell and summary arrays.

| Quantity | Day 1 | Day 2 | Unit | Absolute tolerance |
| --- | --- | --- | --- | --- |
| Cell pressure minimum | 4571.67138671875 | 4438.43212890625 | psia | 0.0009765625 |
| Cell pressure maximum | 5196.734375 | 5421.6787109375 | psia | 0.0009765625 |
| Field oil rate, `FOPR` | 20000 | 20000 | stb/day | 0.00390625 |
| Producer pressure, `WBHP:PROD` | 2905.093994140625 | 2783.449951171875 | psia | 0.00048828125 |
| Injector pressure, `WBHP:INJ` | 8251.8740234375 | 8308.6083984375 | psia | 0.001953125 |

Cell pressure comparisons cover all 300 active cells at both report times.
Pressure uses psia, absolute pounds per square inch.
Oil rate uses stock tank barrels per day.
The final pressure extrema also match the earlier [P07 record](../p07/acceptance.json).

## Tolerance basis

The rule was committed before the four trials ran.
Each absolute tolerance equals two representable output increments at the largest reference magnitude.
The calculation uses the numeric type returned by the official OPM reader, which was `float32` for these quantities.
Relative tolerance is zero.
This allows output rounding while keeping the comparison close to the recorded numerical precision.
Measured repeat differences do not increase the allowed tolerance.

Both repeatability pairs had zero difference at the recorded precision.
That result supports this comparison on the pinned runtime and tested host.
It does not establish independent simulator agreement, physical calibration, or cross-platform solver reproducibility.
Numerical acceptance covers the supplied two-day gas-injection reference.
Other supported specifications still require their own convergence checks.

## Inputs and mapping

The service imported the P07 fixture and created the generated model in separate workspace sessions.
The [P07 source record](p07-source-record.json) and [generated source record](generated-source-record.json) identify the immutable inputs.
The `sources` directory preserves the exact materialized input snapshots used for the trials.
The [generated receipt](generated-receipt.json) records its model revision and active-cell mapping.
Its source comments preserve the reusable specification and grid identifier.

OPM `Parser`, `EclipseState`, and `Schedule` established matching grid properties, fluid tables, initial state, connections, and report dates.
The [input record](input-semantics.json) preserves those parsed values.
The grid contains 10 by 10 by 3 cells, with every cell active.
OPM `EGrid` established the same active-cell order in every result.
The injector connects to zero-based cell `(0, 0, 0)`, at active index 0.
The producer connects to zero-based cell `(9, 9, 2)`, at active index 299.

OPM `ERst` read pressure from the restart results at report steps 1 and 2.
OPM `ESmry` read report times, units, field oil rate, and both well pressures.
The source declares FIELD units, and the summary reader reports `PSIA`, `STB/DAY`, and `DAYS`.
The analysis reads model values through supported APIs and makes no binary comparisons.

## Runtime and commands

The installed image is pinned to `sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1`.
The [image record](image-inspect.log) preserves its installed metadata.
The [Flow version](flow-version.log) is 2026.04, and the [Docker record](docker-version.log) reports 29.3.1.
The host is macOS 14.2.1 on arm64, with Python 3.12.13 and OPM Python 2025.10.
No image was pulled, and no runtime was installed.

Each container had two CPUs, 2 GiB memory, no network access, and a 60-second wall limit.
Flow used one MPI process and two OMP threads, with its default solver configuration.
The `.PRT` files preserve the complete solver configuration and final error summaries.
Each trial reports zero warnings, zero errors, and zero wasted solver iterations.
The full logs contain two completed timesteps per trial.

| Trial | Wall seconds | Command record | Flow log | Solver report |
| --- | --- | --- | --- | --- |
| P07 first run | 1.4047 | [Command](p07-1/flow.command.json) | [Log](p07-1/flow.log) | [Report](p07-1/SPE1.PRT) |
| P07 repeat | 0.4853 | [Command](p07-2/flow.command.json) | [Log](p07-2/flow.log) | [Report](p07-2/SPE1.PRT) |
| Generated first run | 0.5021 | [Command](generated-1/flow.command.json) | [Log](generated-1/flow.log) | [Report](generated-1/SYNTHETIC.PRT) |
| Generated repeat | 0.5680 | [Command](generated-2/flow.command.json) | [Log](generated-2/flow.log) | [Report](generated-2/SYNTHETIC.PRT) |

Complete local outputs remain under `/private/tmp/resinsight-p08-numerical-01`.
Generated binary result files remain outside Git.
The numerical record lists every output filename.
This is Python service acceptance, without ResInsight or a production MCP simulation workflow.
No native geometry or image result is claimed here.

## Repeat the trial

Use the already installed Docker Desktop runtime and approved image.
Choose a new output directory.
Run this command from the repository root:

```sh
uv run --locked --extra imports python tests/models/synthetic/acceptance.py \
  --output /private/tmp/resinsight-p08-numerical-new \
  --docker /Applications/Docker.app/Contents/Resources/bin/docker
```

The command refuses to pull an image.
A timed-out trial removes only its named container and records the failure.

## Maintained checks

The shared repository command passed all 419 tests, including 26 P08 tests.
Ruff, ty, and the strict documentation build passed.
The [check record](checks.json) identifies the tool versions, source commit, and command.
The [check log](checks.log) preserves the complete command output.
Three focused cleanup tests cover published revisions, uncertain publication, and unapplied import failures.

## Data attribution

The preserved and generated inputs derive from SPE1 data, copyright 2015 Statoil.
The upstream source commit is `0ea62974f24d70fc2b3e30d6aae8b76ef000dac1` in `OPM/opm-common`.
The [P07 source record](../../model-imports.md) describes the supported derived fixture.
The [Open Database License 1.0](http://opendatacommons.org/licenses/odbl/1.0/) applies to the source and derived inputs.
The [Database Contents License 1.0](http://opendatacommons.org/licenses/dbcl/1.0/) applies to individual contents.
These terms apply separately from the repository software license.
Retain the source attribution and applicable data notices with public results.
