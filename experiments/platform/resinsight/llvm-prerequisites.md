# LLVM and the Apple runtime

The bounded C++23 probe now compiles and runs with LLVM 19.1.7 and the Apple system C++ runtime.
It uses copied LLVM headers with Apple's global availability rules enabled.
Availability rules describe which runtime features exist on each operating system version.
This result does not yet establish a working ResInsight build or Qt integration.

## Compiler and runtime boundary

The compiler comes from the [LLVM 19.1.7 release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-19.1.7).
Its local prefix is `/private/tmp/resinsight-p01-build/compiler/LLVM-19.1.7-macOS-ARM64`.
The host is macOS 14.2.1 arm64, and the probe targets macOS 14.2 with the installed Apple SDK.
The selected program links `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`.

Qt 6.7.0 also names `/usr/lib/libc++.1.dylib` in its library dependencies.
Using that same runtime avoids adding the private LLVM libc++, libc++abi, and libunwind libraries to the application.
Libc++ is the C++ standard library.
Libc++abi supplies language support such as exceptions.

The downloaded headers disable vendor availability rules through `_LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS` in `__config_site`.
LLVM's [tagged availability header](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/include/__configuration/availability.h) states that disabled rules assume all library features exist.
That assumption does not fit an older Apple system runtime.
The corrected configuration enables the complete Apple availability mapping.

## Supported configuration control

LLVM exposes `LIBCXX_ENABLE_VENDOR_AVAILABILITY_ANNOTATIONS` as a global CMake option.
The [tagged CMake source](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/CMakeLists.txt) describes this option and generates the corresponding configuration macro.
The [tagged Apple cache](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/cmake/caches/Apple.cmake) enables it.
The experiment uses the behavior represented by `LIBCXX_ENABLE_VENDOR_AVAILABILITY_ANNOTATIONS=ON`.

In LLVM 19.1.7, the Apple mapping marks LLVM 18 and LLVM 19 runtime additions unavailable.
It maps LLVM 17 runtime additions to macOS 14.4 and LLVM 16 additions to macOS 14.0.
The [bad_expected_access header](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/include/__expected/bad_expected_access.h) already provides an inline implementation when its newer runtime key function is unavailable.
A key function provides a shared location for virtual type metadata.

The experiment does not edit that feature implementation or force its individual availability macro.
It retains ABI version 1 and the `__1` namespace from the package configuration.
An ABI is the binary interface between compiled components.
The global setting allows the headers to select their existing older-runtime behavior.

## Actual header preparation

The lead experiment copied the packaged header tree with `shutil.copytree`.
It then replaced one global configuration definition in the copied `__config_site` file.
CMake did not generate or install this copied header prefix.
The recorded patch is [enable-apple-libcxx-availability.patch](patches/enable-apple-libcxx-availability.patch).

The following code records the preparation that ran once:

```python
from pathlib import Path
import shutil

root = Path("/private/tmp/resinsight-p01-build")
original = root / "compiler/LLVM-19.1.7-macOS-ARM64/include/c++/v1"
headers = root / "apple-libcxx/include/c++/v1"
shutil.copytree(original, headers)
config = headers / "__config_site"
old = config.read_text()
new = old.replace(
    "#define _LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS",
    "/* #undef _LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS */",
)
config.write_text(new)
```

The original compiler package and its headers remain unchanged.
The copied prefix is `/private/tmp/resinsight-p01-build/apple-libcxx/include/c++/v1`.
No private runtime library or system binary was patched.
A reproducible source build can instead use the global CMake option and the [install-cxx-headers target](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/include/CMakeLists.txt).

## Probe command and result

The probe uses LLD, the LLVM linker, and the copied headers.
It does not add a private library search directory or private runtime search path.
It does not link a private libc++abi or libunwind.
The recorded command uses these inputs:

```sh
RI_LLVM=/private/tmp/resinsight-p01-build/compiler/LLVM-19.1.7-macOS-ARM64
RI_SDK=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
RI_HEADERS=/private/tmp/resinsight-p01-build/apple-libcxx/include/c++/v1
"$RI_LLVM/bin/clang++" -std=c++23 -isysroot "$RI_SDK" \
  -mmacosx-version-min=14.2 -stdlib=libc++ \
  -nostdinc++ -isystem "$RI_HEADERS" -fuse-ld=lld \
  experiments/platform/resinsight/toolchain_probe.cpp \
  -o /private/tmp/resinsight-p01-build/apple-availability-probe
```

Compilation and execution both returned status 0.
The program printed the following line:

```text
C++23 expected and format: 42
```

The dependency inspection reported the following libraries:

```text
/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 1600.157.0)
/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1336.61.1)
```

The full bounded record is `/private/tmp/resinsight-p01-build/logs/llvm-apple-availability-probe.json`.
The probe establishes its exercised `std::expected` and `std::format` path on this host.
It does not establish every C++23 feature or every dependency's runtime behavior.

## Earlier failures

The initial Apple linker attempt aborted while resolving `__ZdaPv` against the private LLVM libc++ library.
The [LLVM Darwin driver](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/clang/lib/Driver/ToolChains/Darwin.cpp) unconditionally supplies a private `-lto_library` path for Apple `ld`.
It omits that option for LLD because LLD contains the matching LLVM code.
The trace confirms that command choice, but it does not establish the exact loader mechanism behind the private libc++ binding.

LLD avoided the Apple linker abort, but the first private-runtime link lacked exception and allocation symbols.
Explicit private libc++abi and libunwind links allowed compilation.
That program then crashed before printing output.
The lead investigation located the crash in `DoIOSInit::DoIOSInit` and observed system locale state during private-library initialization.

The [tagged Apple libc++ test configuration](https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/libcxx/test/configs/apple-libc%2B%2B-shared.cfg.in) warns that upstream libc++ lacks some Apple system-library symbols.
Its replacement tests require a separate library that supplies missing interfaces.
This is evidence against treating the downloaded runtime as a direct system-library replacement.
A library's minimum operating system metadata does not establish safe mixing of two runtime copies.

The Apple SDK header probe did not expose `std::format` in the selected configuration.
Unmodified LLVM 19 headers with the system runtime linked the format path but lacked newer `bad_expected_access` symbols.
Enabling the global Apple availability rules removed that latter mismatch in the successful probe.
The individual failed configurations remain failures and are not automatic alternatives in the application.

The temporary log directory preserves the following bounded records:

- `llvm-toolchain-probe.json` records the Apple linker abort.
- `llvm-lld-probe.json` records the unresolved language-support symbols.
- `llvm-explicit-runtime-probe.json` records the private-runtime crash.
- `llvm-sdk-header-probe.json` records the SDK header limitation.
- `llvm-headers-system-runtime-probe.json` records the newer key-function mismatch.
- `llvm-apple-availability-probe.json` records the selected successful configuration.

No full host crash report is included in this record.
The next acceptance work must exercise Qt and the complete application with the selected single system runtime.
Compiler success alone does not close that platform work.
