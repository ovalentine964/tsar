# quantlib-pricing/CMakeLists.txt — FIX Engine module
cmake_minimum_required(VERSION 3.20)
project(tsar_fix LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Optional QuickFIX dependency
# ---------------------------------------------------------------------------
find_package(QuickFIX QUIET)

# ---------------------------------------------------------------------------
# Library target
# ---------------------------------------------------------------------------
add_library(tsar_fix STATIC
    src/fix_gateway.cpp
    src/fix_session.cpp
)

target_include_directories(tsar_fix
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

# Link QuickFIX if found; otherwise stub mode
if(QuickFIX_FOUND)
    target_link_libraries(tsar_fix PUBLIC QuickFIX::QuickFIX)
    target_compile_definitions(tsar_fix PUBLIC TSAR_HAS_QUICKFIX=1)
    message(STATUS "QuickFIX found — enabling live FIX gateway")
else()
    message(STATUS "QuickFIX NOT found — FIX gateway runs in STUB mode")
endif()
