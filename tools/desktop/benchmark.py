#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Print register MMA measurements only; no result files or GPU setting changes."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
MODES = ('fp16', 'bf16', 'tf32', 'int8')


def read_clock(bus):
    """Read only; nvidia-smi is available with the driver, no pynvml needed."""
    started = time.time_ns()
    result = subprocess.run(
        ['nvidia-smi', '-i', bus, '--query-gpu=clocks.current.sm',
         '--format=csv,noheader,nounits'],
        text=True, capture_output=True, timeout=2)
    ended = time.time_ns()
    if result.returncode:
        raise ValueError('SM clock unavailable')
    mhz = int(result.stdout.strip())
    if mhz <= 0:
        raise ValueError('Invalid SM clock')
    return started, ended, mhz


def measure(command, bus):
    samples = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                samples.append(read_clock(bus))
            except (OSError, ValueError, subprocess.SubprocessError):
                break
            stop.wait(0.02)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=180)
    finally:
        stop.set()
        thread.join()
    if result.returncode:
        raise SystemExit(result.stderr.strip() or 'CUDA 측정 실패')
    row = json.loads(result.stdout)
    # Exclude warm-up and queries that straddle measurement boundaries.
    row['clock_samples'] = [mhz for start, end, mhz in samples
        if row['measure_start_unix_ns'] <= start <= end <= row['measure_end_unix_ns']]
    return row


def clock_summary(row):
    samples = row['clock_samples']
    if not samples:
        return '  측정 구간 클럭 샘플 없음 — 클럭당 처리량·이론값 비교 불가'
    mean = statistics.mean(samples)
    ops_per_clock = row['tera_ops_s'] * 1e6 / (row['sm'] * mean)
    text = (f'  SM 클럭 {min(samples)}..{max(samples)} MHz, 평균 {mean:.1f} MHz '
            f'({len(samples)}개 샘플), 약 {ops_per_clock:.1f} ops/SM/clock')
    if row['mode'] == 'int8':
        # GA10x dense INT8 Tensor Core rate; multiply + add counted as 2 ops.
        theoretical = row['sm'] * mean * 2048 / 1e6
        text += (f'\n  같은 평균 클럭의 dense INT8 이론값 {theoretical:.3f} TOPS, '
                 f'실측/이론 약 {row["tera_ops_s"] / theoretical * 100:.1f}%')
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=list(MODES))
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location('register_mma', ROOT / 'bench/mma/run.py')
    mma = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mma)
    print('레지스터 MMA 준비 중 (첫 실행은 CUDA 컴파일이 필요합니다)…', flush=True)
    mma.build()
    info = json.loads(subprocess.check_output([str(mma.BINARY), '--info'], text=True))
    if info['pci_bus'].lower() not in ('0000:01:00.0', '00000000:01:00.0'):
        raise SystemExit('CUDA device 0이 대상 GPU 0000:01:00.0이 아닙니다. 측정을 중단합니다.')
    print(f"GPU: {info['pci_bus']} / {info['sm']} SM / sm_86", flush=True)
    print('FP16/BF16/TF32는 FP32 누산, INT8은 INT32 누산. 모두 dense MMA.', flush=True)
    print('레지스터 입력 고정. 반복 구간 메모리 로드 없음; 마지막 결과 저장 포함.', flush=True)
    print('클럭·전력 설정 변경 없음. 결과 파일 저장 및 언락 판정 없음.\n', flush=True)
    print('형식   독립 체인   중앙값(ms)       처리량 / 단위   레지스터/스레드   최대 출력 오차', flush=True)
    for mode in args.modes:
        for chains in (1, 4, 8):
            row = measure([str(mma.BINARY), '--mode', mode, '--chains', str(chains)], info['pci_bus'])
            if row['local_bytes_per_thread']:
                raise SystemExit('로컬 메모리 사용이 검출됐습니다. 레지스터 전용 결과로 표시하지 않습니다.')
            print(f"{mode:4}   {chains:9}   {row['median_ms']:10.4f}   "
                  f"{row['tera_ops_s']:9.3f} {'TOPS' if mode == 'int8' else 'TFLOP/s':7} "
                  f"{row['registers_per_thread']:15}   "
                  f"{row['max_abs_error']:.3g}", flush=True)
            print(clock_summary(row), flush=True)
    print('\n측정 완료. 클럭이 자동으로 변하므로 서로 다른 실행의 수치는 달라질 수 있습니다.', flush=True)
    print('클럭당 처리량과 이론 대비 비율은 샘플 평균 기반 추정값입니다.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'벤치마크 오류: {error}')
