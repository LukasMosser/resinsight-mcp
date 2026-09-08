# Qt prerequisites

This record prepares Qt 6.7.0 for the custom ResInsight experiment on macOS 14.2.1 arm64.
The installation stays under `/private/tmp/resinsight-p01-build/qt`.
It does not change Homebrew packages or global configuration.
The custom compiler build remains separate acceptance work.

## Upstream requirement

The [ResInsight v2026.09.0 Mac workflow](https://github.com/OPM/ResInsight/blob/v2026.09.0/.github/workflows/ResInsightMac.yml) selects Qt 6.7.0 and the `qtnetworkauth` module.
It uses `CeetronSolutions/install-qt-action@bump-node24`.
The inspected action commit is `819f371327e72652375eb4a34db43c0636cbfa38`.
Its [installer defaults](https://github.com/CeetronSolutions/install-qt-action/blob/819f371327e72652375eb4a34db43c0636cbfa38/action.yml) select aqtinstall 3.3.x and py7zr 1.0.x.

The [application component list](https://github.com/OPM/ResInsight/blob/v2026.09.0/ApplicationExeCode/CMakeLists.txt) requires the following Qt components:

- Core, Gui, OpenGL, and Widgets.
- Network, NetworkAuth, and Xml.
- Concurrent, PrintSupport, Svg, and Sql.

These components come from `qtbase`, `qtsvg`, and `qtnetworkauth`.
Qt Base also contains [macdeployqt](https://github.com/qt/qtbase/tree/v6.7.0/src/tools/macdeployqt), the application deployment tool.
No Qt Tools archive is required for that tool.
The installation excludes Qt Quick, translations, examples, documentation, Qt Creator, and other optional module packages.

## Installer and commands

The isolated installer uses Python 3.12.13, aqtinstall 3.3.0, and py7zr 1.0.0.
Aqtinstall downloads the official Qt archives through the route used by the upstream action.
The commands below do not use Qt account credentials.
The working directory keeps installer logs outside the repository.

```sh
mkdir -p /private/tmp/resinsight-p01-build
cd /private/tmp/resinsight-p01-build
uv venv --python 3.12 /private/tmp/resinsight-p01-build/aqt-venv
uv pip install --python /private/tmp/resinsight-p01-build/aqt-venv/bin/python \
  aqtinstall==3.3.0 py7zr==1.0.0
/private/tmp/resinsight-p01-build/aqt-venv/bin/aqt install-qt \
  mac desktop 6.7.0 clang_64 \
  --outputdir /private/tmp/resinsight-p01-build/qt \
  --modules qtnetworkauth --archives qtbase qtsvg
```

The `clang_64` installer name selects the universal macOS package.
Universal means that the package contains Intel and arm64 code.
The [official package metadata](https://download.qt.io/online/qtsdkrepository/mac_x64/desktop/qt6_670/Updates.xml) identifies version `6.7.0-0-202403260609`.
Qt's download service redirected the archive requests to `mirrors.20i.com`.

## Download size

The archive response metadata gives the sizes below.
The final selection totals 184,350,454 bytes, about 176 MiB compressed.
The installer removes completed download archives after extraction.
The first plan included Qt Tools, but source inspection identified it as unnecessary before its extraction.

| Archive | Compressed bytes |
| --- | ---: |
| `qtbase` | 179,051,094 |
| `qtsvg` | 4,006,491 |
| `qtnetworkauth` | 1,292,869 |

## Installed evidence

Installation completed on September 8, 2026, with exit status 0.
Aqtinstall reported 118.85 seconds for the final installation.
The Qt prefix is `/private/tmp/resinsight-p01-build/qt/6.7.0/macos`.
The required component configuration files exist under that prefix's `lib/cmake` directory.

The command `du -sk` reported 1,021,684 KiB for Qt, about 998 MiB.
It reported 21,448 KiB for the isolated installer, about 21 MiB.
The shared filesystem reported 21 GiB free after installation.
That free-space measurement includes other concurrent build preparation.

The following commands read the installed version and normal build metadata:

```sh
cd /private/tmp/resinsight-p01-build
LC_ALL=en_US.UTF-8 qt/6.7.0/macos/bin/qmake -query
xcrun vtool -show-build qt/6.7.0/macos/lib/QtCore.framework/Versions/A/QtCore
xcrun vtool -show-build qt/6.7.0/macos/lib/QtNetworkAuth.framework/Versions/A/QtNetworkAuth
```

Qmake reported these values:

```text
QT_INSTALL_PREFIX:/private/tmp/resinsight-p01-build/qt/6.7.0/macos
QMAKE_SPEC:macx-clang
QMAKE_XSPEC:macx-clang
QMAKE_VERSION:3.1
QT_VERSION:6.7.0
```

Both inspected libraries reported `x86_64` and `arm64` architectures.
Each architecture reported `minos 11.0` and `sdk 13.1`.
The installed `mkspecs/qconfig.pri` also records the following build settings:

```text
QT_APPLE_CLANG_MAJOR_VERSION = 14
QT_APPLE_CLANG_MINOR_VERSION = 0
QT_APPLE_CLANG_PATCH_VERSION = 0
QT_MAC_SDK_VERSION = 13.1
QMAKE_MACOSX_DEPLOYMENT_TARGET = 11.0
QT_ARCHS = x86_64 arm64
QT_EDITION = OpenSource
```

The metadata describes the prebuilt Qt libraries, not a tested custom ResInsight deployment target.
The `macdeployqt -h` command printed its usage and returned status 1.
That result establishes tool startup only, not successful application deployment.
The custom LLVM compiler, C++ runtime, gRPC, and application launch still need combined build evidence.

Sandboxed Qt tool calls printed an `Incompatible processor` error with a missing `neon` feature.
The same tools started when execution allowed normal host processor detection outside the sandbox.
No processor override or global configuration change was used.
The explicit locale above applies only to its command.

The temporary evidence folder is `/private/tmp/resinsight-p01-build/qt-evidence`.
It contains `install.log`, `qmake-query.txt`, `qtcore-build-metadata.txt`, and `qtnetworkauth-build-metadata.txt`.
This document preserves the version, architecture, deployment, and resource findings from those records.

## Component licenses

Qt Base and Qt SVG provide LGPL version 3 and GPL options, alongside commercial terms.
Their pinned license inventories are [Qt Base](https://github.com/qt/qtbase/tree/v6.7.0/LICENSES) and [Qt SVG](https://github.com/qt/qtsvg/tree/v6.7.0/LICENSES).
Individual files and bundled third-party components retain their own notices.
This record does not replace those license files.

Qt Network Auth uses GPL-3.0-only or Qt commercial terms.
Its [public header](https://github.com/qt/qtnetworkauth/blob/v6.7.0/src/oauth/qoauth2authorizationcodeflow.h) states that choice.
Its [license inventory](https://github.com/qt/qtnetworkauth/tree/v6.7.0/LICENSES) does not offer LGPL.
The component license choice must remain visible in any later distribution record.

The [macdeployqt source](https://github.com/qt/qtbase/blob/v6.7.0/src/tools/macdeployqt/macdeployqt/main.cpp) uses GPL-3.0-only with the Qt GPL exception, or commercial terms.
Aqtinstall has its own [license](https://github.com/miurahr/aqtinstall/blob/v3.3.0/LICENSE).
No Qt binaries are committed to this repository.
