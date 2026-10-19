# 소스에서 빌드하기

이 저장소는 모듈 소스·펌웨어 추출기·고정 입력 해시·모의 테스트·부팅 훅을 포함한다. 부팅 로그, 컴파일 산출물, NVIDIA 원본 아카이브 및 생성된 펌웨어는 포함하지 않는다. 모든 생성 작업은 로컬에서 수행한다.

## 준비

Python 3.14 이상, make, clang/LLVM, C 컴파일러, zstd와 대상 커널의 헤더가 필요하다. CachyOS 일반 커널에서는 해당 커널과 버전이 맞는 `linux-cachyos-headers`를 준비한다. 커널 패키지가 다르면 그 커널의 헤더를 사용한다. 테스트에 필요한 `systemd-analyze` 등 systemd 도구도 필요하다.

이 문서의 명령은 저장소 최상위 디렉터리에서 실행한다. 소스 디렉터리 이름이나 사용자 홈 경로에는 의존하지 않는다.

## 입력 다운로드 또는 기존 입력 사용

고정된 NVIDIA 소스와 nvidia-utils 패키지를 내려받고 SHA-256을 검사한다. 다운로드한 코드는 실행하지 않는다. URL·파일명·해시·라이선스는 `firmware/artifacts-610.43.03.json`에 있다.

```bash
python3 firmware/fetch_artifacts.py audit-inputs
```

네트워크 없이 캐시를 검사하려면:

```bash
python3 firmware/fetch_artifacts.py audit-inputs --offline
```

기존 입력이 다른 폴더에 있다면 아래 make 명령의 `INPUTS`에 그 폴더 경로를 넣는다. 기본 `INPUTS`는 이전 작업 환경과의 호환을 위해 `../audit-inputs`이며, 이 문서는 저장소 내부 `audit-inputs`를 명시한다.

## 빌드와 모의 검사

```bash
make INPUTS="$PWD/audit-inputs"
make preflight
modinfo -F version kernel/gpu_unlock/ga107_unlock.ko
modinfo -F vermagic kernel/gpu_unlock/ga107_unlock.ko
```

`make`는 입력 해시 검사, 원본 소스 추출, 5개 펌웨어 생성, 커널 모듈 빌드와 모의 테스트를 실행한다. 펌웨어는 `build/firmware`, 감사 결과는 `build/offline-audit.json`, 모듈은 `kernel/gpu_unlock/ga107_unlock.ko`에 생성된다. `make preflight`는 현재 장치 상태를 읽는다. 이 명령들은 모듈 설치·로딩·GPU 설정 변경을 하지 않는다.

개별 단계:

```bash
make prepare INPUTS="$PWD/audit-inputs"
make module LLVM=1
make test INPUTS="$PWD/audit-inputs"
make stage INPUTS="$PWD/audit-inputs"
```

`make stage`도 시스템에 설치하지 않고 `build/stage`에 파일만 배치한다. stage의 커널 경로는 실행 중인 `uname -r`을 사용하므로 다른 커널 대상으로는 아래 명시적 빌드와 설치 절차를 따른다.

다른 커널용 빌드에서는 아래 경로의 `TARGET_KERNEL_VERSION`을 실제 설치된 커널 버전으로 바꾼다.

```bash
make module KDIR=/usr/lib/modules/TARGET_KERNEL_VERSION/build LLVM=1
```

현재 CachyOS 커널은 Clang용이므로 `LLVM=1`이 기본이다. 다른 컴파일러로 빌드된 커널에서는 해당 커널의 빌드 도구를 사용해야 한다.

## 설치와 부팅

관리자 설치·NVIDIA보다 앞선 부팅 순서·복구 명령은 [ADMIN.md](ADMIN.md), 새 커널 재빌드와 영구 부팅 인자는 [UPDATE-NOTES.md](UPDATE-NOTES.md)에 있다. 문서의 `/path/to/ga107-unlock`, `MACHINE_ID`, `REDACTED_UUID`는 예시 자리표시자다. 실제 설치 경로, `/etc/machine-id`, 현재 정상 부팅의 root UUID에 맞게 바꾼다. 기존 root 인자를 유지하며 다른 장치의 UUID를 복사하지 않는다.

## 선택 사항: 벤치마크 환경

uv로 저장소 내부 가상환경을 만든다. 기존 측정 환경은 Python 3.14, PyTorch `2.14.1+cu130`이었다. 새 환경에서 같은 버전을 구할 수 없다면 사용한 버전을 기록하고 ON/OFF 양쪽에 동일하게 사용한다.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python torch==2.14.1 --index-url https://download.pytorch.org/whl/cu130
uv pip install --python .venv/bin/python nvidia-ml-py numpy
.venv/bin/python -u bench/bench_extended.py
```

GPU 설정을 변경하지 않는 스크립트지만 GPU 부하가 발생한다. 생성된 `bench/bench-extended-results.json`은 Git에서 제외된다. ON/OFF 결과를 서로 다른 이름으로 보관하고 비교한다.

```bash
python3 tools/compare.py bench/baseline-2026-10-19.json bench/bench-extended-results.json
```

초기 기준 데이터와 요약 결과만 저장소에 포함한다. 원시 부팅 로그·빌드 로그는 제외했으며 문서에 언급된 로컬 로그 파일은 clone 후 존재하지 않는다.

PyTorch 없이 CUDA Toolkit과 NVML로 실행하는 레지스터 MMA 실험은 [bench/mma/README.md](bench/mma/README.md)를 참고한다.
