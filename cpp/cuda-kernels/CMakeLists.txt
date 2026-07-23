# cuda-kernels/CMakeLists.txt — GPU Monte Carlo & Portfolio Optimisation
cmake_minimum_required(VERSION 3.20)
project(tsar_cuda LANGUAGES CXX)

find_package(CUDAToolkit QUIET)

# ---------------------------------------------------------------------------
# Library target (CUDA when available, CPU stub otherwise)
# ---------------------------------------------------------------------------
if(CUDAToolkit_FOUND)
    enable_language(CUDA)
    add_library(tsar_cuda STATIC
        src/monte_carlo.cu
        src/portfolio_opt.cu
    )
    target_compile_definitions(tsar_cuda PUBLIC TSAR_HAS_CUDA=1)
    set_target_properties(tsar_cuda PROPERTIES
        CUDA_STANDARD 20
        CUDA_STANDARD_REQUIRED ON
    )
    message(STATUS "CUDA toolkit found — building GPU kernels")
else()
    # CPU stub: compile the .cu files as plain CXX with stub bodies
    add_library(tsar_cuda STATIC
        src/monte_carlo_stub.cpp
        src/portfolio_opt_stub.cpp
    )
    message(STATUS "CUDA NOT found — GPU kernels run in CPU STUB mode")
endif()

target_include_directories(tsar_cuda
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
