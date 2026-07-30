# tests/CMakeLists.txt — Unit tests for TSAR C++ modules
cmake_minimum_required(VERSION 3.20)
project(tsar_tests LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Simple test runner (no external test framework dependency)
# ---------------------------------------------------------------------------
add_executable(test_pricing test_pricing.cpp)
target_link_libraries(test_pricing PRIVATE tsar_pricing)

add_executable(test_fix test_fix.cpp)
target_link_libraries(test_fix PRIVATE tsar_fix)

# Monte Carlo test — link against both pricing and GPU stubs
add_executable(test_monte_carlo test_monte_carlo.cpp)
target_link_libraries(test_monte_carlo PRIVATE tsar_pricing tsar_cuda)

# CFFI integration test — exercises the full C ABI stack
add_executable(test_cffi test_cffi.cpp)
target_link_libraries(test_cffi PRIVATE tsar_cffi tsar_pricing tsar_fix)

# CTest integration
add_test(NAME pricing      COMMAND test_pricing)
add_test(NAME fix           COMMAND test_fix)
add_test(NAME monte_carlo   COMMAND test_monte_carlo)
add_test(NAME cffi          COMMAND test_cffi)
