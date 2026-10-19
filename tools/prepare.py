#!/usr/bin/env python3
"""Verify local inputs, extract pinned assets, and record offline evidence.

No downloads, installation, GPU access, or execution of extracted binaries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=ROOT.parent/'audit-inputs')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'firmware/artifacts-610.43.03.json').read_text())
    inputs = {}
    for item in manifest['source_artifacts']:
        if 'filename' not in item:
            continue
        path = args.inputs/item['filename']
        actual = digest(path)
        if actual != item['sha256']:
            raise SystemExit(f'Input SHA-256 mismatch: {path}')
        inputs[item['filename']] = actual
        print(f'Input SHA-256 OK: {path.name}', flush=True)
    source_parent = ROOT/'research/source'
    source_parent.mkdir(parents=True, exist_ok=True)
    source_name = 'NVIDIA-kernel-module-source-610.43.03'
    with tarfile.open(args.inputs/(source_name+'.tar.xz')) as archive:
        archive.extractall(source_parent, filter='data')
    source = source_parent/source_name
    assets = ROOT/'build/firmware'
    for script, path in [('generate_v67.py', args.inputs/'nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst'),
                         ('extract_boot_assets.py', source)]:
        subprocess.run([sys.executable, str(ROOT/'firmware'/script), str(path), str(assets)], check=True)

    hal_path = source/'src/nvidia/generated/g_kernel_gsp_nvoc.c'
    hal = hal_path.read_text()
    findings = []
    for name, symbol in [('kgspGetBinArchiveBooterLoadUcode', 'kgspGetBinArchiveBooterLoadUcode_GA102'),
                         ('kgspGetBinArchiveBooterUnloadUcode', 'kgspGetBinArchiveBooterUnloadUcode_GA102'),
                         ('kgspGetBinArchiveGspRmBoot', 'kgspGetBinArchiveGspRmBoot_GA102'),
                         ('kgspGetPrescrubbedTopFbSize', 'kgspGetPrescrubbedTopFbSize_13afc5'),
                         ('kgspGetMinWprHeapSizeMB', 'kgspGetMinWprHeapSizeMB_d2c3c5')]:
        start = hal.index('// '+name+' --')
        end = hal.find('\n    // ', start+5)
        block = hal[start:end if end != -1 else len(hal)]
        pos = block.index('= &'+symbol+';')
        # ChipHal selection comment directly preceding this assignment.
        comment = block[max(0, pos-500):pos]
        if 'GA107' not in comment:
            raise SystemExit(f'GA107 dispatch evidence missing: {name}')
        findings.append(dict(method=name, implementation=symbol,
                             source=str(hal_path.relative_to(ROOT)),
                             line=hal[:start+pos].count('\n')+1))
    bundle = (assets/'booter_load_ga102.bin').read_bytes()
    fields = struct.unpack('<18I', bundle[:72])
    # Wire format: magic/version, 14 descriptor values, image/signature sizes.
    report = dict(status='offline-assets-verified; GA107 hardware execution untested',
                  inputs=inputs, dispatch=findings,
                  booter=dict(ucode_id=fields[12], engine_mask=fields[13],
                              num_signatures=fields[14], signature_bytes=fields[15],
                              image_bytes=fields[16], bundle_signature_bytes=fields[17]),
                  output_sha256={p.name:digest(p) for p in sorted(assets.iterdir()) if p.is_file()},
                  unresolved=['GA107 physical BootROM/fuse acceptance',
                              'board PROM contains parseable FWSEC-FRTS',
                              'GA107 SS0 effect and preservation through FLR',
                              'post-FLR handoff to installed NVIDIA 615.78.08',
                              'per-operation SS0 bit mapping not established'])
    (ROOT/'build/offline-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Assets and GA107 HAL evidence recorded in build/offline-audit.json')


if __name__ == '__main__':
    main()
