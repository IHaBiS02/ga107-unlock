# CachyOS 업데이트와 언락 유지 메모

작성: 2026-10-19. 대상: LG GA107 RTX 3050 Laptop, 기준 실측은 `ga107_unlock` 0.1.1-experimental. 현재 소스는 0.1.2-experimental이며, 선택적 SS1 실험은 [SS1-EXPERIMENT.md](SS1-EXPERIMENT.md)를 따른다.

## 실사용 결과

사용자가 같은 시드·생성 설정으로 ComfyUI를 비교한 결과, OFF 125초에서 ON 99초로 줄었다. 시간은 20.8% 단축됐고 처리 속도는 26.3% 향상됐다. 반복 횟수와 단계별 시간은 기록하지 않아 TE·VAE 등의 기여를 확정할 수는 없다.

사용자의 855 MHz 고정 ON/OFF 비교에서는 BF16 FP32 누산이 약 8.63 → 11.62 TFLOPS(+35%), FP16 FP32 누산이 약 8.63 → 11.51 TFLOPS(+33%)였다. TF32는 약 4.31 TFLOPS로 변하지 않았다. 전체 생성 과정에는 개선되지 않는 작업도 포함되므로 ComfyUI 향상 폭이 더 작은 것은 이 결과와 양립한다. 완전한 2배 제한 해제를 확인한 것은 아니다.

## 업데이트의 영향

NVIDIA 드라이버 파일을 수정한 방식이 아니다. initramfs의 별도 `ga107_unlock` 모듈이 NVIDIA 초기화 전에 휘발성 SS0 설정을 적용하고 장치를 넘긴다. 전원을 껐다 켤 때마다 다시 적용하는 구조다.

| 변경 | 영향 |
|---|---|
| 커널 업데이트 | 현재 `.ko`는 커널 버전 전용이다. 새 커널 헤더로 빌드하고 새 커널의 모듈 경로에 설치해야 한다. 현재 DKMS 자동 재빌드 설정은 없다. |
| NVIDIA 드라이버 업데이트 | 별도 모듈을 직접 덮어쓰는 방식은 아니지만, 새 드라이버가 설정을 유지하고 정상 초기화되는지는 다시 확인해야 한다. |
| initramfs 재생성 | `zz-ga107-unlock.conf`는 대상 커널용 모듈을 찾으면 포함하고, 없으면 언락 모듈과 순서 훅을 제외한다. 커널 인자가 남아 있어도 모듈이 없으면 언락은 실행되지 않는다. |
| Limine 업데이트/재생성 | 영구 인자는 `/etc/default/limine`에서 관리한다. `/boot/limine.conf`만 직접 수정하면 재생성 때 사라질 수 있다. |

펌웨어는 `/usr/lib/firmware/ga107-unlock/610.43.03/`의 별도 고정 경로에 있다. 드라이버 버전이 바뀌었다고 이 폴더의 숫자를 새 버전으로 바꾸거나 다른 바이너리로 대체하지 않는다.

## 새 커널로 재빌드·설치

가능하면 업데이트 완료 후 재부팅하기 전에 새 커널용 모듈을 준비한다. 해당 커널의 헤더 패키지가 필요하다. 현재 일반 CachyOS 패키지 이름은 `linux-cachyos-headers`이며, 설치된 커널과 헤더의 버전이 맞아야 한다. 자동 빌드 실패 시 언락 없이 부팅한 후 준비할 수도 있다.

먼저 설치된 커널 디렉터리를 확인한다.

```bash
ls /usr/lib/modules
```

다음은 **bash에서 실행**하는 예다. fish에서는 먼저 `bash`를 실행한다. `unlock_kver`에는 부팅할 일반 CachyOS 커널의 정확한 버전을 넣는다. 아래 예시 버전을 새 커널 버전으로 바꾼다. 업데이트 직후 `uname -r`은 아직 실행 중인 이전 커널이므로 새 커널 선택에 사용하지 않는다.

```bash
cd /path/to/ga107-unlock
unlock_kver='7.2.9-2-cachyos'
test -d "/usr/lib/modules/$unlock_kver/build" || exit 1
make module KDIR="/usr/lib/modules/$unlock_kver/build" LLVM=1 || exit 1
modinfo -F vermagic kernel/gpu_unlock/ga107_unlock.ko
modinfo -F version kernel/gpu_unlock/ga107_unlock.ko
```

`vermagic` 선두가 선택한 커널 버전이고 현재 소스의 모듈 버전 `0.1.2-experimental`인지 확인한 뒤 설치한다. 빌드가 실패하거나 버전이 다르면 설치하지 않는다.

```bash
sudo install -Dm644 kernel/gpu_unlock/ga107_unlock.ko \
  "/usr/lib/modules/$unlock_kver/extra/ga107_unlock.ko"
sudo depmod -a "$unlock_kver"
modinfo -k "$unlock_kver" -F version ga107_unlock
sudo limine-mkinitcpio
```

이 절차는 디스크와 다음 부팅 이미지를 바꾼다. 현재 GPU에 재실행하거나 현재 로드된 모듈을 교체하지 않는다. 커널 API가 달라져 컴파일에 실패하면 소스 수정이 필요할 수 있다. 이전에 생성된 `.ko`를 새 커널 경로에 복사하거나 강제로 로드하지 않는다.

## 영구 부팅 인자와 적용 확인

이 장치의 `/etc/default/limine`에는 기존 default 줄을 유지하고 일반 커널용 줄을 추가한다.

```text
KERNEL_CMDLINE[linux-cachyos]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=REDACTED_UUID ga107_unlock.target=0000:01:00.0 ga107_unlock.execute=1"
```

위 UUID는 이 장치의 값이다. 다른 설치 환경에 복사하지 않는다. 인자만 수정했다면 `sudo limine-update`, 모듈을 교체했다면 `sudo limine-mkinitcpio`로 부팅 이미지를 갱신한다. LTS에는 실험 인자를 추가하지 않아 복구 경로로 남긴다.

현재 코드는 cold boot를 전제로 한다. 작업을 저장하고 `sudo systemctl poweroff`로 완전히 종료한 뒤 켠다. 단순 warm reboot의 동작은 검증하지 않았다.

부팅 후:

```bash
uname -r
cat /proc/cmdline
cat /sys/module/ga107_unlock/version
sudo journalctl -k -b --no-pager -g 'ga107_unlock'
nvidia-smi
```

`SS0 applied and FLR completed; benchmark required`와 NVIDIA 정상 초기화를 확인한다. 메시지는 부팅 중 설정 적용을 뜻하므로, 특히 드라이버 업데이트 후 실제 성능 유지 여부는 별도 측정한다. 파일이 없거나 로그에 실행 성공 메시지가 없으면 적용됐다고 간주하지 않는다.

비교 결과는 ON/OFF와 클럭을 구분한 파일명으로 보관한다. 기본 출력 파일과 같은 이름으로 복사하면 이전 결과가 덮어써진다. 측정 후 클럭 고정을 사용했다면 해제한다.

```bash
sudo nvidia-smi -i 00000000:01:00.0 --reset-gpu-clocks
```

## 실패하거나 중단할 때

Limine 편집 화면에서 해당 부팅만 `ga107_unlock.execute=0`으로 바꾸거나 인자가 없는 LTS로 부팅한다. 영구 중단은 `/etc/default/limine`의 일반 커널용 언락 줄을 삭제하고 `sudo limine-update`를 실행한다. 일반 커널은 기존 default 인자를 사용하게 된다.

실행 실패 후 같은 전원 주기에서 재실행·강제 모듈 제거·PCI 리셋을 하지 않는다. 작업을 저장하고 완전히 종료한 뒤 실행 인자를 끈 상태로 복구한다. 자세한 원복 절차는 [ADMIN.md](ADMIN.md)를 참고한다.
