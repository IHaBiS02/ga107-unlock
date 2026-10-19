"""Read-only GPU configuration; dense GEMM throughput with NVML telemetry.

No firmware execution or clock/power setting changes. Rates count FMA as 2 ops.
Clock-normalized rates are estimates when the GPU clock varies. INT8 uses
PyTorch's internal _int_mm API; no INT4 or scalar half/bfloat16 claim is made.
"""
import json
import statistics
import threading
import time
from pathlib import Path

import pynvml as nv
import torch


def measure(name, dtype, n, acc16=False, tf32=False, transpose_b=False):
    torch.backends.cuda.matmul.allow_fp16_accumulation = acc16
    torch.backends.cuda.matmul.allow_tf32 = tf32
    torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
    torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
    if dtype == torch.int8:
        a = torch.randint(-2, 3, (n, n), device='cuda', dtype=dtype)
        b = torch.randint(-2, 3, (n, n), device='cuda', dtype=dtype)
        if transpose_b:
            b = b.t()
        op = lambda: torch._int_mm(a, b)
    else:
        a = torch.randn(n, n, device='cuda', dtype=dtype) * 0.01
        b = torch.randn(n, n, device='cuda', dtype=dtype) * 0.01
        op = lambda: a @ b
    # Check a submatrix against the full dot products before warming up.
    out = op()
    ref = a[:8].double() @ b[:, :8].double()
    actual = out[:8, :8].double()
    error = (actual - ref).abs().max().item()
    scale = ref.abs().max().item()
    tolerance = 0 if dtype == torch.int8 else max(1e-7, scale * 0.03)
    if not torch.isfinite(actual).all().item() or error > tolerance:
        raise RuntimeError(f'{name} correctness check failed: {error=} {tolerance=}')
    del out, ref, actual
    warm = time.perf_counter()
    while time.perf_counter() - warm < 1.5:
        op()
        torch.cuda.synchronize()
    samples, stop = [], threading.Event()
    def sample():
        while not stop.is_set():
            samples.append(dict(t=time.perf_counter(),
                mhz=nv.nvmlDeviceGetClockInfo(handle, nv.NVML_CLOCK_SM),
                watts=nv.nvmlDeviceGetPowerUsage(handle)/1000,
                temp=nv.nvmlDeviceGetTemperature(handle, nv.NVML_TEMPERATURE_GPU)))
            stop.wait(0.05)
    thread = threading.Thread(target=sample)
    thread.start()
    count, start = 0, time.perf_counter()
    while time.perf_counter() - start < 4:
        for _ in range(5):
            op()
        torch.cuda.synchronize()
        count += 5
    elapsed = time.perf_counter() - start
    stop.set()
    thread.join()
    rate = 2*n**3*count/elapsed/1e12
    mean_mhz = statistics.mean(s['mhz'] for s in samples)
    result = dict(mode=name, n=n, tera_ops_s=rate, mean_mhz=mean_mhz,
        min_mhz=min(s['mhz'] for s in samples), max_mhz=max(s['mhz'] for s in samples),
        ops_sm_clock=rate*1e12/(sms*mean_mhz*1e6),
        mean_watts=statistics.mean(s['watts'] for s in samples),
        max_temp=max(s['temp'] for s in samples), max_abs_error=error,
        correctness_tolerance=tolerance, samples=samples)
    print(f"{name:20} {rate:7.3f} T/s  {mean_mhz:6.0f} MHz "
          f"[{result['min_mhz']},{result['max_mhz']}]  "
          f"{result['ops_sm_clock']:7.1f} ops/SM/clk  "
          f"{result['mean_watts']:.1f} W  {result['max_temp']} C", flush=True)
    del a, b
    torch.cuda.empty_cache()
    return result


if __name__ == '__main__':
    nv.nvmlInit()
    props = torch.cuda.get_device_properties(0)
    # Match the CUDA device by UUID rather than assuming NVML index order.
    handle = nv.nvmlDeviceGetHandleByUUID('GPU-' + str(props.uuid))
    sms = props.multi_processor_count
    modes = [('FP16 acc16', torch.float16, 8192, True, False),
             ('FP16 acc32', torch.float16, 8192, False, False),
             ('BF16 acc32', torch.bfloat16, 8192, False, False),
             ('TF32', torch.float32, 8192, False, True),
             ('FP32 no tensor', torch.float32, 4096, False, False),
             ('FP64', torch.float64, 2048, False, False),
             ('INT8 row-major', torch.int8, 8192, False, False),
             ('INT8 tensor acc32', torch.int8, 8192, False, False, True)]
    report = dict(gpu=props.name, sm=sms, torch=torch.__version__, cuda=torch.version.cuda,
                  clock_setting='unchanged', rounds=[])
    path = Path(__file__).with_name('bench-extended-results.json')
    print(f'{props.name}, SM={sms}, torch={torch.__version__}', flush=True)
    try:
        for rnd in range(2):
            print(f'Round {rnd+1}', flush=True)
            rows = []
            report['rounds'].append(rows)
            for args in modes:
                rows.append(measure(*args))
                path.write_text(json.dumps(report, indent=2))
    finally:
        nv.nvmlShutdown()
