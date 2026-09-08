# Custom macOS build

The owner approved this isolated build on the macOS 14.2.1 arm64 host.
The compiler and Qt probes pass, and all 103 native dependency packages are installed.
The application build completed all 3,503 steps in 48 minutes and 26 seconds with exit status 0.
The selected upstream tests and imported-well Python controls also pass.
These results apply to this host and configuration.

## Inputs

The build root is `/private/tmp/resinsight-p01-build`.
The repository remains at `/Users/lmoss/Documents/ChatGPT/resinsight-mcp`.
The checked-in CMake files describe these specific experiment paths.
They are not a general application installer.

The source uses ResInsight `v2026.09.0` and every pinned submodule.
The [checkout record](evidence/source-checkout.json) lists their exact revisions.
The custom source patch [enables grpc in the macOS manifest](patches/enable-macos-grpc.patch).
The CMake invocation also enables `RESINSIGHT_ENABLE_GRPC`.
The tagged configuration also applies its existing OpenZGY patch to disable OpenMP on macOS.
That upstream step modifies eight files inside the pinned OpenZGY source.

The isolated prerequisites have separate records:

- [Qt 6.7.0](qt-prerequisites.md) supplies the GUI components.
- [LLVM 19.1.7](llvm-prerequisites.md) supplies the compiler and linker.
- [CMake, Ninja, and Bison](build-tools.md) supply build tools.
- The repository lockfile supplies Python 3.12 packages, rips, and gRPC code generation.

## Runtime configuration

The [chainload file](build/llvm19.cmake) selects LLVM 19.1.7 and its LLD linker.
It selects a separate LLVM header copy with Apple availability checks enabled.
The application and dependencies link Apple's system C++ runtime.
The prebuilt Qt libraries use that same runtime.
The configuration adds no private C++ runtime search path.

The [triplet](build/triplets/arm64-osx-p01.cmake) selects arm64, static dependencies, release builds, and a macOS 14.2 deployment target.
A triplet defines a dependency build's platform settings.
The same triplet applies to target libraries and host tools such as protoc.
It retains the release's SDK discovery and CMake policy settings.
The vcpkg cache inputs include the copied header configuration.

The [C++23 record](evidence/llvm-apple-availability-probe.json) establishes the required expected-value and formatting operations.
The [Qt record](evidence/llvm-qt-runtime-probe.json) establishes event-loop execution, string exchange, and exception handling.
Both programs link `/usr/lib/libc++.1.dylib` and return status 0.
These small programs do not establish complete application compatibility.

## Dependency plan

The [bootstrap log](evidence/vcpkg-bootstrap.log) records the pinned vcpkg tool startup.
The [dry-run log](evidence/vcpkg-dry-run.log) records the resolved dependency plan before compilation.
The plan uses the release registry baseline and contains 103 packages.
It includes gRPC 1.71.0, Protobuf 5.29.5, Arrow 21.0.0, and Boost 1.89.0.
It retains the release's fmt 10.1.1 override.

The first build completed 97 packages before gRPC configuration failed.
The port's Linux static-link patch replaced `CMAKE_EXE_LINKER_FLAGS` with `-Bstatic` on macOS.
That replacement removed the selected LLD linker and caused Apple's linker to load the incompatible private runtime.
The [configuration log](evidence/grpc-configure-01.log) and [failed thread check](evidence/grpc-linker-failure.json) preserve the result.

The triplet now sets `gRPC_STATIC_LINKING=OFF` for the gRPC port only.
The port helper appends this explicit setting after the port's default options.
The normal `BUILD_SHARED_LIBS=OFF` setting still builds static gRPC libraries.
No port source copy or dependency version change is required.
The revised standalone dry run lists only the six remaining packages for compilation.
The actual CMake integration detects changed build settings and rebuilds the completed packages too.
The standalone dry run therefore did not predict the rebuild cost of this configuration change.

The [second configuration log](evidence/application-configure-02.log) records all 103 successful package installations and successful application configuration.
The [gRPC configuration log](evidence/grpc-configure-02.log) records the corrected linker option and successful thread checks.
The [installed package list](evidence/vcpkg-installed.json) contains the actual package versions and features.

The pinned vcpkg tool requires CMake 4.4.0 for its dependency work.
It downloaded that version into the isolated download tree during the dry run.
The outer application configuration uses the separately installed CMake 3.31.6.
These are distinct tool uses in the recorded build.

## Configure and build

The [configuration record](evidence/application-configure-command.json) contains the exact command and its explicit environment settings.
Its paths select the prepared prerequisites above.
The following command repeats that configuration on the same prepared host:

```sh
uv run --locked python - <<'PY'
import json
import os
import subprocess
from pathlib import Path

record = json.loads(
    Path("experiments/platform/resinsight/evidence/application-configure-command.json").read_text()
)
environment = os.environ.copy()
environment.update(record["environment"])
environment["PATH"] = ":".join(record["path_prefix"] + [environment["PATH"]])
subprocess.run(record["command"], env=environment, check=True)
PY
```

The dependency compilation uses at most two parallel jobs.
Successful package builds remove their build directories and temporary installation copies.
The build retains downloaded archives and top-level package logs.
It disables shared binary caches and keeps the registry cache under the experiment root.

The configuration enables application unit tests and disables HDF5, unity builds, and precompiled headers.
It uses the locked Python environment to generate Python bindings.
It disables upstream Python package installation because the lockfile already supplies those packages.
No global Python packages are installed by this configuration.

The second configuration selected an existing Homebrew OpenGL library and produced Qt link-path warnings.
The final command explicitly selects Apple's SDK OpenGL framework and headers through the supported CMake cache variables.
It also sets `Python_EXECUTABLE` to the locked environment for vcpkg's application helper.
The separate `RESINSIGHT_GRPC_PYTHON_EXECUTABLE` setting controls Python binding generation.

The [third configuration log](evidence/application-configure-03.log) records success without rebuilding the installed dependencies.
Its [result record](evidence/application-configure-03-result.json) records status 0.
The [selected cache values](evidence/application-configuration.json) retain LLVM, LLD, Apple OpenGL, and the locked Python interpreter.
The regenerated application link inputs contain no Homebrew or Anaconda library path.
The upstream configuration retains deprecation and policy warnings, which remain in the logs.

After successful configuration, the application build command is:

```sh
/private/tmp/resinsight-p01-build/build-tools/bin/cmake \
  --build /private/tmp/resinsight-p01-build/application-build --parallel 2
```

The first [configuration log](evidence/application-configure-01.log) records the completed packages and gRPC failure.
The [build command record](evidence/application-build-01-command.json) records the application build.
The [completed log](evidence/application-build-01.log) ends after all 3,503 steps.
The [result](evidence/application-build-01-result.json) records exit status 0 from 11:16:50 through 12:05:16 UTC on September 8, 2026.
That application build took 48 minutes and 26 seconds, excluding prerequisite installation and earlier dependency work.
Warnings remain in the complete log.

## Application checks

The selected [upstream test command](evidence/application-unit-tests-command.json) exercises bounded grid, well geometry, and completion-related tests.
Its [XML result](evidence/application-unit-tests.xml) records 66 tests across ten suites, with zero failures, errors, or skips.
The [process result](evidence/application-unit-tests-result.json) records exit status 0.
This is a selected test run, not the full upstream suite.
A preliminary source count included two commented tests and overstated the executable count as 68.
The runtime XML provides the authoritative count.

The [linkage record](evidence/application-linkage.json) identifies an arm64 application with a macOS 14.2 deployment minimum.
It records Apple's `/usr/lib/libc++.1.dylib` and system OpenGL framework.
Qt framework dependencies report version 6.7.0 and resolve through the recorded `LC_RPATH` entries.
The application also links the built resdata library, whose metadata reports version 2.4.0.
The generic bundle version fields remain `1.0` and `1.0.0`, so runtime API and source records identify the application version.

The [imported-03 command](evidence/controls-imported-03/command.json) runs the application directly from the build directory.
Its explicit environment settings are `LC_ALL=en_US.UTF-8` and the selected Qt installation's `QT_PLUGIN_PATH`.
The existing runtime search paths locate Qt and resdata.
The experiment did not need installer creation or `macdeployqt` packaging to run on this prepared host.
It does not establish a portable application bundle.

The [control record](controls.md) documents successful owned launch, explicit-port attachment, case loading, result changes, snapshots, and a bounded imported-well edit.
The application reports API version `2026.9.0`, with client version `2026.09.0` from rips 2026.9.0.1.
The completion proof compares three exported COMPDAT records with API data.
The additional MSW export is preserved without claiming full multisegment-well acceptance.

Two failed imported attempts preserve a header parsing issue corrected with the documented `wellname:` form.
The separate modeled route returned empty trajectory arrays and stopped before completion export.
Its source unit concern remains separate from that observed failure.
The [component inventory](components.md) records installed dependencies, fetched source, build tools, and license evidence.
The [P01 PR](https://github.com/LukasMosser/resinsight-mcp/pull/22) records delivery and review.
