# ResInsight platform experiment

This directory records the ResInsight part of P01 on the selected Mac.
The custom source build and imported-well Python controls pass on this host.
The [development page](../../../docs/development/platform-resinsight.md) separates source findings from runtime evidence.
The [build record](custom-build.md) and [control record](controls.md) preserve the successful commands and bounded acceptance results.

The small compiler probe uses `std::expected` and `std::format`.
ResInsight 2026.09.0 uses these C++ features and requests C++23.
The installed Apple Clang accepts the draft standard flag `-std=c++2b`.

Run the probe from the repository root:

```sh
xcrun clang++ -std=c++2b -mmacosx-version-min=14.2 \
  experiments/platform/resinsight/toolchain_probe.cpp \
  -o /private/tmp/resinsight-toolchain-probe && \
  /private/tmp/resinsight-toolchain-probe
```

If compilation fails, do not run an earlier executable.
The recorded attempt fails because the installed C++ library does not expose `std::format`.
The evidence directory contains the exact command, compiler output, and host record.

The official arm64 app bundle declares macOS 15.0 as its minimum version.
The selected host runs macOS 14.2.1.
The release workflow also disables gRPC, the interface that rips uses for Python control.

The release bundle remains outside this repository.
No ResInsight source or binary is redistributed by this experiment.
Original experiment code uses the repository's GPL-3.0-or-later license.
