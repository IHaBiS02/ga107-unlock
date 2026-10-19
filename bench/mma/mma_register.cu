// SPDX-License-Identifier: GPL-2.0-only
// Dense Ampere warp MMA, with register-only operands inside the timed loop.
#include <cuda_runtime.h>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

#define CUDA_CHECK(call) do { cudaError_t e = (call); if (e != cudaSuccess) \
    throw std::runtime_error(std::string(#call) + ": " + cudaGetErrorString(e)); } while (0)

// All operands represent 2^-8. Uniform fragments make every output exactly
// K * 2^-16 per instruction, independently of the lane/fragment mapping.
template<int Mode>
__device__ __forceinline__ void mma(float (&d)[4], unsigned x) {
#define MMA_TEXT(shape, type) \
    "mma.sync.aligned." shape ".row.col.f32." type "." type ".f32 " \
    "{%0,%1,%2,%3}, {%4,%4,%4,%4}, {%4,%4}, {%0,%1,%2,%3};\n"
    if constexpr (Mode == 0) {
        asm volatile(MMA_TEXT("m16n8k16", "f16")
            : "+f"(d[0]), "+f"(d[1]), "+f"(d[2]), "+f"(d[3]) : "r"(x));
    } else if constexpr (Mode == 1) {
        asm volatile(MMA_TEXT("m16n8k16", "bf16")
            : "+f"(d[0]), "+f"(d[1]), "+f"(d[2]), "+f"(d[3]) : "r"(x));
    } else {
        asm volatile(MMA_TEXT("m16n8k8", "tf32")
            : "+f"(d[0]), "+f"(d[1]), "+f"(d[2]), "+f"(d[3]) : "r"(x));
    }
#undef MMA_TEXT
}

template<int Mode, int Chains>
__global__ void tensor_loop(float* output, int iterations, unsigned operand) {
    float acc[Chains][4] = {};
    // Each chain has a dependency through C/D. Independent chains expose ILP.
    // Full warps execute the same MMA instruction without divergent control.
    for (int i = 0; i < iterations; ++i) {
#pragma unroll
        for (int u = 0; u < 8; ++u) {
#pragma unroll
            for (int c = 0; c < Chains; ++c) mma<Mode>(acc[c], operand);
        }
    }
    size_t thread = size_t(blockIdx.x) * blockDim.x + threadIdx.x;
#pragma unroll
    for (int c = 0; c < Chains; ++c)
#pragma unroll
        for (int j = 0; j < 4; ++j)
            output[(thread * Chains + c) * 4 + j] = acc[c][j];
}

struct Options {
    std::string mode = "bf16";
    int chains = 4, iterations = 8192, repeats = 7, threads = 128;
    int blocks_per_sm = 8, device = 0;
};

int number(const char* value) {
    char* end = nullptr;
    long n = std::strtol(value, &end, 10);
    if (!*value || *end || n < 0 || n > 10000000) throw std::runtime_error("invalid integer");
    return int(n);
}

template<int Mode, int Chains>
void run(const Options& o, const cudaDeviceProp& p) {
    int blocks = p.multiProcessorCount * o.blocks_per_sm;
    size_t elements = size_t(blocks) * o.threads * Chains * 4;
    float* output = nullptr;
    CUDA_CHECK(cudaMalloc(&output, elements * sizeof(float)));
    cudaEvent_t begin, end;
    CUDA_CHECK(cudaEventCreate(&begin));
    CUDA_CHECK(cudaEventCreate(&end));
    unsigned operand = Mode == 0 ? 0x1c001c00u : Mode == 1 ? 0x3b803b80u : 0x3b800000u;
    int k = Mode == 2 ? 8 : 16;
    cudaFuncAttributes attributes;
    CUDA_CHECK(cudaFuncGetAttributes(&attributes, tensor_loop<Mode, Chains>));
    int active_blocks = 0;
    CUDA_CHECK(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
        &active_blocks, tensor_loop<Mode, Chains>, o.threads, 0));
    auto launch = [&]() {
        tensor_loop<Mode, Chains><<<blocks, o.threads>>>(output, o.iterations, operand);
        CUDA_CHECK(cudaGetLastError());
    };
    // Warm up the same instruction stream for >= 0.3 seconds.
    float warmed_ms = 0;
    do {
        CUDA_CHECK(cudaEventRecord(begin));
        launch();
        CUDA_CHECK(cudaEventRecord(end));
        CUDA_CHECK(cudaEventSynchronize(end));
        float ms;
        CUDA_CHECK(cudaEventElapsedTime(&ms, begin, end));
        warmed_ms += ms;
    } while (warmed_ms < 300);
    auto unix_ns = []() { return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count(); };
    auto measure_start = unix_ns();
    std::vector<float> times;
    for (int r = 0; r < o.repeats; ++r) {
        CUDA_CHECK(cudaEventRecord(begin));
        launch();
        CUDA_CHECK(cudaEventRecord(end));
        CUDA_CHECK(cudaEventSynchronize(end));
        float ms;
        CUDA_CHECK(cudaEventElapsedTime(&ms, begin, end));
        times.push_back(ms);
    }
    auto measure_end = unix_ns();
    // Check every output from every thread and every chain (not only a sample).
    std::vector<float> actual(elements);
    CUDA_CHECK(cudaMemcpy(actual.data(), output, elements * sizeof(float), cudaMemcpyDeviceToHost));
    float expected = float(double(o.iterations) * 8 * k / 65536.0);
    double max_error = 0;
    for (float x : actual) {
        if (!std::isfinite(x)) throw std::runtime_error("non-finite MMA output");
        max_error = std::max(max_error, std::abs(double(x) - expected));
    }
    if (max_error != 0) throw std::runtime_error("MMA output differs from exact reference");
    auto sorted = times;
    std::sort(sorted.begin(), sorted.end());
    double median_ms = sorted[sorted.size() / 2];
    // Each warp MMA performs 2*M*N*K scalar ops, FMA counted as two.
    double operations = double(blocks) * (o.threads / 32) * o.iterations * 8 * Chains * 2 * 16 * 8 * k;
    char bus[32];
    CUDA_CHECK(cudaDeviceGetPCIBusId(bus, sizeof(bus), o.device));
    printf("{\"mode\":\"%s\",\"chains\":%d,\"iterations\":%d,\"unroll\":8,"
           "\"threads\":%d,\"blocks\":%d,\"sm\":%d,\"compute_capability\":\"%d.%d\","
           "\"pci_bus\":\"%s\",\"registers_per_thread\":%d,\"local_bytes_per_thread\":%zu,"
           "\"max_active_blocks_per_sm\":%d,\"median_ms\":%.9g,\"tera_ops_s\":%.9g,"
           "\"total_operations_per_launch\":%.0f,\"checked_elements\":%zu,"
           "\"expected_value\":%.9g,\"max_abs_error\":%.9g,\"samples_ms\":[",
           o.mode.c_str(), Chains, o.iterations, o.threads, blocks, p.multiProcessorCount,
           p.major, p.minor, bus, attributes.numRegs, attributes.localSizeBytes,
           active_blocks, median_ms, operations / (median_ms * 1e9), operations,
           elements, expected, max_error);
    for (size_t i = 0; i < times.size(); ++i) printf("%s%.9g", i ? "," : "", times[i]);
    printf("],\"measure_start_unix_ns\":%lld,\"measure_end_unix_ns\":%lld}\n",
           (long long)measure_start, (long long)measure_end);
    CUDA_CHECK(cudaEventDestroy(begin));
    CUDA_CHECK(cudaEventDestroy(end));
    CUDA_CHECK(cudaFree(output));
}

template<int Mode> void dispatch(const Options& o, const cudaDeviceProp& p) {
    if (o.chains == 1) run<Mode, 1>(o, p);
    else if (o.chains == 4) run<Mode, 4>(o, p);
    else run<Mode, 8>(o, p);
}

int main(int argc, char** argv) {
    try {
        Options o;
        bool info_only = false;
        for (int i = 1; i < argc; ++i) {
            std::string key = argv[i];
            if (key == "--info") { info_only = true; continue; }
            if (key == "--help") {
                puts("--mode fp16|bf16|tf32 --chains 1|4|8 --iterations 1..262144 "
                     "--repeats 1..25 (odd) --threads 128|256 --blocks-per-sm 1..32 --device N");
                return 0;
            }
            if (++i == argc) throw std::runtime_error("missing option value");
            if (key == "--mode") o.mode = argv[i];
            else if (key == "--chains") o.chains = number(argv[i]);
            else if (key == "--iterations") o.iterations = number(argv[i]);
            else if (key == "--repeats") o.repeats = number(argv[i]);
            else if (key == "--threads") o.threads = number(argv[i]);
            else if (key == "--blocks-per-sm") o.blocks_per_sm = number(argv[i]);
            else if (key == "--device") o.device = number(argv[i]);
            else throw std::runtime_error("unknown option: " + key);
        }
        if ((o.mode != "fp16" && o.mode != "bf16" && o.mode != "tf32") ||
            (o.chains != 1 && o.chains != 4 && o.chains != 8) ||
            o.iterations < 1 || o.iterations > 262144 || o.repeats < 1 || o.repeats > 25 ||
            o.repeats % 2 == 0 || (o.threads != 128 && o.threads != 256) ||
            o.blocks_per_sm < 1 || o.blocks_per_sm > 32)
            throw std::runtime_error("unsupported argument range; see --help");
        CUDA_CHECK(cudaSetDevice(o.device));
        cudaDeviceProp props;
        CUDA_CHECK(cudaGetDeviceProperties(&props, o.device));
        if (props.major != 8 || props.minor != 6)
            throw std::runtime_error("this binary is scoped to sm_86 (GA10x)");
        if (info_only) {
            char bus[32];
            CUDA_CHECK(cudaDeviceGetPCIBusId(bus, sizeof(bus), o.device));
            printf("{\"pci_bus\":\"%s\",\"sm\":%d}\n", bus, props.multiProcessorCount);
            return 0;
        }
        if (o.mode == "fp16") dispatch<0>(o, props);
        else if (o.mode == "bf16") dispatch<1>(o, props);
        else dispatch<2>(o, props);
    } catch (const std::exception& e) {
        fprintf(stderr, "mma_register: %s\n", e.what());
        return 1;
    }
}
