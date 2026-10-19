# 0.1.2: 선택적 SS1=0x8 실험

## 목적과 확인 범위

`0.1.1`에서 SS0만 변경했을 때 레지스터 MMA의 FP16/BF16 FP32 누산은 약 512 → 1024 ops/SM/clock으로 올라갔지만 TF32는 약 256으로 유지됐다. 이 버전은 원본 `gpu-unlock`이 쓰는 SS1=8을 별도로 시험할 수 있게 한다.

**SS1이 GA107의 TF32 필드라는 매핑은 확인되지 않았다.** 이는 TF32 해제를 보장하는 옵션이 아니다. 원본 역시 SS1의 성능 효과는 미검증이라고 명시한다. 근거: [원본 README](https://github.com/Zagitta/gpu-unlock#readme), [원본 selector 코드](https://github.com/Zagitta/gpu-unlock/blob/main/kernel/gpu_unlock/unlock_610.c).

## 동작

- 모듈 버전 `0.1.2-experimental`.
- 기본 `ss1_full=0`: 기존 SS0=0x88888888 정책을 사용하며 SS1은 진입 값을 보존한다.
- `ss1_full=1`: 기존 V67/pre-driver 경로에서 SS0 검증 성공 후 SS1에 0x8을 쓰고 readback을 확인한다. 이미 8이면 중복 쓰지 않는다.
- FLR 직전과 직후에 SS1을 선택한 정책의 기대값과 대조한다. 일치하지 않으면 실패로 보고한다.
- `ss1_full=1`만으로 실행되지 않는다. 기존의 정확한 target, execute=1, LG GA107 보드, unbound/cold 장치 검사가 그대로 필요하다.
- 불필요한 전체 GPU 상태 변경이나 실행 중 장치에 쓰는 경로는 추가하지 않았다. 펌웨어 자산은 0.1.1과 동일하다.

## 빌드·설치

저장소 최상위에서 실행한다. 현재 작업에서는 빌드와 모의 검사만 했으며 아래 시스템 설치 명령을 실행하지 않았다.

```bash
make module
modinfo -F version kernel/gpu_unlock/ga107_unlock.ko
modinfo -F vermagic kernel/gpu_unlock/ga107_unlock.ko
modinfo -p kernel/gpu_unlock/ga107_unlock.ko
```

버전이 `0.1.2-experimental`, vermagic가 부팅할 커널과 일치하고 `ss1_full` 파라미터가 있는지 확인한 뒤 설치한다.

```bash
sudo install -Dm644 kernel/gpu_unlock/ga107_unlock.ko \
    "/usr/lib/modules/$(uname -r)/extra/ga107_unlock.ko"
sudo depmod -a
modinfo -F version ga107_unlock
sudo limine-mkinitcpio
```

기존 펌웨어와 부팅 순서 훅은 재설치할 필요 없다. 새 `.ko`를 디스크에 설치해도 현재 로드된 모듈이 바뀌지는 않는다. `insmod`/unbind로 현재 부팅에서 다시 실행하지 않는다.

## 첫 cold boot 실험

최초에는 영구 설정에 추가하지 않고 Limine 편집 화면에서 해당 부팅에만 아래 인자를 사용한다. 기존 root 등의 정상 부팅 인자는 유지한다.

```text
ga107_unlock.target=0000:01:00.0 ga107_unlock.execute=1 ga107_unlock.ss1_full=1
```

진행 중인 작업을 저장하고 `sudo systemctl poweroff`로 완전히 종료한 뒤 켠다. warm reboot 경로는 지원하지 않는다.

부팅 후 다음을 확인한다.

```bash
cat /sys/module/ga107_unlock/version
cat /sys/module/ga107_unlock/parameters/ss1_full
sudo journalctl -k -b --no-pager -g 'ga107_unlock|SS1|selector|post-FLR|failure unlock_610'
nvidia-smi
```

버전 0.1.2, ss1_full=Y, `SS1 opt-in experiment`, SS1 selector readback과 post-FLR의 SS1=00000008, `SS0 applied and FLR completed` 및 NVIDIA 정상 초기화를 확인한다. 이 로그들은 SS1 적용 확인이며 TF32 성능 해제의 증명은 아니다.

## 855 MHz 마이크로벤치마크

앞서 보관한 `build/mma/on-855.json`은 SS0만 켠 결과다. 새 결과를 다른 이름으로 보관해 SS1의 효과를 분리한다. Python 환경과 CUDA 소스·컴파일러·드라이버는 양쪽에서 같게 유지한다. 가상환경이 없으면 [BUILD.md](BUILD.md)의 준비 절차를 따른다.

```bash
sudo nvidia-smi -i 00000000:01:00.0 --lock-gpu-clocks=855,855
.venv/bin/python bench/mma/run.py --label ss0-plus-ss1 --require-clock 855 \
    --output build/mma/on-ss1-855.json
sudo nvidia-smi -i 00000000:01:00.0 --reset-gpu-clocks
python3 bench/mma/compare.py build/mma/on-855.json build/mma/on-ss1-855.json \
    --baseline-label SS0 --candidate-label SS0+SS1
```

벤치마크가 실패해도 클럭 고정은 해제한다. TF32가 약 4.38 → 8.75 TFLOPS(20 SM, 855 MHz), 또는 256 → 512 ops/SM/clock으로 증가하는지 본다. FP16/BF16 유지·출력 검증도 함께 확인한다. 변화가 없으면 SS1만으로 해당 TF32 명령의 제한을 해제하지 못한 것이다. 값을 더 크게 만들거나 알려지지 않은 레지스터를 추가로 쓰는 식으로 대응하지 않는다.

## 원복

다음 cold boot에서 `ga107_unlock.ss1_full=1`을 제거하거나 `ga107_unlock.ss1_full=0`으로 바꾸면 SS0만 적용하는 기본 정책으로 돌아간다. 전체 언락 중단은 execute=0으로 한다. 현재 GPU에 SS1=7을 다시 쓰는 복구 명령은 제공하지 않는다.

실패 시 로그를 보존하고 같은 전원 주기에서 다시 실행하거나 강제 rmmod/PCI 리셋을 하지 않는다. 전원을 완전히 종료하고 ss1_full=0 또는 execute=0으로 복구한다. 영구 설정을 바꾸지 않았다면 첫 실험의 일회성 ss1_full 인자는 다음 부팅에서 사라진다.

## 검증

현재 커널 `7.2.11-1-cachyos`의 LLVM 모듈 빌드와 모의 테스트를 통과했다. 기존 61개에 8개를 추가한 69개 전체 거래 시나리오에서 기본 SS1 무쓰기, 실제 진입값 7→8, 이미 8인 경우, SS0/SS1 write 실패, FLR 전후 SS1 손실, 잘못된 정책의 하드웨어 접근 전 거절을 검사한다. 모듈 진입 테스트는 ss1_full만 켠 dry-run의 비실행과 바인딩된 장치 거절도 확인한다. 실제 SS1=8 GPU 실행과 TF32 개선은 아직 검증하지 않았다.
