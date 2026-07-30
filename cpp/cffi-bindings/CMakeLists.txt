# cffi-bindings/CMakeLists.txt — C ABI for Rust/Python interop
cmake_minimum_required(VERSION 3.20)
project(tsar_cffi LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Library target — shared library for FFI consumers
# ---------------------------------------------------------------------------
add_library(tsar_cffi SHARED
    src/tsar_cffi.cpp
)

target_include_directories(tsar_cffi
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

# Link against TSAR modules that we expose via FFI
target_link_libraries(tsar_cffi
    PRIVATE tsar_pricing
    PRIVATE tsar_fix
    PRIVATE tsar_cuda
)

# Versioned .so
set_target_properties(tsar_cffi PROPERTIES
    VERSION   ${PROJECT_VERSION}
    SOVERSION 0
    # Hide all symbols except extern "C" exports
    C_VISIBILITY_PRESET hidden
    CXX_VISIBILITY_PRESET hidden
)
