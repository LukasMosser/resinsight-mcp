# ResInsight on macOS

The owner approved an isolated custom build on the selected host.
The official arm64 release does not satisfy the Python control gate.
The installed Apple compiler fails the C++ probe, but the isolated LLVM configuration now passes it.
The full application build and Python control remain unproved.

## Host and release

The host is an Apple M1 Pro MacBook Pro with eight CPU cores and 16 GiB of memory.
It runs macOS 14.2.1 with Xcode 15.1 and SDK 14.2.
The experiment began with about 27 GiB of free disk space.

The inspected release is [ResInsight v2026.09.0](https://github.com/OPM/ResInsight/releases/tag/v2026.09.0).
Its arm64 app bundle declares `LSMinimumSystemVersion=15.0`.
Its generic bundle version fields contain `1.0` and `1.0.0`, so the release record uses the download tag.

The [release workflow](https://github.com/OPM/ResInsight/blob/v2026.09.0/.github/workflows/ResInsightMac.yml) disables gRPC and HDF5.
gRPC is the interface that rips uses for Python control.
The workflow targets macOS 15.0 for arm64 and macOS 13.3 for Intel.

The downloaded executable did not finish a `--help` invocation within 20 seconds.
The experiment stopped that owned process at the timeout.
That result does not establish whether the application can display a GUI on this host.

## Compiler evidence

The [release source](https://github.com/OPM/ResInsight/blob/v2026.09.0/CMakeLists.txt) requests C++23.
It uses `std::expected` and `std::format` in application code.
The probe tests those features with the installed compiler and C++ library.

Apple Clang 15.0.0 rejects the flag `-std=c++23` and names `-std=c++2b` as its draft C++23 flag.
With that supported flag, the probe fails with this error:

```text
error: no member named 'format' in namespace 'std'
```

The probe therefore does not justify starting the full build with this compiler.
A newer compiler and C++ library need their own compatibility proof on this host.
The [experiment directory](https://github.com/LukasMosser/resinsight-mcp/tree/main/experiments/platform/resinsight) contains the source and compiler record.

## Approved build path

The source-aligned path retains release `v2026.09.0` and its pinned submodules.
It uses Qt 6.7.0, Python 3.12, and the existing vcpkg dependency system.
vcpkg builds the application's C++ dependencies.

The [dependency manifest](https://github.com/OPM/ResInsight/blob/v2026.09.0/vcpkg.json) excludes grpc on macOS.
A custom build must include that dependency and enable `RESINSIGHT_ENABLE_GRPC`.
Changing only the CMake option does not supply the missing dependency.

The vcpkg submodule revision is `df31882c439c38fc7c8b89d861457e8b8bf6fe67`.
The registry baseline is `84bab45d415d22042bd0b9081aea57f362da3f35`.
The existing arm64 triplet uses static libraries and obtains the SDK through `xcrun`.

The owner selected the isolated build on this Mac.
This record does not establish the full build's disk use or application compatibility.
Dependent integration work remains gated until a build proves Python control.

The [official LLVM 19.1.7 release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-19.1.7) provides an ARM64 archive of about 1.41 GB compressed.
The selected compiler and runtime files occupy about 451 MiB after extraction.
The compiler and bundled runtime metadata declare macOS 14.0 as their minimum.

The separate bundled C++ runtime crashes during its initialization on this host.
The selected configuration instead uses Apple's system C++ runtime, which the prebuilt Qt also uses.
A separate copy of LLVM's headers enables its Apple version availability checks.
This uses the global configuration behind `LIBCXX_ENABLE_VENDOR_AVAILABILITY_ANNOTATIONS`, without overriding individual feature checks.

LLVM 19.1.7 and its LLD linker compile and run the C++23 probe with this configuration.
A Qt 6.7.0 probe also passes its event loop, string exchange, and expected-value exception checks.
The application and all C++ dependencies must retain this compiler, header, and runtime configuration.
The dependency plan remains pinned to the release registry baseline.
The [custom build record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/custom-build.md) contains the configuration, commands, and prerequisite evidence.

## Python controls found in source

The following calls exist in the tagged source.
Their presence does not prove runtime behavior on this host.
The experiment must use explicit ports and paths when it exercises these calls.

| Operation | Tagged Python interface |
| --- | --- |
| Attach | `rips.Instance(port=..., launched=False)` connects to localhost. |
| Launch | `Instance.launch(resinsight_executable=..., launch_port=0, console=False)` starts an owned process. |
| Load a case | `instance.project.load_case(path=...)` returns the case. |
| Select a result | `view.apply_cell_result(result_type, result_variable)` changes the displayed property. |
| Select time | `view.set_time_step(time_step)` selects the report step. |
| Export an image | `view.export_snapshot(...)` writes an image file. |
| Create a well | `project.well_path_collection().add_new_object(rips.ModeledWellPath)` creates a modeled path. |
| Import a well | `project.import_well_paths(well_path_files=[...])` imports an ASCII trajectory. |
| Add a target | `geometry.append_well_target(...)` adds a path target. |
| Add a perforation | `well_path.append_perforation_interval(...)` adds a measured-depth interval. |
| Export completions | `case.export_well_path_completions(...)` writes well connections. |

The [connection code](https://github.com/OPM/ResInsight/blob/v2026.09.0/GrpcInterface/Python/rips/instance.py) compares application and package major and minor versions.
Attachment also changes the application's start directory to the Python process directory.
The experiment must record that side effect when it tests attachment.

The [well target implementation](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationLibCode/ProjectDataModelCommands/RimcWellPathGeometryDef.cpp) changes the Z sign.
The runtime proof must therefore connect the intended depth, trajectory, and active cells.
The export must use the name of the well that the experiment actually creates.

The generic modeled-well route defaults to metric units and exposes no scripted unit setter in the inspected source.
The supported file-import route assigns units from the first loaded case when the trajectory intersects its bounds.
The probe selects each route explicitly and never changes routes after a failure.
The imported FIELD route will test the bounded perforation edit and completion export.
The separate modeled route can record the unit limitation at runtime.

## Native OPM Jobs

The release contains internal C++ controls for OPM Jobs.
The inspected gRPC and scriptable command sources contain no matching Python job controls.
These source findings support a dedicated process adapter as the current proposed design.

| Operation | Internal C++ entry point | Python coverage found |
| --- | --- | --- |
| Create | `RimOpmFlowJob` and its input setters | No matching binding in the inspected paths. |
| Start | `RicRunJobFeature::runJob`, `RimGenericJob::execute` | No matching binding in the inspected paths. |
| Progress | `RimGenericJob::state`, `percentageDone` | No matching binding in the inspected paths. |
| Cancel | `RicStopJobFeature::stopJob`, `RimGenericJob::stop` | No matching binding in the inspected paths. |
| Logs | `RimGenericJob::jobLog` | No matching binding in the inspected paths. |
| Load results | `RimOpmFlowJob::onCompleted` | No matching binding in the inspected paths. |

The [job states](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationLibCode/ProjectDataModel/Jobs/RimGenericJob.h) contain no separate canceled state.
The [job implementation](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationLibCode/ProjectDataModel/Jobs/RimGenericJob.cpp) reports 100 percent when a job finishes, including failure.
The service cannot equate percent complete with successful simulation.

The [OPM job implementation](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationLibCode/ProjectDataModel/Jobs/RimOpmFlowJob.cpp) loads results after success and the presence of an EGRID file.
This review does not prove the native job lifecycle at runtime.
The separate [OPM experiment](platform-opm.md) records the container run.
