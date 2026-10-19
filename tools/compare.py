#!/usr/bin/env python3
"""Compare repeated GEMM medians, both raw and normalized by sampled clocks."""
import argparse
import json
import statistics
from collections import defaultdict

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline')
parser.add_argument('after')
args = parser.parse_args()


def load(path):
    with open(path) as stream:
        report = json.load(stream)
    rows = defaultdict(list)
    for rnd in report['rounds']:
        for row in rnd:
            rows[(row['mode'], row['n'])].append(row)
    return report, rows


before, old = load(args.baseline)
after, new = load(args.after)
if before['gpu'] != after['gpu'] or before['sm'] != after['sm']:
    raise SystemExit('GPU/SM mismatch: results are not comparable')
print('mode                     raw ratio  ops/SM/clock ratio  clock min..max after')
for key, rows in old.items():
    if key not in new:
        continue
    current = new[key]
    ratio = statistics.median(r['tera_ops_s'] for r in current)/statistics.median(r['tera_ops_s'] for r in rows)
    norm = statistics.median(r['ops_sm_clock'] for r in current)/statistics.median(r['ops_sm_clock'] for r in rows)
    print(f'{key[0]:24} {ratio:7.3f}x {norm:17.3f}x  '
          f'{min(r["min_mhz"] for r in current)}..{max(r["max_mhz"] for r in current)} MHz')
print('Clock-normalized ratios are estimates when clocks vary. A ratio alone does not prove correctness.')
