# Custom macOS build

The owner approved this isolated build on the macOS 14.2.1 arm64 host.
The compiler and Qt probes pass.
The full dependency and application build remains in progress.
This record does not yet establish Python control of ResInsight.

## Inputs

The build root is `/private/tmp/resinsight-p01-build`.
The repository remains at `/Users/lmoss/Documents/ChatGPT/resinsight-mcp`.
The checked-in CMake files describe these specific experiment paths.
They are not a general application installer.

The source uses ResInsight `v2026.09.0` and every pinned submodule.
The [checkout record](evidence/source-checkout.json) lists their exact revisions.
The only ResInsight source change is [enabling grpc in the macOS manifest](patches/enable-macos-grpc.patch).
The CMake invocation also enables `RESINSIGHT_ENABLE_GRPC`.

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

After successful configuration, the application build command is:

```sh
/private/tmp/resinsight-p01-build/build-tools/bin/cmake \
  --build /private/tmp/resinsight-p01-build/application-build --parallel 2
```

The first [configuration log](evidence/application-configure-01.log) records the completed packages and gRPC failure.
The active configuration log is `/private/tmp/resinsight-p01-build/logs/application-configure-02.log`.
The experiment must preserve final build logs and actual runtime evidence before P01 can close.
The [control probe](controls.md) defines the next application acceptance work.
