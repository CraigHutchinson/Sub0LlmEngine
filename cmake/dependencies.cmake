# Dependencies through CPM, each pinned to an exact revision. For local development CPM honours CPM_<NAME>_SOURCE (the Sub0 dev
# machine points these at the checkouts under the GitHub folder); CPM prints "Using local source" when one is in effect.
include_guard(GLOBAL)
include(${CMAKE_CURRENT_LIST_DIR}/get_cpm.cmake)

# Sub0Platform: the operating-system layer (processes, files and locks, TCP and local sockets, host facts, waiting on several things at once).
# Only it and the net layer touch the operating system. Same pin as Sub0Squad (head of its default branch as of 2026-11-19); its tests are off here.
CPMAddPackage(NAME Sub0Platform
  GIT_REPOSITORY https://github.com/CraigHutchinson/Sub0Platform.git
  GIT_TAG 5feccdf226046cc790214bc30793832a1888ce4b
  SOURCE_SUBDIR cpp
  OPTIONS "SUB0PLATFORM_BUILD_TESTS OFF" "SUB0PLATFORM_INSTALL OFF")

# simdjson: the one JSON library (as in Sub0Squad and Sub0Llm). It stays private to the contracts layer (cmake/CheckLayers.cmake).
CPMAddPackage(NAME simdjson
  GIT_REPOSITORY https://github.com/simdjson/simdjson.git
  GIT_TAG 40a686ab89dc5ee58ec10d0514dd5c99abbc472b
  OPTIONS "SIMDJSON_DEVELOPER_MODE OFF")

# Version.cmake: git describe -> version fields and a generated header, refreshed on every configure (same pin and wrapper as Sub0Squad).
# Provides version::version and sub0engine::version::version_sha / version_full (...-dirty when the tree has changes).
set(VERSION_OUT_DIR "${CMAKE_BINARY_DIR}/generated/sub0engine")
set(VERSION_FALLBACK "0.0.0")
set(VERSION_H_FILENAME "Version.hpp")
set(VERSION_NAMESPACE "sub0engine::version")
# Version.cmake writes an empty header when the nearest tag is not a semantic version, so it is given a git that describes only v<major>.<minor>
# tags. The package is fetched with plain git and only then added: FetchContent's own git calls must not go through the wrapper (cmd.exe eats the
# `^` of `git rev-parse HEAD^0`).
CPMAddPackage(NAME Version.cmake
  GIT_REPOSITORY https://github.com/BareCpper/Version.cmake.git
  GIT_TAG c9e67af0aec3588912b760b45dca3ff217a62f59
  DOWNLOAD_ONLY YES)
if(CMAKE_HOST_WIN32)
  set(GIT_EXECUTABLE "${CMAKE_CURRENT_LIST_DIR}/git-semver.cmd")
else()
  set(GIT_EXECUTABLE "${CMAKE_CURRENT_LIST_DIR}/git-semver.sh")
endif()
add_subdirectory(${Version.cmake_SOURCE_DIR} ${CMAKE_BINARY_DIR}/_deps/version.cmake-build)
