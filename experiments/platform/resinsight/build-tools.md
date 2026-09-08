# Isolated build tools

This record prepares the remaining tools for the custom ResInsight experiment on macOS 14.2.1 arm64.
CMake and Ninja live in `/private/tmp/resinsight-p01-build/build-tools`.
GNU Bison installs under `/private/tmp/resinsight-p01-build/tools`.
The work does not change Homebrew packages or configure ResInsight or vcpkg.

## Versions and sources

The experiment selected CMake 3.31.6, Ninja 1.13.0, and GNU Bison 3.8.2.
The [ResInsight Mac workflow](https://github.com/OPM/ResInsight/blob/v2026.09.0/.github/workflows/ResInsightMac.yml) requires Bison newer than 2.5 for the Thrift dependency.
Its Homebrew installation step is replaced here by an isolated source build.
The selected Bison release exceeds that minimum.

The [CMake distribution](https://pypi.org/project/cmake/3.31.6/) and [Ninja distribution](https://pypi.org/project/ninja/1.13.0/) come from PyPI.
The CMake package reports version `3.31.6`.
The Ninja package reports version `1.13.0`, and its executable banner is `1.13.0.git.kitware.jobserver-pipe-1`.
The full banner identifies the packaged Ninja build without hiding its suffix.

Bison comes from the [official GNU source archive](https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz).
The release README requires GNU M4 1.4.6 or later.
This host provides GNU M4 1.4.6 at `/usr/bin/m4`.
The build uses the existing Apple Clang 15.0.0 at `/usr/bin/clang`.

## CMake and Ninja installation

The environment uses Python 3.12.13.
The pinned PyPI packages install without a local compiler build.
No global Python packages are changed.

```sh
cd /private/tmp/resinsight-p01-build
uv venv --python 3.12 /private/tmp/resinsight-p01-build/build-tools
uv pip install --python /private/tmp/resinsight-p01-build/build-tools/bin/python \
  cmake==3.31.6 ninja==1.13.0
build-tools/bin/cmake --version
build-tools/bin/ninja --version
```

## Bison source build

The source release includes its generated configuration script.
The build does not need a Git bootstrap or new system dependencies.
Disabling translated messages avoids a separate gettext requirement.
Compilation uses at most two jobs.

```sh
cd /private/tmp/resinsight-p01-build
mkdir -p downloads sources tools
curl -fsSL https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz \
  -o downloads/bison-3.8.2.tar.xz
tar -xJf downloads/bison-3.8.2.tar.xz -C sources
cd sources/bison-3.8.2
LC_ALL=en_US.UTF-8 CC=/usr/bin/clang ./configure \
  --prefix=/private/tmp/resinsight-p01-build/tools --disable-nls
LC_ALL=en_US.UTF-8 /usr/bin/make -j2
LC_ALL=en_US.UTF-8 /usr/bin/make install
```

The locale applies only to each command.
The install prefix keeps the host's Bison unchanged.
The build logs live in `/private/tmp/resinsight-p01-build/build-tools-evidence`.

## Installed evidence

The installation completed on September 8, 2026.
Bison configuration, compilation, and installation returned status 0.
The installed Bison data directory is `/private/tmp/resinsight-p01-build/tools/share/bison`.
The version commands reported these results:

```text
cmake version 3.31.6
1.13.0.git.kitware.jobserver-pipe-1
bison (GNU Bison) 3.8.2
```

The functional test uses Bison's own `examples/c/calc/calc.y` grammar.
A grammar defines the input that a parser accepts.
The installed Bison generated C code, and Apple Clang compiled that code into a working calculator.
The two expressions test arithmetic precedence and parentheses.

```sh
cd /private/tmp/resinsight-p01-build
mkdir -p build-tools-evidence
tools/bin/bison --defines=build-tools-evidence/calc.h \
  --output=build-tools-evidence/calc.c \
  sources/bison-3.8.2/examples/c/calc/calc.y
/usr/bin/clang build-tools-evidence/calc.c -o build-tools-evidence/calc
printf '1+2*3\n(1+2)*3\n' | build-tools-evidence/calc
```

The program printed `7` and `9` and returned status 0.
This establishes a small parser-generation path, not full Bison test coverage.
It does not establish ResInsight or Thrift build success.

The `du -sk` command reported 125,872 KiB for the Python tool environment and 2,752 KiB for the installed Bison prefix.
The Bison source and build directory used 55,988 KiB.
The shared filesystem reported 21 GiB free at that point.
Other build preparation can change that free-space measurement.

The evidence folder retains the configure, build, and install logs.
It also retains version records, the generated calculator, and `calc-results.txt`.
No generated tools or test artifacts are committed to the repository.

## Build path

Add these directories to the environment for the custom build:

```sh
PATH="/private/tmp/resinsight-p01-build/tools/bin:/private/tmp/resinsight-p01-build/build-tools/bin:$PATH"
export PATH
```

This command changes the current shell environment only.
The custom compiler and Qt paths remain separate inputs.
Preparing these tools does not prove that ResInsight or vcpkg builds successfully.
