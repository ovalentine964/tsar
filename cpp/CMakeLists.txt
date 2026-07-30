# =============================================================================
# TSAR — Trading Super Agent Regime
# Root CMakeLists.txt — C++ Module Workspace
# =============================================================================
cmake_minimum_required(VERSION 3.20)
project(tsar_cpp
    VERSION 0.1.0
    DESCRIPTION "TSAR C++ Modules — QuantLib Pricing, FIX Engine, CUDA, CFFI"
    LANGUAGES CXX
)

# ---------------------------------------------------------------------------
# Global C++20 settings
# ---------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Position-independent code (required for shared-library / Python extension)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Append custom CMake modules
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------
option(TSAR_BUILD_PRICING   "Build quantlib-pricing module"   ON)
option(TSAR_BUILD_FIX       "Build fix-engine module"        ON)
option(TSAR_BUILD_CUDA      "Build cuda-kernels module"      OFF)  # Requires CUDA
option(TSAR_BUILD_CFFI      "Build cffi-bindings module"     ON)
option(TSAR_BUILD_TESTS     "Build tests"                    ON)

# ---------------------------------------------------------------------------
# Compiler warnings (global)
# ---------------------------------------------------------------------------
add_compile_options(
    -Wall -Wextra -Wpedantic -Wno-unused-parameter
    -Wconversion -Wsign-conversion
)

# ---------------------------------------------------------------------------
# Sub-modules
# ---------------------------------------------------------------------------
if(TSAR_BUILD_PRICING)
    add_subdirectory(quantlib-pricing)
endif()

if(TSAR_BUILD_FIX)
    add_subdirectory(fix-engine)
endif()

if(TSAR_BUILD_CUDA)
    enable_language(CUDA)
    add_subdirectory(cuda-kernels)
endif()

if(TSAR_BUILD_CFFI)
    add_subdirectory(cffi-bindings)
endif()

if(TSAR_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
