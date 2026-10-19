#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit administrator helper: preserve root args, enable only linux-cachyos.

Never called automatically by the GUI. No config files are sourced as shell.
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import shlex
import tempfile

PATTERN = re.compile(r'^\s*KERNEL_CMDLINE\[([^\]]+)\](\+?=)(.*)$')
WANTED = ('ga107_unlock.target=0000:01:00.0', 'ga107_unlock.execute=1', 'ga107_unlock.ss1_full=1')


def transform(text):
    values, selected = {}, []
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = PATTERN.match(line.rstrip('\n'))
        if not match:
            if 'KERNEL_CMDLINE' in line and not line.lstrip().startswith('#'):
                raise ValueError('지원하지 않는 KERNEL_CMDLINE 문법입니다. 수동 확인이 필요합니다.')
            continue
        key, operator, raw = match.groups()
        raw = raw.strip()
        if '\\' in raw:
            raise ValueError('이스케이프된 복잡한 인자는 수동 확인이 필요합니다.')
        parts = shlex.split(raw, comments=True, posix=True)
        if raw.startswith(('"', "'")):
            if len(parts) != 1:
                raise ValueError('지원하지 않는 복합 부팅 인자입니다.')
            value = parts[0]
        else:
            if any(c in raw for c in ('"', "'")):
                raise ValueError('인자 내부 따옴표는 수동 확인이 필요합니다.')
            value = ' '.join(parts)
        # The common config has one quoted literal or an unquoted kernel cmdline.
        # Reject shell expansion/operators rather than evaluating them as root.
        if any(c in value for c in ('$', '`', ';', '|', '&', '\n', '\r', '\\', '"', "'")):
            raise ValueError('복잡한 부팅 인자는 자동 변경하지 않습니다. sudoedit /etc/default/limine을 사용하세요.')
        values[key] = ((values.get(key, '') + ' ') if operator == '+=' else '') + value
        if key == 'linux-cachyos':
            selected.append(index)
    base = values.get('linux-cachyos') or values.get('default', '')
    tokens = base.split()
    if not any(t.startswith('root=') for t in tokens):
        raise ValueError('기존 root= 부팅 인자가 없어 자동 변경을 중단합니다.')
    tokens = [t for t in tokens if not t.startswith('ga107_unlock.')]
    updated = 'KERNEL_CMDLINE[linux-cachyos]="' + ' '.join(tokens + list(WANTED)) + '"\n'
    if selected:
        first = selected[0]
        return ''.join(updated if i == first else '' if i in selected else line
                       for i, line in enumerate(lines))
    return text.rstrip('\n') + '\n' + updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing or printing private args')
    args = parser.parse_args()
    path = Path('/etc/default/limine')
    original = path.read_text()
    updated = transform(original)
    if args.check:
        print('already configured' if original == updated else 'update required')
        return
    if os.geteuid() != 0:
        raise SystemExit('sudo로 명시적으로 실행해야 합니다.')
    if original == updated:
        print('일반 CachyOS의 언락 부팅 인자가 이미 설정돼 있습니다.')
        return
    backup = path.with_name(path.name + '.ga107-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    stat = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.ga107-', delete=False) as f:
            temporary = Path(f.name)
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, stat.st_mode & 0o777)
        os.replace(temporary, path)
        print('일반 CachyOS 부팅 인자 갱신 완료. 기존 설정 백업:', backup)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
