# 관리자 명령 메모 — 실행하지 않은 명령

작성된 코드는 실험 포트이며 GA107에서 성공을 확인한 릴리스가 아니다. 아래 설치·모듈 로드·부팅 변경 명령은 사용자가 실행할 때만 적용된다. 현재 켜진 GPU를 unbind하거나 플래시하는 절차는 포함하지 않는다.

`0.1.0` 실행 후 BAR 자원이 유지돼 NVIDIA 초기화가 실패한 상태라면 먼저 `ga107_unlock.execute=0` 또는 실험 인자를 제거한 cold boot로 복구한다. `rmmod -f`, PCI 리셋, 재삽입으로 현재 부팅에서 강제 복구하지 않는다. `0.1.1`은 이 실패의 정렬/자원 관리 버그를 고쳤으나 새 실험 전에 정상 NVIDIA 복구부터 확인한다. 상세는 [INCIDENT-2026-10-19.md](INCIDENT-2026-10-19.md).

## 기존 사용자: 정상 복구 후 현재 모듈 교체

먼저 실행 인자를 끈 상태로 전원을 껐다 켜고 `nvidia-smi`가 정상 동작하는지 확인한다. 아래 명령은 디스크와 다음 부팅 이미지의 모듈만 교체하며 현재 로드된 모듈을 교체하지 않는다. 이미 설치한 펌웨어와 부팅 순서 훅은 그대로 사용한다.

```bash
cd /path/to/ga107-unlock
make module
modinfo -F version kernel/gpu_unlock/ga107_unlock.ko
sudo install -Dm644 kernel/gpu_unlock/ga107_unlock.ko \
  "/usr/lib/modules/$(uname -r)/extra/ga107_unlock.ko"
sudo depmod -a
modinfo -F version ga107_unlock
sudo limine-mkinitcpio
sudo python3 tools/inspect_initramfs.py \
  /boot/MACHINE_ID/linux-cachyos/initramfs
```

두 버전 출력은 현재 소스의 `0.1.2-experimental`이어야 한다. 이미지 검사의 PASS는 부팅 순서 확인이며 모듈 버전이나 GPU 성공 검증은 아니다. 다음 부팅도 우선 `ga107_unlock.execute=0`으로 확인하고, 실제 실행은 아래 cold boot 실험 절차를 따른다. 0.1.1에서 기존 SS0 경로의 실제 실행은 확인했다. 0.1.2의 선택적 SS1 실험은 [SS1-EXPERIMENT.md](SS1-EXPERIMENT.md)를 따른다.

## 1. 먼저 일반 사용자로 빌드

```bash
cd /path/to/ga107-unlock
make
make preflight
modinfo kernel/gpu_unlock/ga107_unlock.ko
```

현재 커널과 vermagic가 같아야 한다. 현재 작업에서 빌드한 `.ko`는 `7.2.11-1-cachyos`용이다. 커널이 바뀌면 다시 빌드해야 한다. 모듈 서명 강제 환경이라면 로컬 서명/등록이 별도로 필요하며 이 폴더는 Secure Boot 설정을 바꾸지 않는다.

## 2. 선택 사항: 실행하지 않는 모드 확인

이 명령은 모듈을 로드하지만 `execute=0`이므로 NVIDIA가 바인딩한 상태에서도 자산 요청·MMIO를 하지 않는다. 출력은 커널 로그에서 확인한다.

```bash
sudo insmod kernel/gpu_unlock/ga107_unlock.ko target=0000:01:00.0 execute=0
sudo journalctl -k -b -g 'ga107_unlock'
sudo rmmod ga107_unlock
```

아무 옵션 없이 로드해도 비활성이다. 성공 메시지가 아닌 `matched; execute=0, no firmware request or MMIO`가 정상이다. **이 dry-run조차 이번 작업에서 실행하지 않았다.**

## 3. 실제 실험을 위한 파일 설치

아래는 관리자 권한이 필요한 파일 복사와 모듈 의존성 목록 갱신이다. NVIDIA 드라이버 파일은 교체하지 않는다. 별도의 610.43.03 펌웨어를 이 실험용 경로에만 설치한다.

```bash
sudo install -Dm644 kernel/gpu_unlock/ga107_unlock.ko \
  "/usr/lib/modules/$(uname -r)/extra/ga107_unlock.ko"
sudo install -dm755 /usr/lib/firmware/ga107-unlock/610.43.03
sudo install -m644 build/firmware/*.bin /usr/lib/firmware/ga107-unlock/610.43.03/
sudo install -dm755 /usr/share/licenses/ga107-unlock
sudo install -m644 build/firmware/NVIDIA-LICENSE licenses/*.txt firmware/NOTICE.md \
  /usr/share/licenses/ga107-unlock/
sudo depmod -a
```

## 4. CachyOS mkinitcpio에서 NVIDIA보다 먼저 배치

작성 당시 `/etc/mkinitcpio.conf.d/10-chwd.conf`에 NVIDIA 모듈들이 들어 있다. 제공한 drop-in은 해당 커널용 모듈이 설치돼 있는 경우에만 `ga107_unlock`을 추가하고, systemd 이미지에는 `ga107-order` 훅을 추가한다. 훅이 만드는 initrd 전용 서비스는 `systemd-modules-load`, `systemd-udevd`, `systemd-udev-trigger`보다 먼저 완료된다. systemd 262는 모듈을 병렬 로드하므로 MODULES 나열 순서만으로는 부족하다. 모듈이 없는 LTS는 제외한다.

초기 설정의 `ga107_unlock?`는 수정했다. `?`가 systemd의 런타임 MODULES.conf에 남으면 모듈 이름으로 처리돼 로딩이 실패할 수 있다. **이전 설정을 설치했다면 아래 두 파일을 다시 설치하고 initramfs를 재생성해야 한다.** 이 설명은 부팅 순서 설정 변경에 한정한다. 모듈 소스 버전을 바꿀 때에는 위 교체 절차대로 커널 모듈도 재설치해야 한다.

```bash
sudo install -Dm755 boot/ga107-order.install /etc/initcpio/install/ga107-order
sudo install -Dm644 boot/zz-ga107-unlock.conf \
  /etc/mkinitcpio.conf.d/zz-ga107-unlock.conf
sudo limine-mkinitcpio
```

위 명령은 현재 장치의 Limine 부팅 이미지까지 갱신한다. 다른 부트로더에서는 해당 환경의 initramfs 생성 명령을 쓴다. `mkinitcpio -c` 또는 preset `_config`로 다른 설정을 쓰면 drop-in이 무시될 수 있다. 생성 로그에서 일반 커널 이미지에 `[ga107-order]` 훅이 실행됐는지 확인한다. `modinfo -F firmware kernel/gpu_unlock/ga107_unlock.ko`로 필요한 펌웨어 경로를 볼 수 있다. 기존 정상 부팅 항목과 복구 가능한 initramfs를 확보한 상태에서 실험한다.

실제 이미지의 런타임 설정은 다음 명령으로 확인한다. `lsinitcpio -c`는 buildconfig 원문만 출력하므로 최종 MODULES 배열을 보여주지 않는다. 이 Python 도구는 이미지를 읽기·압축 해제하여 필요한 설정 문자열만 출력하며 파일 추출이나 설정 실행을 하지 않는다.

```bash
sudo python3 tools/inspect_initramfs.py \
  /boot/MACHINE_ID/linux-cachyos/initramfs
```

마지막 `Boot ordering configuration: PASS`를 확인한다. 이는 이미지 안 설정의 검사이며 실제 부팅 성공을 보장하는 것은 아니다.

## 5. cold boot 한 번만 실행

기존 부팅 설정에 영구 옵션을 쓰지 말고, **전원을 완전히 끈 다음 부트로더의 해당 부팅 항목 편집 화면에서 한 번만** 다음 커널 인자를 추가한다.

```text
ga107_unlock.target=0000:01:00.0 ga107_unlock.execute=1
```

종료 명령은 다음과 같다. 진행 중인 작업은 먼저 저장한다.

```bash
sudo systemctl poweroff
```

warm reboot는 지원하지 않는다. 노트북은 종료나 충전기 분리만으로 GPU 전원이 반드시 끊겼다고 보장할 수 없다. cold 상태가 아니면 코드가 WPR2/PLM 검사에서 거절하도록 했지만 이 검사가 모든 전원 상태를 증명하지는 않는다. 필요한 경우 제조사가 안내한 전원 초기화 방법을 따른다. GPU가 부팅 후 한 번이라도 드라이버로 초기화됐다면 unbind해 재시도하지 않는다.

## 6. 적용 후 로그와 처리량

```bash
sudo journalctl -k -b --no-pager -o short-monotonic > boot-kernel.log
rg '0000:01:00.0|ga107_unlock|gpu_unlock|NVRM' boot-kernel.log
lspci -Dnnk -s 0000:01:00.0
nvidia-smi
.venv/bin/python -u bench/bench_extended.py
python tools/compare.py bench/baseline-2026-10-19.json bench/bench-extended-results.json
```

`SS0 applied and FLR completed; benchmark required`는 설정과 리셋 단계가 끝났다는 뜻이다. BF16/FP16-FP32 누산·TF32 처리량이 실제로 증가하고 수치 검사도 통과해야 성능 해제 성공으로 판단한다. 전력 한도 때문에 실사용 속도가 2배가 되지 않을 수 있다. SS1 보존 여부도 로그에서 확인한다.

실패·DMA 버퍼 유지·GPU 응답 중단 시 같은 전원 주기에서 재실행하지 않는다. 모듈이 DMA 버퍼를 유지하는 경우 강제 `rmmod -f`를 사용하지 않는다. 다음 부팅에서는 실행 인자를 제거하고 전원을 완전히 끈 뒤 복구한다. ROM에서 FWSEC-FRTS를 찾지 못하면 로그를 보존한다. 이 포트에는 ACPI VBIOS 자동 추출이나 타 보드 ROM 대입 기능이 없다.

## 7. 중단·원복

부트로더에서 두 실험 인자를 지우거나 `ga107_unlock.execute=0`으로 부팅하면 펌웨어를 실행하지 않는다. 화면 문제로 정상 진입이 안 되면 이 인자가 없는 정상 부팅 항목/복구 환경을 사용한다. SS0의 휘발성 상태 초기화를 위해 전원 완전 차단이 필요할 수 있다.

아래 명령은 이 폴더에서 설치한 drop-in과 모듈만 제거한다. 현재 실행 중인 실험 상태가 즉시 원복되는 명령은 아니다.

```bash
sudo rm -f /etc/mkinitcpio.conf.d/zz-ga107-unlock.conf
sudo rm -f /etc/initcpio/install/ga107-order
sudo rm -f "/usr/lib/modules/$(uname -r)/extra/ga107_unlock.ko"
sudo depmod -a
sudo limine-mkinitcpio
```

다른 커널용으로도 설치했다면 해당 커널의 `extra/ga107_unlock.ko`도 별도로 제거한다. 전용 펌웨어와 라이선스 디렉터리는 비활성 파일로 남겨도 실행되지 않는다.

업데이트 후 유지·새 커널 재빌드·영구 부팅 설정과 ComfyUI 실측은 [UPDATE-NOTES.md](UPDATE-NOTES.md)에 정리했다.

0.1.2의 선택적 SS1=8 부팅 인자·설치·측정·원복은 [SS1-EXPERIMENT.md](SS1-EXPERIMENT.md)에 있다. 기본값에서는 SS1을 보존한다.
