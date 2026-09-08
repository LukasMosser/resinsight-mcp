# Output inventory

This inventory records the preserved output of the successful September 8, 2026 run.
All files below exist directly under `experiments/platform/opm/output/`.
The roles describe the intended result content, not independent numerical acceptance.
The original files remain unchanged and outside Git.

| File | Intended role |
| --- | --- |
| `SPE1CASE1.EGRID` | Grid geometry and active-cell mapping. |
| `SPE1CASE1.INIT` | Initial grid properties. |
| `SPE1CASE1.UNRST` | State results across restart report steps. |
| `SPE1CASE1.SMSPEC` | Names, units, and identities of summary vectors. |
| `SPE1CASE1.UNSMRY` | Summary time-series values. |
| `SPE1CASE1.ESMRY` | Extended summary output for summary readers. |
| `SPE1CASE1.RSM` | Human-readable summary tables. |
| `SPE1CASE1.PRT` | Simulator print report. |
| `SPE1CASE1.DBG` | Simulator debug log. |

## Dated report evidence

The [summary excerpt](final-summary-excerpt.txt) retains headings, units, well names, and dated rows from the original `RSM` file.
Its final date is December 29, 2024.
On that date, `BGSAT` for block 1 is `0.549651`.
`BGSAT` is the gas saturation of a grid block.

The same date reports `WOPR` for `PROD` as `5558.104 STB/DAY`.
`WOPR` is the oil production rate of a well.
`STB/DAY` means stock-tank barrels per day.
These are quoted simulator results, not independently validated numerical values.

The excerpt also preserves the previous date and the report's cumulative-volume scale factors.
No value was converted, rounded, or compared with another simulator.
The excerpt includes the upstream source and database license notices.
