# Preserved Flow result fixture

These five files come from the successful P08 `p07-1` trial on September 9, 2026.
The tested commit was `f289e8eee5ea500f1a1f32535c6a262b35abaf16`.
The original command and numerical records remain under `docs/development/evidence/p08/`.
This directory is the canonical maintained result fixture for parser and publication tests.
Tests read and change semantic arrays through the official OPM Python interfaces.
Tests do not compare file bytes.

The source is the [preserved SPE1 input fixture](../../../../models/imports/data/spe1/SPE1.DATA).
The runtime was `flow 2026.04` on Linux arm64 through Docker Desktop.
The image was `openporousmedia/opmreleases@sha256:810b1a2b72ee24a194df033781e82d57ad3a262167054953c0c3e37d9c0cbbc1`.
The run used two CPUs, 2 GiB of memory, disabled networking, and a 60-second wall limit.
It completed two simulated days with 300 active cells.
The reader was `opm==2025.10` with NumPy 2.5.3.
The included log records the actual program banner and warnings.

## Data notices

Copyright (C) 2015 Statoil applies to the source data.
The source database uses the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Individual contents use the [Database Contents License 1.0](https://opendatacommons.org/licenses/dbcl/1-0/).
These notices remain separate from the repository software license.
The source input retains its original notices.
