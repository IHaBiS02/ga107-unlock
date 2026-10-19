# SPDX-License-Identifier: GPL-2.0-only
"""Read-only status collection and shell instructions; no GPU register access."""
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ('booter_load_ga102.bin', 'v67-ga102-610.43.03.bin',
            'gsp_ga10x.bin', 'gsp_boot_ga102.bin', 'gsp_boot_desc_ga102.bin')
TARGET = '0000:01:00.0'


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def command(args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, '', type(error).__name__


def evaluate(s):
    """Require current-boot completion evidence, selectors, params, and driver."""
    evidence = s['evidence']
    complete = 'SS0 applied and FLR completed' in evidence
    selector_lines = [line for line in evidence.splitlines() if 'post-FLR SEC2' in line]
    selectors = bool(selector_lines and re.search(
        r'SS0=88888888\s+SS1=00000008\b', selector_lines[-1]))
    failed = 'experiment failed' in evidence or 'failure unlock_610' in evidence
    applied = (s['loaded'] and s['execute'] == 'Y' and s['ss1_full'] == 'Y'
               and s['target'] == TARGET and complete and selectors
               and not failed and s['driver_ok'])
    reasons = []
    if not s['board_matches']:
        return 'unsupported', False, ['LG GA107 10de:25ab / 1854:052f 보드만 지원합니다.']
    if applied:
        if s['installed_version'] != s['source_version'] or s['loaded_version'] != s['source_version']:
            reasons.append('현재 부팅에는 적용됐습니다. 소스·설치·로드 버전이 달라 업데이트를 권장합니다.')
        return 'applied', True, reasons or ['이번 부팅에서 SS0·SS1 적용과 NVIDIA 정상 응답을 확인했습니다.']
    if failed:
        reasons.append('이번 부팅의 실험 실패 기록이 있습니다. 같은 부팅에서 재실행하지 마세요.')
    if not s['loaded']:
        reasons.append('현재 커널에 언락 모듈이 로드되지 않았습니다.')
    elif s['execute'] != 'Y':
        reasons.append('모듈이 비활성 모드(execute=0 또는 미지정)로 로드됐습니다.')
    elif s['ss1_full'] != 'Y':
        reasons.append('SS1 옵션이 활성화되지 않았습니다. SS0만 적용됐을 수 있습니다.')
    if s['installed_version'] != s['source_version']:
        reasons.append('현재 커널용 설치 모듈이 없거나 소스 버전과 다릅니다.')
    if not s['journal_ok']:
        reasons.append('현재 사용자가 커널 로그를 읽지 못해 실제 적용 여부를 확정할 수 없습니다.')
        return 'unknown', False, reasons
    if not complete or not selectors:
        reasons.append('SS0·SS1=8의 FLR 후 검증 및 완료 로그가 모두 확인되지 않습니다.')
    if not s['driver_ok']:
        reasons.append('NVIDIA 드라이버가 정상 응답하지 않습니다.')
    return 'inactive', False, reasons


def collect():
    kernel = command(['uname', '-r'])[1]
    source = read(ROOT / 'kernel/gpu_unlock/main.c')
    match = re.search(r'MODULE_VERSION\("([^"]+)"\)', source)
    module = Path('/sys/module/ga107_unlock')
    sysdev = Path('/sys/bus/pci/devices') / TARGET
    ids = [read(sysdev / key) for key in ('vendor', 'device', 'subsystem_vendor', 'subsystem_device')]
    rc, journal, err = command(['journalctl', '-k', '-b', '--no-pager', '-o', 'cat',
                              '-g', 'ga107_unlock:|SS1 preserved|SS1 opt-in experiment|pre-FLR selectors|post-FLR SEC2|failure unlock_610'])
    # -o cat strips host names. Never retain kernel cmdline/root UUIDs.
    evidence = '\n'.join(line for line in journal.splitlines()
                         if 'Command line:' not in line and 'Kernel command line:' not in line)[-24000:]
    _, installed, _ = command(['modinfo', '-k', kernel, '-F', 'version', 'ga107_unlock'])
    _, vermagic, _ = command(['modinfo', '-k', kernel, '-F', 'vermagic', 'ga107_unlock'])
    driver_rc, driver, _ = command(['nvidia-smi', '-i', TARGET,
        '--query-gpu=name,driver_version', '--format=csv,noheader'])
    access_rc, access_out, access_err = command(['journalctl', '-k', '-b', '-n', '1', '--no-pager', '-o', 'cat'])
    journal_access = access_rc == 0 and bool(access_out) and '-- No entries --' not in access_out
    s = dict(kernel=kernel, source_version=match[1] if match else '',
        loaded=module.is_dir(), loaded_version=read(module / 'version'),
        installed_version=installed, vermagic=vermagic,
        execute=read(module / 'parameters/execute'), ss1_full=read(module / 'parameters/ss1_full'),
        target=read(module / 'parameters/target'),
        board_matches=ids == ['0x10de', '0x25ab', '0x1854', '0x052f'],
        journal_ok=journal_access or (rc == 0 and bool(evidence)),
        evidence=evidence, driver_ok=driver_rc == 0, driver=driver,
        headers=Path(f'/usr/lib/modules/{kernel}/build').is_dir(),
        pkgbase=read(f'/usr/lib/modules/{kernel}/pkgbase'),
        missing_firmware=[name for name in FIRMWARE
                          if not (Path('/usr/lib/firmware/ga107-unlock/610.43.03') / name).is_file()])
    s['state'], s['applied'], s['reasons'] = evaluate(s)
    if s['missing_firmware']:
        s['reasons'].append('다음 부팅에 필요한 펌웨어 파일이 일부 누락됐습니다.')
    if s['applied'] and s['vermagic'].split()[:1] != [kernel]:
        s['reasons'].append('현재 적용은 확인됐지만 디스크 모듈의 커널 버전이 맞지 않습니다.')
    return s


def repair_commands(s, root=ROOT):
    if s['state'] == 'unsupported':
        return '# 이 장치는 자동 복구 명령 대상이 아닙니다.'
    if s['state'] == 'unknown':
        return "sudo journalctl -k -b --no-pager -g 'ga107_unlock:|SS1|post-FLR|failure unlock_610'\n# 로그를 확인한 다음 앱에서 다시 검사하세요."
    if s['pkgbase'] != 'linux-cachyos':
        return '# 현재 일반 linux-cachyos 커널이 아닙니다. 복구용 LTS 설정은 자동 변경하지 않습니다.\nuname -r'
    # Generate a bash script, then quote it for pasting from fish or bash.
    lines = ['set -euo pipefail', 'cd ' + shlex.quote(str(root)),
             'unlock_kver=$(uname -r)',
             'if [[ ! -d "/usr/lib/modules/$unlock_kver/build" ]]; then',
             '  sudo pacman -S --needed linux-cachyos-headers', 'fi',
             '[[ -d "/usr/lib/modules/$unlock_kver/build" ]] || { echo "현재 커널과 맞는 헤더가 필요합니다."; exit 1; }',
             'make module KDIR="/usr/lib/modules/$unlock_kver/build" LLVM=1',
             '[[ "$(modinfo -F vermagic kernel/gpu_unlock/ga107_unlock.ko)" == "$unlock_kver "* ]]',
             'modinfo -F version kernel/gpu_unlock/ga107_unlock.ko']
    if s['missing_firmware']:
        lines += ['python3 firmware/fetch_artifacts.py build/desktop-inputs',
                  'make prepare INPUTS="$PWD/build/desktop-inputs"',
                  'sudo install -dm755 /usr/lib/firmware/ga107-unlock/610.43.03',
                  'sudo install -m644 build/firmware/*.bin /usr/lib/firmware/ga107-unlock/610.43.03/',
                  'sudo install -dm755 /usr/share/licenses/ga107-unlock',
                  'sudo install -m644 build/firmware/NVIDIA-LICENSE licenses/*.txt firmware/NOTICE.md /usr/share/licenses/ga107-unlock/']
    lines += ['sudo install -Dm644 kernel/gpu_unlock/ga107_unlock.ko "/usr/lib/modules/$unlock_kver/extra/ga107_unlock.ko"',
              'sudo depmod -a "$unlock_kver"',
              'sudo install -Dm755 boot/ga107-order.install /etc/initcpio/install/ga107-order',
              'sudo install -Dm644 boot/zz-ga107-unlock.conf /etc/mkinitcpio.conf.d/zz-ga107-unlock.conf',
              'sudo /usr/bin/python3 tools/desktop/configure_boot.py',
              'sudo limine-mkinitcpio',
              'modinfo -k "$unlock_kver" -F version ga107_unlock',
              'echo "갱신 완료. 작업을 저장하고 완전히 종료했다가 켜세요. 현재 부팅에는 즉시 적용되지 않습니다."']
    # fish does not support heredocs: use bash -c with proper shell quoting.
    return 'bash -c ' + shlex.quote('\n'.join(lines)) + '\n'


def save_summary(s, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe = {k: s[k] for k in ('kernel', 'source_version', 'loaded_version', 'installed_version',
                              'state', 'applied', 'execute', 'ss1_full', 'reasons')}
    destination.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + '\n')
