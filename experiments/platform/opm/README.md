# OPM platform experiment

This experiment runs OPM Flow 2026.04 in the official Linux arm64 image on macOS.
The input contains 300 cells and uses the SPE1 schedule from OPM.
The run uses at most two CPUs and 2 GiB of memory.
The container has no network access.

## Source and license

The original input is `input/upstream/SPE1CASE1.DATA`.
It comes from [OPM/opm-common](https://github.com/OPM/opm-common/blob/0ea62974f24d70fc2b3e30d6aae8b76ef000dac1/tests/SPE1CASE1.DATA) at commit `0ea62974f24d70fc2b3e30d6aae8b76ef000dac1`.
That commit is the `release/2026.04/final` tag.
The source header assigns the deck to ODbL 1.0 and the individual contents to DbCL 1.0.
The header also states copyright 2015 Statoil.

The derived input is `input/SPE1CASE1.DATA`.
Its `WELLDIMS` record changes from `2 1 1 2 /` to `4 1 1 4 /`.
The change allows the four wells that the upstream schedule already declares.
Two nearby comments describe the new limits.
All other model data stays unchanged.

The [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/) applies to both input files.
The [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/) applies to their contents.
These terms also apply when the files appear in a repository with a different software license.
Retain the source notices and these license links with distributed copies.
Public results must carry the required source and ODbL notice.

OPM Flow uses [GPL version 3 or later](https://github.com/OPM/opm-simulators/blob/release/2026.04/final/README.md).
The container contains other packages with their own terms.
This repository does not distribute the container image.

## Run evidence

The `evidence/` directory records Docker and Flow versions, the run log, and the exit status.
The `evidence/rejected/` directory preserves the original input failure.
That failure reports four scheduled wells against the declared limit of two.
The derived input completes all 120 report steps and reaches 3,650 days.

Generated results stay in the ignored `output/` directory.
The completed run provides grid, initial state, restart, and summary files.
The development page describes the warnings and the remaining ResInsight acceptance work.
