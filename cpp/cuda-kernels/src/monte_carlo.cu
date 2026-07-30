// =============================================================================
// monte_carlo.cu — GPU Monte Carlo option pricing (CUDA)
// =============================================================================
//
// Production kernel: warp-shuffle parallel reduction for mean/variance,
// pathwise delta estimator, antithetic variates for variance reduction.
// Each block handles one option; threads within a block cooperate on paths.
// =============================================================================

#ifdef TSAR_HAS_CUDA

#include "tsar/gpu/monte_carlo.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>

#include <cstdio>
#include <cstring>
#include <cmath>

namespace tsar::gpu {

// ---------------------------------------------------------------------------
// Warp-level reduction (shuffle)
// ---------------------------------------------------------------------------
__device__ __forceinline__ double warp_reduce_sum(double val) {
    for (int offset = warpSize / 2; offset > 0; offset >>= 1) {
        val += __shfl_down_sync(0xFFFFFFFF, val, offset);
    }
    return val;
}

// ---------------------------------------------------------------------------
// Block-level reduction via shared memory
// ---------------------------------------------------------------------------
__device__ double block_reduce_sum(double val, double* shared) {
    int lane = threadIdx.x % warpSize;
    int wid  = threadIdx.x / warpSize;

    val = warp_reduce_sum(val);
    if (lane == 0) shared[wid] = val;
    __syncthreads();

    // First warp reduces the partial sums
    int num_warps = (blockDim.x + warpSize - 1) / warpSize;
    val = (threadIdx.x < num_warps) ? shared[threadIdx.x] : 0.0;
    if (wid == 0) val = warp_reduce_sum(val);

    return val;
}

// ---------------------------------------------------------------------------
// CUDA kernel — one block per option, threads cooperate on paths
// ---------------------------------------------------------------------------
__global__ void mc_kernel(const MCOptionParams* __restrict__ params,
                          MCResult* __restrict__ results,
                          uint64_t n_paths,
                          uint64_t seed,
                          size_t n_options) {
    extern __shared__ double sdata[];

    size_t opt_idx = blockIdx.x;
    if (opt_idx >= n_options) return;

    const MCOptionParams& p = params[opt_idx];

    double vol2    = p.vol * p.vol;
    double sqrt_T  = sqrt(p.time_years);
    double drift   = (p.rate - 0.5 * vol2) * p.time_years;
    double diffusion = p.vol * sqrt_T;
    double discount  = exp(-p.rate * p.time_years);
    double S_inv     = 1.0 / p.spot;  // For pathwise delta: d(ST)/dS = ST/S

    // Antithetic variates: each thread generates z and -z
    double local_payoff_sum   = 0.0;
    double local_payoff_sq    = 0.0;
    double local_delta_sum    = 0.0;

    curandStatePhilox4_32_10_t rng;
    curand_init(seed, opt_idx * blockDim.x + threadIdx.x, 0, &rng);

    uint64_t paths_per_thread = (n_paths + blockDim.x - 1) / blockDim.x;

    for (uint64_t i = 0; i < paths_per_thread; ++i) {
        double z = curand_normal_double(&rng);

        // Path 1: +z
        double ST1   = p.spot * exp(drift + diffusion * z);
        double payoff1 = p.is_call ? fmax(ST1 - p.strike, 0.0)
                                   : fmax(p.strike - ST1, 0.0);

        // Path 2 (antithetic): -z
        double ST2   = p.spot * exp(drift - diffusion * z);
        double payoff2 = p.is_call ? fmax(ST2 - p.strike, 0.0)
                                   : fmax(p.strike - ST2, 0.0);

        double avg_payoff = 0.5 * (payoff1 + payoff2);
        local_payoff_sum += avg_payoff;
        local_payoff_sq  += avg_payoff * avg_payoff;

        // Pathwise delta: d(payoff)/dS = (payoff derivative w.r.t. S)
        // For call: d(max(ST-K,0))/dS = ST/S * I(ST>K)
        // For put:  d(max(K-ST,0))/dS = -ST/S * I(ST>K)
        if (p.is_call) {
            double d1 = (ST1 > p.strike) ? ST1 * S_inv : 0.0;
            double d2 = (ST2 > p.strike) ? ST2 * S_inv : 0.0;
            local_delta_sum += 0.5 * (d1 + d2);
        } else {
            double d1 = (ST1 < p.strike) ? -ST1 * S_inv : 0.0;
            double d2 = (ST2 < p.strike) ? -ST2 * S_inv : 0.0;
            local_delta_sum += 0.5 * (d1 + d2);
        }
    }

    // Block-level reductions
    double sum_payoff = block_reduce_sum(local_payoff_sum, sdata);
    double sum_sq     = block_reduce_sum(local_payoff_sq,  sdata);
    double sum_delta  = block_reduce_sum(local_delta_sum,  sdata);

    if (threadIdx.x == 0) {
        double n = static_cast<double>(n_paths);
        double mean_payoff = sum_payoff / n;
        double var_payoff  = (sum_sq / n) - (mean_payoff * mean_payoff);
        // Clamp variance to avoid negative due to floating point
        var_payoff = fmax(var_payoff, 0.0);

        results[opt_idx].price     = discount * mean_payoff;
        results[opt_idx].std_error = discount * sqrt(var_payoff / n);
        results[opt_idx].delta     = discount * (sum_delta / n);
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
GPUError monte_carlo_batch(const MCOptionParams* params,
                           size_t n_options,
                           uint64_t n_paths,
                           uint64_t seed,
                           MCResult* results) {
    if (!params || !results || n_options == 0 || n_paths == 0) {
        return GPUError::InvalidInput;
    }

    MCOptionParams* d_params  = nullptr;
    MCResult*       d_results = nullptr;

    cudaError_t err;
    err = cudaMalloc(&d_params, n_options * sizeof(MCOptionParams));
    if (err != cudaSuccess) return GPUError::DeviceMemory;

    err = cudaMalloc(&d_results, n_options * sizeof(MCResult));
    if (err != cudaSuccess) { cudaFree(d_params); return GPUError::DeviceMemory; }

    cudaMemcpy(d_params, params, n_options * sizeof(MCOptionParams),
               cudaMemcpyHostToDevice);

    constexpr int block_size = 256;
    size_t shared_bytes = ((block_size + 31) / 32) * sizeof(double);

    mc_kernel<<<(int)n_options, block_size, shared_bytes>>>(
        d_params, d_results, n_paths, seed, n_options);

    err = cudaGetLastError();
    if (err != cudaSuccess) {
        cudaFree(d_params);
        cudaFree(d_results);
        return GPUError::KernelLaunch;
    }

    cudaDeviceSynchronize();

    cudaMemcpy(results, d_results, n_options * sizeof(MCResult),
               cudaMemcpyDeviceToHost);

    cudaFree(d_params);
    cudaFree(d_results);

    return GPUError::Ok;
}

// ---------------------------------------------------------------------------
// VaR via historical simulation — GPU sort + percentile
// ---------------------------------------------------------------------------
__global__ void sort_step(double* data, size_t n, int phase) {
    size_t i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n - 1) return;

    // Odd-even transposition sort (simple, works for moderate n)
    bool is_odd_step = (phase % 2 == 1);
    bool is_even_idx = (i % 2 == 0);

    if ((is_odd_step && !is_even_idx) || (!is_odd_step && is_even_idx)) {
        if (data[i] > data[i + 1]) {
            double tmp = data[i];
            data[i] = data[i + 1];
            data[i + 1] = tmp;
        }
    }
}

GPUError var_historical(const double* returns,
                        size_t n_returns,
                        double portfolio_value,
                        double confidence,
                        double* var_out) {
    if (!returns || !var_out || n_returns == 0) {
        return GPUError::InvalidInput;
    }

    // Copy returns to device
    double* d_returns = nullptr;
    cudaError_t err = cudaMalloc(&d_returns, n_returns * sizeof(double));
    if (err != cudaSuccess) return GPUError::DeviceMemory;

    cudaMemcpy(d_returns, returns, n_returns * sizeof(double),
               cudaMemcpyHostToDevice);

    // Sort on GPU using odd-even transposition sort
    // (Production: use CUB radix sort or thrust::sort)
    constexpr int block_size = 256;
    int num_blocks = (n_returns + block_size - 1) / block_size;
    for (size_t phase = 0; phase < n_returns; ++phase) {
        sort_step<<<num_blocks, block_size>>>(d_returns, n_returns, (int)phase);
    }
    cudaDeviceSynchronize();

    // Read back sorted returns
    std::vector<double> sorted(n_returns);
    cudaMemcpy(sorted.data(), d_returns, n_returns * sizeof(double),
               cudaMemcpyDeviceToHost);
    cudaFree(d_returns);

    // VaR = -percentile(1 - confidence) * portfolio_value
    size_t idx = static_cast<size_t>((1.0 - confidence) * n_returns);
    if (idx >= n_returns) idx = n_returns - 1;

    *var_out = -sorted[idx] * portfolio_value;
    if (*var_out < 0.0) *var_out = 0.0;  // VaR is non-negative

    return GPUError::Ok;
}

}  // namespace tsar::gpu

#endif  // TSAR_HAS_CUDA
