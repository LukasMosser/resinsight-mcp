# P01 component inventory

This record describes the selected ResInsight source and the September 8, 2026 dependency plan.
It separates application dependencies from experiment clients and build tools.
All 103 selected native dependency packages are installed, and the application build and imported-well control probe pass.
This record includes the built executable's library inspection, without a portable distribution or license compatibility conclusion.
SPDX identifiers are standard names for licenses and license expressions.

## Source and inventory authority

The selected ResInsight tag is `v2026.09.0`, commit `197d58a750dd0bc243025b3939ab2a8a01a2c709`.
Its [license notice](https://github.com/OPM/ResInsight/blob/197d58a750dd0bc243025b3939ab2a8a01a2c709/ApplicationLibCode/Adm/LicenseInformation.txt) states `GPL-3.0-or-later` for ResInsight and its visualization core.
The [COPYING file](https://github.com/OPM/ResInsight/blob/197d58a750dd0bc243025b3939ab2a8a01a2c709/COPYING) contains the GPL version 3 text.
Individual component files retain their notices.

The following pinned records define the requested native dependency graph:

- [vcpkg.json](https://github.com/OPM/ResInsight/blob/197d58a750dd0bc243025b3939ab2a8a01a2c709/vcpkg.json) lists direct dependencies and the `fmt` 10.1.1 override.
- [vcpkg-configuration.json](https://github.com/OPM/ResInsight/blob/197d58a750dd0bc243025b3939ab2a8a01a2c709/vcpkg-configuration.json) selects registry baseline `84bab45d415d22042bd0b9081aea57f362da3f35`.
- The [registry at that baseline](https://github.com/microsoft/vcpkg/tree/84bab45d415d22042bd0b9081aea57f362da3f35) records port versions, dependencies, and available license metadata.
- The [source submodule declarations](https://github.com/OPM/ResInsight/blob/197d58a750dd0bc243025b3939ab2a8a01a2c709/.gitmodules) and Git links pin embedded repositories.

The [resolved plan](evidence/vcpkg-dry-run.log) preserves the selected dependency records.
It records each selected version, feature set, triplet, and port Git tree.
The triplet is `arm64-osx-p01`.
Exact port files were read from `/private/tmp/resinsight-p01-build/cache/vcpkg/registries/git-trees/<tree>/vcpkg.json`.
These temporary records supplement the pinned manifests and must remain distinct from installation success evidence.
The [installed package list](evidence/vcpkg-installed.json) records the actual versions, features, and triplet through `vcpkg list --x-json`.
The [application inspection](evidence/application-linkage.json) records the executable and resdata library through `file` and `otool`.

## Native dependencies in the resolved plan

Versions below include the vcpkg port revision after `#`, when present.
License expressions come from the exact selected port metadata unless the row says otherwise.
Boost Test is a test dependency, while gRPC and protobuf also provide code generation tools.
A manifest entry alone does not establish inclusion in the final application binary.

| Component | Selected version | License expression or evidence |
| --- | --- | --- |
| Apache Arrow, CSV, filesystem, JSON, Parquet | 21.0.0#2 | `Apache-2.0` |
| Boost Filesystem, Spirit, Test | 1.89.0 | `BSL-1.0` |
| Clipper2 | 1.5.4 | `BSL-1.0` |
| Eigen | 3.4.1#1 | `MPL-2.0` |
| gRPC, core and codegen | 1.71.0#3 | `Apache-2.0` |
| protobuf, pulled by gRPC | 5.29.5#3 | `BSD-3-Clause` |
| type-lite | 0.2.0 | Installed copyright confirms `BSL-1.0`, despite the missing port license field. |
| fast-float | 8.1.0 | `Apache-2.0 OR BSL-1.0 OR MIT` |
| spdlog | 1.16.0 | `MIT` |
| pugixml | 1.15#1 | `MIT` |
| nanoflann | 1.8.0 | `BSD-3-Clause` |
| fmt, explicit override | 10.1.1 | `MIT` |

The plan also includes the following transitive libraries.
Transitive means required through another dependency.
This compact table groups entries with the same expression without replacing their individual port records.

| Selected components | License metadata |
| --- | --- |
| Abseil 20250814.1, OpenSSL 3.6.0#3, Thrift 0.22.0 | `Apache-2.0` |
| Brotli 1.2.0, RapidJSON 2025-02-26, utf8-range 5.29.5, utf8proc 2.11.2 | `MIT` |
| gflags 2.3.0, libevent 2.1.12+20230128#1, RE2 2025-11-05, xsimd 14.0.0 | `BSD-3-Clause` |
| LZ4 1.10.0 | `BSD-2-Clause` |
| c-ares 1.34.6 | `MIT-CMU` |
| bzip2 1.0.8#6 | `bzip2-1.0.6` |
| zlib 1.3.1 | `Zlib` |
| Zstandard 1.5.7 | `BSD-3-Clause OR GPL-2.0-only` |
| Snappy 1.2.2#1 | Installed copyright records BSD three-clause library terms and separate benchmark-data notices. |
| libiconv 1.18#3 | The selected macOS port skips GNU libiconv and installs a wrapper for the system dependency. |
| Remaining Boost ports, 1.89.0 | See the resolved plan and each selected port. |

The libiconv package version names a dependency port, not a GNU library built for this Mac.
The selected port reports `Not building GNU libiconv` and marks the package empty.
Its macOS path leaves the host SDK implementation under the host's existing terms.

## Embedded source

The following revisions were read through `git submodule status` in the selected source.
Paths in this table are relative to its `ThirdParty` directory.
Names without separate release versions use their immutable Git revision.
These are source components, not proof that every optional component will be linked.

| Component and path | Revision | Inspected license evidence |
| --- | --- | --- |
| `custom-opm-common/opm-common` | `015a8107623afb4ea6ec35cff0d3d334fdb4c637` | `LICENSE` and parser source: `GPL-3.0-or-later` |
| `custom-opm-flowdiag-app/opm-flowdiagnostics-applications` | `2f23dbc47af540fb3588bd7ec1ddea4a19af9a0f` | `LICENSE` and application notice: `GPL-3.0-or-later` |
| `custom-surfio/surfio` | `14e3fc39f4531c9183d50d0e9039f420c10510e4` | `COPYING`: `MIT` |
| `openzgy` | `1f7931b8d42cd0a1b321bd7ad12af9bf038a249b` | `LICENSE`: `Apache-2.0`. Embedded `open-zgy` also has license files. |
| `qtadvanceddocking` | `8b97dd179bb0ed280580c10dd3b95924f71b450e` | `LICENSE` and `DockManager.h`: `LGPL-2.1-or-later` |
| `qwt` | `2e1ab86284626b6fc5c23597cf331cdaf1a2d884` | Qwt License 1.0, based on LGPL 2.1 with stated exceptions. |
| `regression-analysis` | `a78007d8a35d0801f57f5e16e43ab41f59c9d19f` | `LICENSE.txt` and application notice: `GPL-3.0-or-later` |
| `roffcpp` | `5661a1d4ed60743b47c3cf3e3308febc92c01494` | `LICENSE.txt` and application notice: `GPL-3.0-or-later` |
| `tomlplusplus` | `30172438cee64926dc41fdd9c11fb3ba5b2ba9de` | `LICENSE`: `MIT` |

The application notice also covers copied source without separate submodule revisions.
ERT, NR/CRAVA, the visualization core, and copied OPM flow diagnostics state GPL version 3 or later.
NightCharts states LGPL version 2.1 or later.
ExprTk and mio state MIT terms, and Droid Sans states Apache version 2.0 terms.
The copied FreeType license file offers its FreeType License or GPL version 2 terms.
The copied Catch2 2.2.3 test header states Boost Software License 1.0 terms.
GLEW retains its specific permissive notice.
Microsoft icons retain CC BY 4.0 terms, with separate notices for modifications and other icons.
The adapted conrec implementation states GPL version 3 or later in `cafContourLines.cpp` and `cafContourLines.h`.
The separate Qwt adaptation retains Qwt License 1.0 terms.
OpenVDS has an Apache notice, but the current macOS command leaves it disabled through the pinned platform default.
The main source commit pins these copied files and notices.

## Fetched and nested dependencies

These versions were read from the populated source after successful configuration.
The generated build includes these components in their stated roles.

| Component | Populated version or revision | License and role |
| --- | --- | --- |
| GoogleTest | 1.11.0, `e2239ee6043f73722e7aa812a459f54a28552929` | `BSD-3-Clause`. Upstream test libraries. |
| mdspan | 0.6.0, `9ceface91483775a6c74d06ebf717bbb2768452f` | `Apache-2.0 WITH LLVM-exception`. Multidimensional array headers for surfio. |
| cJSON | 1.7.16, downloaded from the pinned release archive | `MIT`. JSON source compiled into the copied OPM component. |
| zfp | 0.5.5, `e8edaced12f139ddf16167987ded15e5da1b98da` | `BSD-3-Clause`. Nested OpenZGY compression library. |

The populated GoogleTest source differs from the later application test declaration, which requests 1.15.2.
The earlier OPM parser test declaration requests 1.11.0.
The populated checkout and its `LICENSE` define the actual version and notice.
The mdspan and cJSON notices reside in `application-build/_deps/<name>-src/LICENSE`.
The zfp notice resides in `source/ThirdParty/openzgy/zfp/LICENSE`.

## Qt runtime and client environment

Qt Base, SVG, and Network Auth are the selected GUI libraries at version 6.7.0.
The installed archive metadata identifies build `6.7.0-0-202403260609` with Intel and arm64 code.
The [Qt prerequisite record](qt-prerequisites.md) preserves archive selection, installed metadata, and pinned license sources.
Qt Base and SVG offer LGPL version 3 and GPL options alongside commercial terms.
Qt Network Auth offers `GPL-3.0-only` or commercial terms, without an LGPL option.
Qt's bundled components and individual files retain separate notices.

| Experiment client | Installed version | Inspected package license metadata |
| --- | --- | --- |
| CPython | 3.12.13 | Installed `lib/python3.12/LICENSE.txt`, including PSF and historical notices. |
| rips | 2026.9.0.1 | `GPL-3.0-or-later`, also stated by the pinned Python source license. |
| grpcio | 1.83.1 | `Apache-2.0` |
| protobuf Python package | 7.36.1 | 3-Clause BSD License, as written in package metadata. |
| Pillow, snapshot decoder | 12.3.0 | `MIT-CMU` |

The Python protobuf version differs from the planned C++ protobuf version.
They are separate package records, not interchangeable version claims.
The repository's [uv.lock](../../../uv.lock) records the full locked Python dependency graph and package artifacts.
Installed package metadata and license files supply the corresponding notices.
This table does not replace notices for every library bundled inside binary wheels.

## Build and installation tools

| Tool | Selected or observed version | License evidence and role |
| --- | --- | --- |
| LLVM Clang, LLD, copied libc++ headers | 19.1.7 | Installed LLVM notice: `Apache-2.0 WITH LLVM-exception`. Compiler, linker, and headers. |
| CMake from Python package | 3.31.6 | Bundled CMake `Copyright.txt`: BSD 3-Clause terms. Python wrapper also ships Apache 2.0 and BSD notices. |
| CMake fetched by vcpkg | 4.4.0 | Dry-run log records the official universal archive. Its bundled notices remain authoritative. |
| Ninja Python package | 1.13.0 | Apache 2.0 notices. Executable reports `1.13.0.git.kitware.jobserver-pipe-1`. |
| Ninja fetched by vcpkg | 1.13.2 | [Tagged Apache 2.0 notice](https://github.com/ninja-build/ninja/blob/v1.13.2/COPYING). Dependency build executable reports `1.13.2`. |
| GNU Bison | 3.8.2 | GPL version 3 or later. Generated parser evidence includes the Bison skeleton exception. |
| grpcio-tools | 1.83.1 | Package metadata: `Apache-2.0`. Python protocol code generation. |
| aqtinstall | 3.3.0 | Package metadata: `MIT`. Downloads selected Qt archives. |
| py7zr | 1.0.0 | Package metadata: `LGPL-2.1-or-later`. Extracts Qt archives. |
| vcpkg source | `df31882c439c38fc7c8b89d861457e8b8bf6fe67` | Selected submodule `LICENSE.txt`: MIT terms. Native dependency installation. |
| vcpkg-boost | 2025-03-29 | Exact port metadata: `MIT`. Build helper. |
| boost-uninstall | 1.89.0 | Exact port metadata: `MIT`. Build helper, distinct from Boost library terms. |
| vcpkg-cmake, vcpkg-cmake-config, vcpkg-cmake-get-vars | 2024-04-23, 2024-05-23, 2025-05-29 | Exact port metadata: `MIT`. Build helpers. |

The [LLVM prerequisite record](llvm-prerequisites.md) describes the selected Apple system runtime and copied-header configuration.
The probe uses Apple's system libc++ and libSystem rather than redistributing private LLVM runtime libraries.
The Apple SDK and system libraries remain host prerequisites with their own terms.
Build-tool licenses do not replace notices for generated code, linked libraries, or bundled assets.

Version evidence resides under `/private/tmp/resinsight-p01-build/build-tools-evidence` and `qt-evidence`.
The Bison `calc.c` evidence contains its generated-code exception.
The selected LLVM package contains `include/llvm/Support/LICENSE.TXT`.
The aqt installer environment's package metadata supplies its installer license records.

## Linked application

The application inspection records an arm64 executable with a macOS 14.2 minimum and SDK 14.2.
The imported-well probe confirms runtime startup and reports ResInsight `2026.9.0` through gRPC.
The bundle's generic version fields remain `1.0` and `1.0.0`, so they do not identify the tested release.

| Dynamic component | Observed link evidence |
| --- | --- |
| Apple C++ runtime | `/usr/lib/libc++.1.dylib`; no private LLVM runtime path. |
| Apple OpenGL | `/System/Library/Frameworks/OpenGL.framework/Versions/A/OpenGL`. |
| Qt 6.7.0 | Core, Gui, Widgets, OpenGL, OpenGLWidgets, Network, NetworkAuth, Concurrent, PrintSupport, Sql, Svg, and Xml frameworks. |
| resdata | `@rpath/libresdata.2.dylib`, current version `2.4.0`, built from the pinned copied ERT source. |
| Other Apple libraries | libSystem, libcups, libresolv, and the system frameworks listed in the inspection. |

The executable's search paths resolve Qt and resdata in the isolated build directories.
The inspected resdata library itself links only Apple's system and C++ runtime libraries.
The GUI probe explicitly selects the installed Qt plugin directory with `QT_PLUGIN_PATH`.
Static dependency and copied-source notices remain covered by the earlier tables and their pinned records.
Dynamic-library inspection does not enumerate every source file inside those archives.

## Boundaries

The [OPM experiment](../opm/README.md) records the simulator image and SPE1 source license separately.
The [native image experiment](../../../docs/development/platform-images.md) records its MCP observation path separately.
No application, Qt archive, compiler package, or dependency binary is committed by this inventory.
A portable distribution would need its own bundled-file inventory and installed notices.
Missing port license fields and incomplete upstream summary entries remain visible findings.
This document records source evidence and does not choose a license route or determine compatibility.
