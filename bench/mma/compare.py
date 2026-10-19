#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare matching register-MMA cases; reject changed code or mixed clocks."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('off', type=Path)
parser.add_argument('on', type=Path)
parser.add_argument('--baseline-label', default='OFF')
parser.add_argument('--candidate-label', default='ON')
args = parser.parse_args()
off, on = (json.loads(path.read_text()) for path in (args.off, args.on))
for field in ('schema', 'benchmark', 'gpu', 'sm', 'source_sha256', 'binary_sha256', 'driver', 'pci_bus'):
    if off.get(field) != on.get(field):
        raise SystemExit(f'{field} differs; rerun both states with the same code/compiler/driver/GPU')
fields = ('mode', 'chains', 'iterations', 'unroll', 'threads', 'blocks')
key = lambda row: tuple(row[f] for f in fields)
a = {key(r): r for r in off['rows']}
b = {key(r): r for r in on['rows']}
if not a or len(a) != len(off['rows']) or len(b) != len(on['rows']):
    raise SystemExit('Empty or duplicated cases')
if a.keys() != b.keys():
    raise SystemExit('Case sets differ or measurement is incomplete')
for k, r in a.items():
    s = b[k]
    if r.get('local_bytes_per_thread') != 0 or s.get('local_bytes_per_thread') != 0:
        raise SystemExit('Local memory detected; register-only comparison refused')
    if r.get('max_abs_error') != 0 or s.get('max_abs_error') != 0:
        raise SystemExit('Output correctness failed')
    clock = r.get('min_mhz')
    if clock is None or not (clock == r.get('max_mhz') == s.get('min_mhz') == s.get('max_mhz')):
        raise SystemExit(f'Case {k[:2]}: clocks are not fixed and identical')
print(f'mode chains  {args.baseline_label} T/s   {args.candidate_label} T/s  candidate/baseline   baseline ops/SM/clk  candidate ops/SM/clk')
for k, r in a.items():
    s = b[k]
    print(f"{r['mode']:4} {r['chains']:6} {r['tera_ops_s']:8.3f} {s['tera_ops_s']:8.3f} "
          f"{s['tera_ops_s']/r['tera_ops_s']:6.3f}x {r['ops_sm_clock']:15.1f} {s['ops_sm_clock']:14.1f}")
print('Compare the plateau across 4/8 chains; one chain can be latency limited. Labels are user supplied.')
