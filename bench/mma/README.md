# 레지스터 MMA 마이크로벤치마크 (GA10x / sm_86)

일반 cuBLAS GEMM에서 보인 약 33~35% 개선이 데이터 이동·커널 구성에 제한된 것인지 조사하는 도구다. `mma.sync`를 직접 실행하며, 반복 구간에는 전역/공유 메모리의 입력 로드가 없다. 입력은 레지스터에 유지하고 마지막에만 결과를 전역 메모리에 저장한다. FP32 누산을 사용하는 FP16·BF16 및 TF32와, INT32 누산을 사용하는 INT8을 지원한다. 일반 GEMM·ComfyUI 성능이나 GPU 전체의 절대 최대 성능을 보장하는 도구는 아니다.

## INT8 출력과 이론값

앱의 **레지스터 MMA 실행**에는 INT8도 포함된다. INT8만 결과 파일 없이 측정하려면:

```bash
python3 tools/desktop/benchmark.py --modes int8
```

명령은 고정된 INT8 레지스터 입력으로 dense `mma.sync.aligned.m16n8k32.row.col.s32.s8.s8.s32`를 실행하고 INT32로 누산한다. 모든 입력은 1이며 각 출력의 정확한 기대값은 `iterations × 8 × 32`이다. 기본값에서는 2,097,152이고 최대 허용 반복 수도 INT32 오버플로가 나지 않는다. 최종 출력 전체를 검사한다.

GA10x의 스펙상 dense INT8 처리량은 SM당 클럭당 2048 정수 연산이다(곱셈·덧셈을 각각 1연산). 20 SM이면 `40.96 × SM 클럭(GHz)` TOPS다. 예를 들어 855 MHz에서 35.021 TOPS, 1640 MHz에서 67.174 TOPS다. 2:4 구조적 희소성을 사용하는 스펙 수치는 두 배지만 이 테스트는 dense이므로 희소성 수치와 비교하지 않는다. 근거: [NVIDIA GA10x 백서, Tensor Cores 절](https://www.nvidia.com/content/PDF/nvidia-ampere-ga-102-gpu-architecture-whitepaper-v2.1.pdf).

출력에는 `nvidia-smi`로 샘플링한 측정 구간 SM 클럭과, 그 평균을 기준으로 계산한 이론값·실측 비율이 포함된다. 샘플이 없으면 비율을 계산하지 않는다. 현재 상태의 이론값 도달 여부만으로 언락 전후 차이를 입증할 수 없으며, 효과 비교는 같은 클럭에서 ON/OFF로 측정해야 한다.

기존 JSON/NVML 실행기는 `--modes int8`로 선택할 수 있다. 기존 기본 모드(FP16·BF16·TF32)는 유지한다. 소스가 바뀌어 실행 파일 해시도 바뀌므로 기존 ON/OFF JSON과 새 실행 결과를 엄격 비교하려면 양쪽을 새 바이너리로 다시 측정해야 한다.

## 준비

CUDA Toolkit의 `nvcc`가 PATH에 있어야 한다. 빌드 아키텍처는 `sm_86`이며 다른 compute capability의 장치는 거절한다. Python 측은 표준 라이브러리와 `nvidia-ml-py`만 사용한다. PyTorch는 필요 없다.

저장소 최상위에서 실행한다. 기존 가상환경을 사용해도 되며, 새로 만들려면:

```bash
uv venv .venv
uv pip install --python .venv/bin/python nvidia-ml-py
```

컴파일만 할 때는 가상환경·GPU 없이 다음 명령을 사용한다.

```bash
python3 bench/mma/run.py --build-only
```

컴파일된 실행 파일, ptxas 보고서와 해시는 `build/`에 저장돼 Git에서 제외된다. 코드·컴파일러가 같으면 같은 실행 파일을 재사용한다. ON/OFF 사이에 코드나 컴파일러를 바꾸지 않는다.

## 같은 855 MHz에서 ON/OFF 측정

이 스크립트는 언락 실행, 클럭·전력 변경, 드라이버 언바인딩을 하지 않는다. 상태 변경과 부팅은 기존 ADMIN 절차를 따른다. 드라이버가 초기화된 현재 부팅에서 언락 모듈을 다시 실행하지 않는다.

1. 언락이 적용된 cold boot에서 실행 성공 로그를 확인한다. 같은 충전·전원 모드에서 다른 GPU 작업을 종료한다.
2. GPU 클럭을 고정하고 ON 결과를 저장한다.

```bash
sudo nvidia-smi -i 00000000:01:00.0 --lock-gpu-clocks=855,855
.venv/bin/python bench/mma/run.py --label on --require-clock 855 --output build/mma/on-855.json
sudo nvidia-smi -i 00000000:01:00.0 --reset-gpu-clocks
```

3. 부팅 인자를 `ga107_unlock.execute=0`으로 바꾸고 완전히 종료했다가 켠다. 같은 클럭으로 OFF를 측정한다.

```bash
sudo nvidia-smi -i 00000000:01:00.0 --lock-gpu-clocks=855,855
.venv/bin/python bench/mma/run.py --label off --require-clock 855 --output build/mma/off-855.json
sudo nvidia-smi -i 00000000:01:00.0 --reset-gpu-clocks
```

4. 결과를 비교한다.

```bash
python3 bench/mma/compare.py build/mma/off-855.json build/mma/on-855.json
```

스크립트가 실패하거나 Ctrl+C로 중단되더라도 클럭 해제 명령은 실행한다. `--label`은 사용자가 선언한 상태다. 모듈 파라미터가 Y라고 실제 실행이 성공했다는 의미는 아니므로 커널 로그로 적용 여부를 확인한다. JSON에는 모듈 버전과 execute 파라미터만 기록하고 원시 부팅 인자·UUID·호스트명은 저장하지 않는다.

기존 `rtx3050-gram-pro/bench-venv`를 사용한다면 `.venv/bin/python` 대신 해당 환경의 Python을 사용한다.

## 설계와 결과 해석

- FP16/BF16: dense `mma.sync.aligned.m16n8k16.row.col.f32.*.*.f32`.
- TF32: dense `mma.sync.aligned.m16n8k8.row.col.f32.tf32.tf32.f32`.
- 부동소수점 입력은 모두 정확히 표현되는 2^-8이다. 결과의 모든 원소·스레드·독립 누산 체인을 `반복 수 × 8 × K / 65536`의 정확한 기대값과 대조한다. INT8의 기대값은 위 절을 참고한다. 0 오차만 허용한다. 이는 균일한 입력의 명령 실행 검사이며 임의 행렬의 정확도 검사는 아니다.
- 기본적으로 1·4·8개 독립 누산 체인을 비교한다. 1체인은 의존성 지연에 제한될 수 있으므로 4·8체인에서 처리량이 평탄해지는지 확인한다. 루프는 8번 펼치며, 워프 MMA 하나의 연산 수는 `2 × 16 × 8 × K`이다. FMA는 2연산으로 센다.
- 각 케이스는 같은 커널로 GPU 이벤트 시간 300ms 이상 예열하고 7회 측정의 중앙값을 기록한다. CUDA 이벤트는 GPU 전체 launch 완료 시간을 측정하며 초기화·컴파일·호스트 결과 검사는 제외한다. 종료 시 결과 저장과 launch 오버헤드는 포함돼 있다.
- NVML은 실제 측정 구간의 SM/메모리 클럭·전력·온도를 기록한다. `--require-clock 855`는 샘플이 없거나 고정 클럭과 다르면 부분 결과를 저장하고 중단한다. NVML 샘플링은 모든 순간의 클럭을 보장하지는 않는다.
- 레지스터 수·로컬 메모리 사용량·계산상 최대 상주 블록 수도 기록한다. 로컬 메모리가 발생하면 중단한다. `build/mma-build.log`의 spill 정보와 실제 SASS도 함께 확인한다.
- `ops/SM/clock`은 GPU 전체 처리량을 SM 수와 샘플 평균 클럭으로 나눈 추정치다. 비교 도구는 동일 코드·바이너리·드라이버·GPU/PCI 위치·케이스와 양쪽의 동일 고정 클럭을 요구한다. 다른 소프트웨어 환경의 결과를 무리하게 비교하지 않는다.

ON에서 약 2배에 가까워지고 일반 GEMM은 약 1.35배에 그친다면 GEMM의 다른 병목을 의심할 근거가 된다. 이 도구에서도 약 1.35배라면 남은 하드웨어 제한뿐 아니라 명령 의존성·발행·스케줄링도 후보이므로 곧바로 부분 언락이라고 단정하지 않는다.

상주 워프 수의 영향을 보려면 양쪽 모두 같은 옵션으로 다시 측정한다. 기존 파일과 다른 이름을 사용한다.

```bash
.venv/bin/python bench/mma/run.py --label on --threads 256 --blocks-per-sm 16 --require-clock 855 --output build/mma/on-855-w8.json
```

더 긴 측정은 `--iterations 16384 --repeats 9`를 사용할 수 있다. 옵션은 양쪽에서 같아야 한다. 짧은 검증 실행은 `--iterations 2048 --repeats 3`으로 가능하나 클럭 샘플이 부족할 수 있다.

## 명령어 확인

```bash
cuobjdump --dump-sass build/mma-register > build/mma-register.sass
```

각 함수에서 `HMMA`를 확인하고 반복 구간에 `LDL`/`STL` 같은 spill 접근이나 전역/공유 메모리 로드가 없는지 점검한다. 최종 결과의 `STG` 저장은 정상이다. 빌드 시 ptxas의 `0 bytes spill stores, 0 bytes spill loads`도 확인한다.

명령 형식과 fragment 배치는 [NVIDIA PTX ISA](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)의 warp-level MMA 정의를 따른다.
