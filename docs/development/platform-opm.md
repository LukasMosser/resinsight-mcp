# OPM on macOS

The OPM part of P01 now runs on the selected macOS arm64 host.
P01 is the first platform experiment.
This result proves a bounded simulator run, not the complete ResInsight or MCP workflow.
The experiment does not add an application adapter.

## Source findings

The [official OPM instructions](https://opm-project.org/?page_id=36) support macOS through source builds and container execution.
The [container tutorial](https://opm-project.org/?page_id=853) names the `openporousmedia/opmreleases` image.
The [2026.04 arm64 image metadata](https://hub.docker.com/v2/repositories/openporousmedia/opmreleases/tags/2026.04_arm64) identifies a Linux arm64 image, so Intel emulation is unnecessary.
These source claims alone do not prove that the image runs on this host.

The input comes from `OPM/opm-common` at tag `release/2026.04/final`.
Its commit is `0ea62974f24d70fc2b3e30d6aae8b76ef000dac1`.
The [original SPE1 file](https://github.com/OPM/opm-common/blob/0ea62974f24d70fc2b3e30d6aae8b76ef000dac1/tests/SPE1CASE1.DATA) defines a 10 × 10 × 3 grid without include files.
A deck is the simulator input file.
The experiment retains that source deck and a derived deck with corrected well limits.

## Runtime findings

The run took place on September 8, 2026, on a Darwin arm64 host.
Docker Desktop 4.67.0 started without a setup prompt.
Its bundled client and Linux arm64 engine both report version 29.3.1.
The container reports `flow 2026.04`.

The container used two CPUs, 2 GiB of memory, and no network access.
It received a read-only input mount and a writable output mount.
The unchanged source failed with exit status 1 because its two-well limit conflicts with four scheduled wells.
The derived deck changes `WELLDIMS` to `4 1 1 4 /` and preserves the full schedule.

The derived run returned exit status 0.
Flow reported 300 active cells, three fluid phases, and 120 completed report steps.
The final report date is December 29, 2024, at 3,650 simulated days.
Flow used 123 timesteps and reported 1.46 seconds of simulation time.
Its final totals report zero wasted linearizations and iterations.

The run writes `EGRID`, `INIT`, `UNRST`, `SMSPEC`, `UNSMRY`, `ESMRY`, and `RSM` results.
The text summary contains dated saturation and well results through the final report date.
This acceptance uses simulator records and report meaning, without binary comparisons.
Opening and querying the binary results in ResInsight remains a separate P01 step.

## Warnings and limits

Flow reports unsupported `NOECHO` and `ECHO` input keywords.
It also reports unhandled `DATE/DAY`, `DATE/MONTH`, and `DATE/YEAR` summary requests.
The restart writer reports that it does not handle `WELSPECS` output.
The complete log preserves these warnings.

These warnings do not prevent this run from reaching its final date.
They limit the claim that all requested report content exists.
This experiment does not establish restart equivalence or numerical agreement with an independent simulator.
It does not establish job cancellation or recovery behavior.

The image does not include the Python `opm` package.
The experiment does not install a replacement reader in the image.
ResInsight result loading and supported numerical queries remain acceptance work for the combined platform proof.

## Repeat the run

Use the installed Docker Desktop application and its bundled client.
Run the commands from the repository root.
Start Docker Desktop before these commands.
Use an empty experiment output directory to keep evidence from separate runs distinct.

```sh
OPM_IMAGE='openporousmedia/opmreleases@sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1'
OPM_DOCKER='/Applications/Docker.app/Contents/Resources/bin/docker'
OPM_EXPERIMENT="$PWD/experiments/platform/opm"
mkdir -p "$OPM_EXPERIMENT/output"
"$OPM_DOCKER" pull --platform linux/arm64 "$OPM_IMAGE"
"$OPM_DOCKER" run --rm --platform linux/arm64 --cpus 2 --memory 2g \
  --network none "$OPM_IMAGE" flow --version
"$OPM_DOCKER" run --rm --platform linux/arm64 --cpus 2 --memory 2g \
  --network none \
  --mount "type=bind,source=$OPM_EXPERIMENT/input,target=/input,readonly" \
  --mount "type=bind,source=$OPM_EXPERIMENT/output,target=/output" \
  "$OPM_IMAGE" flow /input/SPE1CASE1.DATA --output-dir=/output
```

The image is pinned to its registry digest, an exact image identifier.
The limits above bound CPU and memory use.
The observed run completed in seconds, but the command does not set a time limit.
The original run used the same arguments and a temporary worktree path.

## Evidence and licenses

The experiment files live under `experiments/platform/opm/` in the repository.
The `evidence/` directory contains the version records, full run logs, and exit statuses.
Generated binary results stay outside Git in the experiment output directory.
The [experiment README](https://github.com/LukasMosser/resinsight-mcp/tree/main/experiments/platform/opm) records exact input provenance and license links.

OPM Flow uses GPL version 3 or later.
The SPE1 deck uses ODbL 1.0, and its contents use DbCL 1.0.
The derived input preserves those terms and the Statoil source notice.
Public results require the applicable source and ODbL notice.
