#!/usr/bin/env python3
"""Read sysfs/configuration status only; never unbind, reset, mmap or load firmware."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target', default='0000:01:00.0')
args = parser.parse_args()
if '/' in args.target or '..' in args.target:
    parser.error('Expected a full PCI address')
root = Path('/sys/bus/pci/devices')/args.target
report = {'target':args.target, 'checks':{}, 'writes_performed':False}
for name in ['vendor','device','subsystem_vendor','subsystem_device','reset_method']:
    try:
        report['checks'][name] = (root/name).read_text().strip()
    except OSError as error:
        report['checks'][name] = {'error':str(error)}
driver = root/'driver'
report['driver'] = driver.resolve().name if driver.is_symlink() else None
expected = dict(vendor='0x10de',device='0x25ab',subsystem_vendor='0x1854',subsystem_device='0x052f')
report['board_matches'] = all(report['checks'].get(k)==v for k,v in expected.items())
reset = report['checks'].get('reset_method')
report['flr_advertised'] = isinstance(reset,str) and 'flr' in reset.split()
report['ready_for_pre_driver_attempt'] = report['board_matches'] and report['flr_advertised'] and report['driver'] is None
report['note'] = 'An unbound device alone is not proof of a cold card. Current NVIDIA binding is expected during desktop use.'
try:
    out = subprocess.run(['nvidia-smi','--query-gpu=name,pci.bus_id,driver_version,vbios_version',
                          '--format=csv'],capture_output=True,text=True,timeout=10)
    report['nvidia_smi'] = {'returncode':out.returncode,'stdout':out.stdout,'stderr':out.stderr}
except (OSError,subprocess.TimeoutExpired) as error:
    report['nvidia_smi'] = {'error':str(error)}
print(json.dumps(report,indent=2))
