#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install per-user launchers/autostart only; never changes system boot/GPU."""
import argparse
import os
from pathlib import Path
import subprocess

APP = Path(__file__).with_name('app.py').resolve()


def exec_quote(value):
    value = str(value).replace('%', '%%')
    # Desktop Entry value escaping is applied before Exec argument quoting.
    for old, new in [('\\', '\\\\\\\\'), ('"', '\\\\"'), ('`', '\\\\`'), ('$', '\\\\$')]:
        value = value.replace(old, new)
    return '"' + value + '"'


def desktop_entry(startup=False):
    command = '/usr/bin/python3 ' + exec_quote(APP) + (' --startup' if startup else '')
    return ('[Desktop Entry]\nType=Application\nVersion=1.0\n'
        'Name=GA107 Unlock Check\nName[ko]=GA107 언락 확인\n'
        'Comment=Check this boot and show repair commands when needed\n'
        'Comment[ko]=현재 커널의 SS0·SS1 적용 검사 및 업데이트 명령 안내\n'
        'Exec=' + command + '\nIcon=utilities-system-monitor\nTerminal=false\n'
        'StartupNotify=false\nCategories=System;\n'
        + ('X-GNOME-Autostart-enabled=true\n' if startup else ''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("sudo 없이 일반 사용자로 실행하세요.")
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    paths = [(data / 'applications/ga107-unlock-check.desktop', False),
             (config / 'autostart/ga107-unlock-check.desktop', True)]
    try:
        desktop = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        desktop = str(home / 'Desktop')
    if desktop and Path(desktop).is_dir() and Path(desktop) != home:
        paths.append((Path(desktop) / 'ga107-unlock-check.desktop', False))
    for path, startup in paths:
        if args.uninstall:
            path.unlink(missing_ok=True)
            print('Removed:', path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desktop_entry(startup))
            path.chmod(0o755)
            print('Installed:', path)


if __name__ == '__main__':
    main()
