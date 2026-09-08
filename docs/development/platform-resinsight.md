# ResInsight on macOS

The custom ResInsight 2026.09.0 build and imported-well Python controls pass on the selected macOS 14.2.1 arm64 host.
The official arm64 release does not satisfy the Python control gate.
The successful experiment uses the approved isolated LLVM configuration and Qt 6.7.0.
The [P01 PR](https://github.com/LukasMosser/resinsight-mcp/pull/22) records delivery and review.

## Recorded runtime result

The application completed all 3,503 build steps in 48 minutes and 26 seconds on September 8, 2026.
The [build result](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/application-build-01-result.json) records exit status 0.
The selected upstream tests passed 66 tests across ten suites, with no failures or skips.
The [test XML](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/application-unit-tests.xml) and [command](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/application-unit-tests-command.json) define that bounded coverage.
They do not represent the full upstream test suite.

The successful [imported-03 event log](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/controls-imported-03/events.jsonl) records the following controls.
The application reported API version `2026.9.0`, and the installed rips 2026.9.0.1 package reported client version `2026.09.0`.

| Control | Observed result |
| --- | --- |
| Launch and attach | Owned process 53194, explicit localhost port 59372, GUI confirmed. |
| Case load | SPE1 has 10 × 10 × 3 cells, all 300 active, with the inspected FIELD geometry. |
| Results and view | PRESSURE at step 0, then SGAS at step 120, with vertical scale 20. |
| Images | Three fresh 1280 × 900 PNGs decoded successfully and received visual review. |
| Bounded edit | The P01IMPORT perforation endpoint changed from 8,374 to 8,424 feet, with start depth 8,326 feet. |
| Trajectory | 170 samples follow x=y=4,500 feet, with measured depth equal to vertical depth from 0 through 8,430 feet. |
| Completions | Three positive COMPDAT connections cover I=5, J=5, K=1 through 3. Exported records match API data. |
| Cleanup | Only the owned process received SIGTERM and closed, recorded as return code -15. |

The reviewed snapshots show [initial pressure](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/controls-imported-03/pressure_initial/pressure_initialSPE1CASE1_3D_View_PRESSURE_00_01_Jan_2015.png), [final gas saturation](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/controls-imported-03/gas_final/gas_finalSPE1CASE1_3D_View_SGAS_120_29_Dec_2024.png), and the [imported well](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/controls-imported-03/imported_well/imported_wellSPE1CASE1_3D_View_SGAS_120_29_Dec_2024.png).
The [control record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/controls.md) explains depth conventions, fixture corrections, and export checks.
The [runtime review](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/runtime-review.json) preserves independent findings and confirms that no listed probe process remained.
The images show result labels and the imported marker, while data checks establish subsurface completion geometry.
The exporter also wrote `P01IMPORT_MSW.inc`, but full multisegment-well contents were not validated.

Two earlier imported runs failed because `name P01IMPORT` became `me P01IMPORT` on this host.
The successful run used the importer's documented `wellname: P01IMPORT` header in the same imported route.
A separate [modeled-01 record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/controls-modeled-01/events.jsonl) shows an empty-trajectory failure before completion export.
The modeled FIELD-unit concern remains a source finding, not an observed export error.

The [linkage record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/evidence/application-linkage.json) identifies Apple's C++ runtime and OpenGL, Qt 6.7.0, and resdata.
The application ran from its build directory with explicit locale and Qt plugin settings.
No installer or portable bundle was required for this experiment.
This result does not establish other macOS hosts, all modeled-well operations, or an application adapter.

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
Its recorded build and imported-well controls now pass within the scope above.
The experiment does not establish a portable distribution or broader host support.

The [official LLVM 19.1.7 release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-19.1.7) provides an ARM64 archive of about 1.41 GB compressed.
The selected compiler and runtime files occupy about 451 MiB after extraction.
The compiler and bundled runtime metadata declare macOS 14.0 as their minimum.

The separate bundled C++ runtime crashes during its initialization on this host.
The selected configuration instead uses Apple's system C++ runtime, which the prebuilt Qt also uses.
A separate copy of LLVM's headers enables its Apple version availability checks.
This uses the global configuration behind `LIBCXX_ENABLE_VENDOR_AVAILABILITY_ANNOTATIONS`, without overriding individual feature checks.

LLVM 19.1.7 and its LLD linker compile and run the C++23 probe with this configuration.
A Qt 6.7.0 probe also passes its event loop, string exchange, and expected-value exception checks.
The successful application build retains this compiler, header, and runtime configuration.
The dependency plan remains pinned to the release registry baseline.
The [custom build record](https://github.com/LukasMosser/resinsight-mcp/blob/main/experiments/platform/resinsight/custom-build.md) contains the configuration, commands, and prerequisite evidence.

## Python controls found in source

The following calls exist in the tagged source.
The runtime record above identifies which operations passed in this experiment.
The probe uses explicit ports and paths.

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
This side effect remains part of the connection contract.

The [well target implementation](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationLibCode/ProjectDataModelCommands/RimcWellPathGeometryDef.cpp) changes the Z sign.
The imported runtime proof connects the intended depth, trajectory, and active cells.
Its exported well name matches the imported P01IMPORT well.

The generic modeled-well route defaults to metric units and exposes no scripted unit setter in the inspected source.
The supported file-import route assigns units from the first loaded case when the trajectory intersects its bounds.
The probe selects each route explicitly and never changes routes after a failure.
The imported FIELD route passed the bounded perforation edit and completion export checks.
The separate modeled route stopped at empty trajectory data before reaching export.
That run does not confirm the source unit concern as a runtime failure.

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
