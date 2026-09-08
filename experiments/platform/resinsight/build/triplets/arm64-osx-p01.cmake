include("/private/tmp/resinsight-p01-build/source/ThirdParty/vcpkg-overlay-triplets/arm64-osx.cmake")
set(VCPKG_BUILD_TYPE release)
set(VCPKG_OSX_DEPLOYMENT_TARGET "14.2")
get_filename_component(P01_CONFIGURATION "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "${P01_CONFIGURATION}/llvm19.cmake")
list(APPEND VCPKG_HASH_ADDITIONAL_FILES
    "/private/tmp/resinsight-p01-build/source/ThirdParty/vcpkg-overlay-triplets/arm64-osx.cmake"
    "/private/tmp/resinsight-p01-build/apple-libcxx/include/c++/v1/__config_site"
    "${VCPKG_CHAINLOAD_TOOLCHAIN_FILE}")
