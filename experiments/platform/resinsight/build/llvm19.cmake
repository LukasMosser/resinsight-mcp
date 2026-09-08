include_guard(GLOBAL)

# These paths describe the isolated P01 host experiment.
set(P01_BUILD_ROOT "/private/tmp/resinsight-p01-build")
set(P01_LLVM "${P01_BUILD_ROOT}/compiler/LLVM-19.1.7-macOS-ARM64")
set(CMAKE_C_COMPILER "${P01_LLVM}/bin/clang" CACHE FILEPATH "")
set(CMAKE_CXX_COMPILER "${P01_LLVM}/bin/clang++" CACHE FILEPATH "")
set(CMAKE_AR "${P01_LLVM}/bin/llvm-ar" CACHE FILEPATH "")
set(CMAKE_RANLIB "${P01_LLVM}/bin/llvm-ranlib" CACHE FILEPATH "")
set(CMAKE_OSX_ARCHITECTURES "arm64" CACHE STRING "")
set(CMAKE_OSX_DEPLOYMENT_TARGET "14.2" CACHE STRING "")
execute_process(COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE P01_SDK OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY)
set(CMAKE_OSX_SYSROOT "${P01_SDK}" CACHE PATH "")
include("${P01_BUILD_ROOT}/source/ThirdParty/vcpkg/scripts/toolchains/osx.cmake")

# The configured headers enable Apple's version availability checks.
# Both the application and Qt link Apple's system C++ runtime.
string(APPEND CMAKE_CXX_FLAGS_INIT
    " -stdlib=libc++ -nostdinc++ -isystem ${P01_BUILD_ROOT}/apple-libcxx/include/c++/v1")
foreach(kind EXE SHARED MODULE)
    string(APPEND CMAKE_${kind}_LINKER_FLAGS_INIT " -fuse-ld=lld")
endforeach()
