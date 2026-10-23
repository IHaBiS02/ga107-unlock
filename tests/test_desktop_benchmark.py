# SPDX-License-Identifier: GPL-2.0-only
"""Check output-only desktop execution without CUDA or GPU access."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import types
import unittest
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_benchmark', ROOT / 'tools/desktop/benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def run_benchmark(self, bus='0000:01:00.0', local=0):
        fake = types.SimpleNamespace(build=lambda: None, BINARY=Path('/fake/mma'))
        loader = types.SimpleNamespace(exec_module=lambda module: None)
        row = dict(local_bytes_per_thread=local, median_ms=1.25, tera_ops_s=12.5,
                   registers_per_thread=32, max_abs_error=0, clock_samples=[])
        with patch.object(benchmark.importlib.util, 'spec_from_file_location', return_value=types.SimpleNamespace(loader=loader)), \
             patch.object(benchmark.importlib.util, 'module_from_spec', return_value=fake), \
             patch.object(benchmark.subprocess, 'check_output', return_value=json.dumps(dict(pci_bus=bus, sm=16))), \
             patch.object(benchmark, 'measure', return_value=row) as run, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            benchmark.main([])
        return run.call_args_list, output.getvalue()

    def test_only_register_mma_cases_and_no_result_output_argument(self):
        calls, output = self.run_benchmark()
        self.assertEqual(len(calls), 12)
        cases = set()
        for call in calls:
            argv = call.args[0]
            self.assertEqual(argv[0], '/fake/mma')
            self.assertNotIn('--output', argv)
            cases.add((argv[2], argv[4]))
        self.assertEqual(cases, {(m, str(c)) for m in ('fp16', 'bf16', 'tf32', 'int8') for c in (1, 4, 8)})
        self.assertIn('12.500', output)
        self.assertIn('TOPS', output)
        self.assertIn('TFLOP/s', output)
        self.assertIn('측정 완료', output)

    def test_wrong_device_and_local_memory_refused(self):
        with self.assertRaisesRegex(SystemExit, '대상 GPU'):
            self.run_benchmark(bus='0000:02:00.0')
        with self.assertRaisesRegex(SystemExit, '로컬 메모리'):
            self.run_benchmark(local=16)

    def test_dense_int8_theory_at_observed_clock(self):
        row = dict(mode='int8', sm=20, tera_ops_s=67.1744, clock_samples=[1640, 1640])
        summary = benchmark.clock_summary(row)
        self.assertIn('2048.0 ops/SM/clock', summary)
        self.assertIn('67.174 TOPS', summary)
        self.assertIn('100.0%', summary)
        self.assertIn('비교 불가', benchmark.clock_summary(row | dict(clock_samples=[])))

    def test_clock_samples_exclude_warmup_and_boundary_crossings(self):
        samples = iter([(1, 9, 1000), (9, 11, 1200), (11, 19, 1640), (19, 21, 1800)])
        finished = threading.Event()
        def read_clock(bus):
            try:
                return next(samples)
            except StopIteration:
                finished.set()
                raise ValueError('done')
        def run(command, **kwargs):
            self.assertTrue(finished.wait(2))
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(
                dict(measure_start_unix_ns=10, measure_end_unix_ns=20)))
        with patch.object(benchmark, 'read_clock', side_effect=read_clock), \
             patch.object(benchmark.subprocess, 'run', side_effect=run):
            row = benchmark.measure(['/fake/mma'], '0000:01:00.0')
        self.assertEqual(row['clock_samples'], [1640])


if __name__ == '__main__':
    unittest.main()
