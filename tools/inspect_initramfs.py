#!/usr/bin/env python3
"""Print actual boot-loader configuration from newc/zstd initramfs; no extraction or execution."""
import argparse
import subprocess
from pathlib import Path

WANTED = {'etc/modules-load.d/MODULES.conf',
          'usr/lib/systemd/system/ga107-unlock.service',
          'usr/lib/systemd/system/sysinit.target.wants/ga107-unlock.service'}


def exact(stream, count):
    out = bytearray()
    while len(out) < count:
        part = stream.read(count-len(out))
        if not part:
            raise ValueError('Truncated CPIO archive')
        out.extend(part)
    return bytes(out)


def archive(stream):
    result = {}
    while True:
        hdr = exact(stream,110)
        if hdr[:6] not in (b'070701', b'070702'):
            raise ValueError('Expected newc CPIO header')
        size = int(hdr[54:62],16)
        namesize = int(hdr[94:102],16)
        if not 1 <= namesize <= 4096 or size > 1024**3:
            raise ValueError('Unreasonable CPIO member size')
        name = exact(stream,namesize).rstrip(b'\0').decode('utf-8')
        exact(stream,(-(110+namesize)) % 4)
        capture = name.removeprefix('./') in WANTED
        if capture and size > 65536:
            raise ValueError('Unexpected configuration size')
        if capture:
            result[name.removeprefix('./')] = exact(stream,size).decode('utf-8')
        else:
            left = size
            while left:
                chunk = exact(stream,min(left,65536))
                left -= len(chunk)
        exact(stream,(-size) % 4)
        if name == 'TRAILER!!!':
            return result


def inspect(path):
    result = {}
    with path.open('rb',buffering=0) as stream:
        while True:
            head = stream.read(6)
            if not head:
                break
            stream.seek(-len(head),1)
            if head[:1] == b'\0':
                # Padding between early CPIO and the main image.
                stream.read(1)
                continue
            if head in (b'070701',b'070702'):
                result.update(archive(stream))
                continue
            if head[:4] == b'\x28\xb5\x2f\xfd':
                with subprocess.Popen(['zstd','-dc'],stdin=stream,
                                      stdout=subprocess.PIPE,stderr=subprocess.PIPE) as proc:
                    try:
                        result.update(archive(proc.stdout))
                    except BaseException:
                        proc.kill()
                        proc.communicate()
                        raise
                    _, errors = proc.communicate()
                    if proc.returncode:
                        raise ValueError(errors.decode())
                break
            raise ValueError('Only uncompressed/newc and zstd images are supported')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    args = parser.parse_args()
    files = inspect(args.image)
    for name in sorted(WANTED):
        print(f'[{name}]')
        print(files.get(name,'MISSING'))
    modules = files.get('etc/modules-load.d/MODULES.conf','').splitlines()
    unit = files.get('usr/lib/systemd/system/ga107-unlock.service','')
    link = files.get('usr/lib/systemd/system/sysinit.target.wants/ga107-unlock.service','')
    passed = ('ga107_unlock' in modules and 'ga107_unlock?' not in modules and
              'Before=sysinit.target systemd-modules-load.service systemd-udevd.service systemd-udev-trigger.service' in unit and
              'ExecStart=/usr/bin/modprobe ga107_unlock' in unit and
              link == '../ga107-unlock.service')
    print('Boot ordering configuration:', 'PASS' if passed else 'NOT VERIFIED')
    raise SystemExit(0 if passed else 1)
