#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build/run register-only dense MMA; never changes GPU clocks or firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name('mma_register.cu')
BINARY = ROOT / 'build/mma-register'


def read_optional(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def build():
    nvcc = shutil.which('nvcc')
    if not nvcc:
        raise SystemExit('nvcc not found; install the CUDA toolkit and add its bin directory to PATH')
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    compiler = subprocess.check_output([nvcc, '--version'], text=True).strip()
    state = dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), compiler=compiler,
                 flags=['-O3', '-std=c++17', '-arch=sm_86', '-Xptxas=-v'])
    stamp = ROOT / 'build/mma-build-state.json'
    try:
        cached = json.loads(stamp.read_text())
        if (all(cached.get(k) == v for k, v in state.items()) and BINARY.is_file()
                and cached.get('binary_sha256') == hashlib.sha256(BINARY.read_bytes()).hexdigest()):
            return compiler
    except (OSError, ValueError):
        pass
    command = [nvcc, '-O3', '-std=c++17', '-arch=sm_86', '-Xptxas=-v',
               str(SOURCE), '-o', str(BINARY)]
    result = subprocess.run(command, text=True, capture_output=True)
    (ROOT / 'build/mma-build.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit('CUDA build failed; see build/mma-build.log')
    state['binary_sha256'] = hashlib.sha256(BINARY.read_bytes()).hexdigest()
    stamp.write_text(json.dumps(state, indent=2) + '\n')
    return compiler


def run_case(nv, handle, command):
    samples, errors = [], []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                samples.append(dict(unix_ns=time.time_ns(),
                    sm_mhz=nv.nvmlDeviceGetClockInfo(handle, nv.NVML_CLOCK_SM),
                    memory_mhz=nv.nvmlDeviceGetClockInfo(handle, nv.NVML_CLOCK_MEM),
                    watts=nv.nvmlDeviceGetPowerUsage(handle) / 1000,
                    temp_c=nv.nvmlDeviceGetTemperature(handle, nv.NVML_TEMPERATURE_GPU)))
            except nv.NVMLError as error:
                errors.append(type(error).__name__)
                break
            stop.wait(0.01)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        process = subprocess.run(command, text=True, capture_output=True, timeout=180)
    finally:
        stop.set()
        thread.join()
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or 'CUDA process failed')
    row = json.loads(process.stdout)
    measured = [s for s in samples if row['measure_start_unix_ns'] <= s['unix_ns'] <= row['measure_end_unix_ns']]
    row['telemetry'] = measured
    row['telemetry_errors'] = errors
    row['telemetry_sample_count'] = len(measured)
    if measured:
        row['mean_mhz'] = statistics.mean(s['sm_mhz'] for s in measured)
        row['min_mhz'] = min(s['sm_mhz'] for s in measured)
        row['max_mhz'] = max(s['sm_mhz'] for s in measured)
        row['memory_mhz_min'] = min(s['memory_mhz'] for s in measured)
        row['memory_mhz_max'] = max(s['memory_mhz'] for s in measured)
        row['mean_watts'] = statistics.mean(s['watts'] for s in measured)
        row['max_temp_c'] = max(s['temp_c'] for s in measured)
        row['ops_sm_clock'] = row['tera_ops_s'] * 1e6 / (row['sm'] * row['mean_mhz'])
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', help='User-declared state, e.g. on or off; not proof of unlock')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--device', type=int, default=0, help='CUDA device ordinal')
    parser.add_argument('--modes', nargs='+', choices=['fp16', 'bf16', 'tf32', 'int8'], default=['fp16', 'bf16', 'tf32'])
    parser.add_argument('--chains', nargs='+', type=int, choices=[1, 4, 8], default=[1, 4, 8])
    parser.add_argument('--threads', type=int, choices=[128, 256], default=128)
    parser.add_argument('--blocks-per-sm', type=int, default=8)
    parser.add_argument('--iterations', type=int, default=8192)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--require-clock', type=int, help='Reject cases not sampled at this exact SM MHz')
    args = parser.parse_args()
    if not 1 <= args.iterations <= 262144 or not 1 <= args.blocks_per_sm <= 32:
        parser.error('iterations must be 1..262144 and blocks-per-sm 1..32')
    if not 1 <= args.repeats <= 25 or args.repeats % 2 == 0:
        parser.error('repeats must be odd, 1..25')
    if not args.build_only and (not args.label or not args.output):
        parser.error('--label and --output are required for measurements')
    compiler = build()
    print('Ready: build/mma-register (sm_86); compiler details in build/mma-build.log', flush=True)
    if args.build_only:
        return
    try:
        import pynvml as nv
    except ImportError:
        raise SystemExit('Install nvidia-ml-py in this Python environment')
    info = json.loads(subprocess.check_output([str(BINARY), '--info', '--device', str(args.device)], text=True))
    nv.nvmlInit()
    try:
        handle = nv.nvmlDeviceGetHandleByPciBusId(info['pci_bus'])
        gpu_name = nv.nvmlDeviceGetName(handle)
        driver = nv.nvmlSystemGetDriverVersion()
        report = dict(schema=1, benchmark='dense-register-mma-sm86', label=args.label,
            gpu=gpu_name, sm=info['sm'], pci_bus=info['pci_bus'], driver=driver, compiler=compiler,
            source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
            module_version=read_optional('/sys/module/ga107_unlock/version'),
            execute_parameter=read_optional('/sys/module/ga107_unlock/parameters/execute'),
            ss1_full_parameter=read_optional('/sys/module/ga107_unlock/parameters/ss1_full'),
            clock_changes_performed=False, rows=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for mode in args.modes:
            for chains in args.chains:
                command = [str(BINARY), '--mode', mode, '--chains', str(chains),
                    '--device', str(args.device), '--threads', str(args.threads),
                    '--blocks-per-sm', str(args.blocks_per_sm), '--iterations', str(args.iterations),
                    '--repeats', str(args.repeats)]
                row = run_case(nv, handle, command)
                row['required_clock_passed'] = (args.require_clock is None or
                    (row.get('min_mhz') == row.get('max_mhz') == args.require_clock))
                report['rows'].append(row)
                args.output.write_text(json.dumps(report, indent=2) + '\n')
                clock = (f"{row['min_mhz']}..{row['max_mhz']} MHz, "
                         f"{row['ops_sm_clock']:.1f} ops/SM/clk") if 'mean_mhz' in row else 'no clock samples'
                print(f"{mode:4} chains={chains} {row['tera_ops_s']:8.3f} T/s, {clock}, "
                      f"regs={row['registers_per_thread']}, local={row['local_bytes_per_thread']} B, "
                      f"error={row['max_abs_error']}", flush=True)
                if row['local_bytes_per_thread']:
                    raise SystemExit('Local memory detected; inspect SASS before interpreting this as register-only')
                if not row['required_clock_passed']:
                    raise SystemExit('Required clock was not maintained or could not be sampled; partial result saved')
        print(f'Saved {args.output}', flush=True)
    finally:
        nv.nvmlShutdown()


if __name__ == '__main__':
    main()
