# quantlib-pricing/CMakeLists.txt
cmake_minimum_required(VERSION 3.20)
project(tsar_pricing LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Optional QuantLib dependency
# ---------------------------------------------------------------------------
find_package(QuantLib QUIET)

# ---------------------------------------------------------------------------
# Library target
# ---------------------------------------------------------------------------
add_library(tsar_pricing STATIC
    src/pricing_engine.cpp
    src/option_pricer.cpp
)

target_include_directories(tsar_pricing
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

# Link QuantLib if found; otherwise the engine runs in stub mode
if(QuantLib_FOUND)
    target_link_libraries(tsar_pricing PUBLIC QuantLib::QuantLib)
    target_compile_definitions(tsar_pricing PUBLIC TSAR_HAS_QUANTLIB=1)
    message(STATUS "QuantLib found — enabling live pricing backend")
else()
    message(STATUS "QuantLib NOT found — pricing engine runs in STUB mode")
endif()
