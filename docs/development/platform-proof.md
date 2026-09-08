# Platform proof

P01 records the first platform experiment on the selected Mac.
The OPM run and native image experiment pass within their stated limits.
ResInsight Python control remains unproved, so P01 stays open.

## Evidence

Each record distinguishes upstream source claims from observed runtime behavior.
The experiments stay outside the application package.
They do not establish a complete engineering workflow.

| Gate | Result | Evidence |
| --- | --- | --- |
| ResInsight with gRPC | A newer compiler and a custom build need an owner decision. | [ResInsight source and host probes](platform-resinsight.md). |
| OPM execution | Flow 2026.04 completes 120 report steps through 3,650 days. | [OPM run, versions, warnings, and input provenance](platform-opm.md). |
| Native MCP image | An isolated Codex CLI model identifies a hidden random marker from one native image. | [Image experiment and observer record](platform-images.md). |
| Case, view, and image export | Await the ResInsight build. | [Required controls](platform-resinsight.md#python-controls-found-in-source). |
| Well edit and completion export | Await the ResInsight build. | [Required controls](platform-resinsight.md#python-controls-found-in-source). |
| Native OPM Jobs API | Tagged source has internal controls but no matching Python bindings in the inspected paths. | [Capability table](platform-resinsight.md#native-opm-jobs). |

## Open build choice

The host runs macOS 14.2.1 with Xcode 15.1 and Apple Clang 15.
The official arm64 ResInsight bundle declares macOS 15.0 as its minimum and disables gRPC in its build workflow.
The installed compiler and library also fail the required `std::format` probe.

The owner can select an isolated newer compiler on this Mac or a newer macOS host.
The local path needs a compiler and library probe before the full dependency build.
Neither path establishes Python control until an actual application passes the required calls.

## Remaining acceptance

The [P01 issue](https://github.com/LukasMosser/resinsight-mcp/issues/2) remains the work record.
The [implementation plan](implementation-plan.md#p01-prove-the-macos-path) defines its full acceptance criteria.
The lead must complete these steps before closing it:

- Prove a ResInsight build with gRPC and a matching rips package.
- Attach by explicit port and launch an owned instance.
- Load the small OPM result, change its view, and export a fresh image.
- Create a bounded well edit and record completion export behavior.
- Complete the component inventory for the actual build.

The image experiment proves the isolated Codex CLI path.
It does not prove the connection in the existing Codex desktop task.
The application observation work must name the client and versions that it actually tests.
