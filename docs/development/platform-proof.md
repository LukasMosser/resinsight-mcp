# Platform proof

P01's bounded platform evidence passes on the selected macOS 14.2.1 arm64 host.
The custom ResInsight build, imported-well controls, OPM run, and native image experiment all have successful records.
The [P01 issue](https://github.com/LukasMosser/resinsight-mcp/issues/2) and [PR](https://github.com/LukasMosser/resinsight-mcp/pull/22) record delivery and review.
These experiments do not add an application adapter or establish support for other hosts.

## Evidence

Each record distinguishes source findings from observed runtime behavior.
The experiments stay outside the application package.
Their combined results do not establish a complete engineering workflow.

| Gate | Result | Evidence |
| --- | --- | --- |
| ResInsight with gRPC | Custom ResInsight 2026.09.0 builds and runs with the matching rips package. | [Build and runtime record](platform-resinsight.md#recorded-runtime-result). |
| Owned launch and explicit attachment | The probe launches its own process, attaches through its assigned port, and closes only that process. | [Recorded controls](platform-resinsight.md#recorded-runtime-result). |
| Case, view, and image export | SPE1 loads 300 active cells. PRESSURE and SGAS changes produce three reviewed PNGs. | [Case and image evidence](platform-resinsight.md#recorded-runtime-result). |
| Well edit and completion export | The imported FIELD well passes the bounded perforation edit and three-cell COMPDAT comparison. | [Well evidence and limits](platform-resinsight.md#recorded-runtime-result). |
| OPM execution | Flow 2026.04 completes 120 report steps through 3,650 days. | [OPM run and provenance](platform-opm.md). |
| Native MCP image | An isolated Codex CLI model identifies a hidden random marker from one native image. | [Image experiment](platform-images.md). |
| Component inventory | The record identifies installed packages, fetched source, runtime libraries, and build tools. | [Component evidence](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/components.md). |
| Native OPM Jobs API | Inspected source has internal controls without matching Python job bindings. | [Capability table](platform-resinsight.md#native-opm-jobs). |

## Selected build

The host runs macOS 14.2.1 with Xcode 15.1 and Apple Clang 15.
The official arm64 ResInsight bundle declares macOS 15.0 as its minimum and disables gRPC in its build workflow.
The installed Apple compiler and library fail the required `std::format` probe.

The owner selected an isolated LLVM 19.1.7 compiler and custom ResInsight build on this Mac.
The selected configuration uses Qt 6.7.0, Apple's system C++ runtime, and LLVM headers with Apple availability checks.
All 3,503 application build steps completed successfully in 48 minutes and 26 seconds.
The selected upstream tests passed 66 tests across ten suites, with no failures or skips.
These are bounded checks, not the full upstream suite.

## Acceptance boundaries

The [implementation plan](implementation-plan.md#p01-prove-the-macos-path) defines the acceptance scope.
The successful imported-well route satisfies the bounded well-edit experiment.
A separate modeled-well run returned empty trajectory arrays and stopped before completion export.
That failure remains visible and does not establish a runtime FIELD-unit error.

The completion proof compares actual exported COMPDAT records with the application API's three expected connections.
The exporter also emitted an MSW file, but the experiment does not validate its full multisegment-well contents.
No edited completion deck was simulated as part of this ResInsight control run.

The image experiment proves native delivery through the isolated Codex CLI.
It does not prove that delivery through the existing Codex desktop task.
ResInsight snapshots were reviewed separately from that marker experiment.
The custom application ran from its build directory with explicit Qt plugin configuration.
No installer, portable bundle, or wider macOS support claim follows from this host result.
