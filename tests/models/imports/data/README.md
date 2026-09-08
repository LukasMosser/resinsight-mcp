# P07 input data

The `spe1` directory contains a derived SPE1 input from OPM.
The source is [OPM/opm-common](https://github.com/OPM/opm-common/blob/0ea62974f24d70fc2b3e30d6aae8b76ef000dac1/tests/SPE1CASE1.DATA).
Its commit is `0ea62974f24d70fc2b3e30d6aae8b76ef000dac1`.
The repository preserves the original under `experiments/platform/opm/input/upstream/`.

The source header states copyright 2015 Statoil.
The [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/) applies to the source and derived input.
The [Database Contents License 1.0](https://opendatacommons.org/licenses/dbcl/1-0/) applies to their contents.
These terms apply separately from the repository software license.
Public results must retain the source attribution and applicable ODbL notice.

## Recorded changes

P01 raises the well limits to `4 1 1 4 /`.
P07 starts from that corrected deck and keeps its grid, fluid properties, and initial state.
OPM 2025.10 keyword serialization writes these sections into include files.
The original comments and layout remain available in the upstream and P01 copies.
P07 removes `ECHO` and `NOECHO` because Flow reports them as unsupported.

P07 replaces the reporting and schedule sections with a bounded two-day trial.
The trial retains `PROD` and `INJ`, their original completions, and explicit rate and pressure controls.
It removes the two later RFT wells and their history controls.
The summary requests field oil rate and both well pressures.
`RPTRST BASIC=1` requests each report state, and `DRSDT 0` retains the P01 dissolved-gas setting.

These changes define the input fixture before import.
The import service preserves every fixture source file and records an empty change list.
The service never rewrites a supplied deck.
