# LG GA107 BF16 / FP16-FP32 누산 / TF32 실험 포트

**상태: 0.1.1에서 SS0 적용·FLR·NVIDIA 복귀와 855 MHz ON/OFF 실측을 확인했다. BF16/FP16 FP32 누산은 약 33~35% 개선됐고 TF32는 개선되지 않았다. 완전한 2배 해제를 확인한 것은 아니다.**

현재 소스 버전은 `0.1.1-experimental`이다. `0.1.0`의 첫 실제 부팅은 FWSEC의 비정렬 DMEM 길이를 거절한 뒤 잘못된 실행 상태 플래그로 BAR/DMA 자원을 유지했다. NVIDIA 초기화가 실패했고, V67 및 SS0 쓰기에는 도달하지 않았다. [실패 분석과 복구](INCIDENT-2026-10-19.md). 수정본은 DMEM 전송을 범위 검사 후 256바이트 단위로 올림하고, DMA를 실제로 프로그래밍할 때부터 자원을 유지한다. 0.1.1의 실제 실행에서 SS0 적용·FLR·NVIDIA 복귀는 확인했다. 다만 GEMM 측정은 연산 제한 해제를 입증하지 못했다. [실측 결과](RESULTS-0.1.1.md).

대상은 사용자 장치 `0000:01:00.0`, NVIDIA `10de:25ab`, LG `1854:052f`이다. 다른 보드와 3090은 거절한다. `execute=1`과 정확한 `target`을 함께 지정하지 않으면 펌웨어 요청·MMIO를 하지 않는다. 현재 사용 중인 GPU를 강제로 떼어내는 기능은 없다.

## 무엇을 구현했는가

- 로컬 `gpu-unlock`의 pre-driver FWSEC → V67 → 속도 선택 → FLR 경로를 별도 모듈 `ga107_unlock.ko`로 이식했다.
- 장치 검색뿐 아니라 Falcon 실행 중·FLR 후의 PCI ID 재검사도 GA107 ID로 바꿨다. 보드 ID 검사를 하드웨어 작업 전에 추가했다.
- 공식 610.43.03 HAL에서 GA107의 BooterLoad, GSP boot, HS 실행 경로, 최소 heap 및 pre-scrubbed FB 조건이 공유됨을 확인했다. [분석 상세](ANALYSIS.md).
- SS0에 `0x88888888`을 쓰고 읽어 검증한다. SS1은 진입 값을 저장해 변경하지 않으며 FLR 전후에도 보존됐는지 검사한다.
- FWSEC/서명 형식, 지원하지 않는 fuse 버전, 전원 상태, cold 상태, DMA 및 FLR 검사는 유지했다. 실패 시 부분 변경이 남을 수 있고, Falcon이 멈추지 않으면 DMA 버퍼를 해제하지 않는다.

**이것은 BF16 비트만 변경하는 구현은 아니다.** 공개 소스에서 GA107의 연산별 SS0 비트 맵을 확정할 수 없어 SS0 전체 필드를 원본의 full-rate 선택값으로 쓴다. SS0에 속한 다른 연산에도 영향이 있을 수 있다. SS1의 해제는 포함하지 않는다. SM 개수·VRAM 용량·메모리 버스·클럭·전력 한도는 변경하지 않는다.

목표는 BF16/FP16 입력의 **FP32 누산**과 TF32 처리량이다. FP16 입력의 FP16 누산은 이번 목표인 절반 제한과 다르다. 설정 readback만으로 성공이라 하지 않고, 실제 행렬곱 처리량과 정확도를 재측정해야 한다.

## 관리자 권한 없이 준비

```bash
cd /path/to/ga107-unlock
make                 # 로컬 입력 검증·펌웨어 추출·LLVM 커널 빌드·모의 검사
make preflight       # sysfs와 nvidia-smi 상태 조회만 수행
make stage           # build/stage 안에 설치 예정 파일만 생성
```

입력 폴더를 바꾸려면 `make INPUTS=/절대/경로`. Python 3.14+, zstd, make, clang/LLVM, C 컴파일러, 현재 커널 헤더가 필요하다. 현재 CachyOS 커널은 Clang으로 빌드돼 `LLVM=1`을 기본으로 한다. GCC 커널에서는 `make LLVM=0` 등 환경에 맞는 컴파일러를 지정한다.

이 명령들은 다운로드나 호스트 설치, 드라이버 언로드, GPU 리셋, initramfs 수정, 모듈 로딩을 하지 않는다. 펌웨어 생성기는 NVIDIA 입력과 추출 출력의 SHA-256을 검사한다. 추출한 바이너리를 실행하지 않는다.

주요 결과물:

- `kernel/gpu_unlock/ga107_unlock.ko`: 현재 커널용 실험 모듈.
- `build/firmware/`: 핀된 610.43.03 자산. `ga102`라는 파일명은 공식 공용 자산의 출처를 보존한 것이다.
- `build/offline-audit.json`: 입력·출력 해시, Booter 형식, GA107 HAL 분기 위치.
- `research/preflight-current.json`: 작성 당시 상태. 보드와 FLR은 일치하지만 `nvidia` 바인딩 중이므로 지금 실행하는 것은 거절된다.
- `bench/baseline-2026-10-19.json`: 언락 전 실측. 모든 구간 855 MHz, BF16/FP16-FP32 약 8.63 TFLOPS, TF32 약 4.31 TFLOPS.

모듈 설치·cold boot 실험·로그·원복 명령은 [ADMIN.md](ADMIN.md)에 있다. **그 명령은 이번 작업에서 실행하지 않았다.** 실험은 전원 완전 차단 후 NVIDIA가 처음 바인딩하기 전이어야 한다. 데스크톱에서 unbind 후 재시도하는 방식은 지원하지 않는다.

부팅 설정 수정: 초기 버전의 `ga107_unlock?` 목록만 설치한 경우 [ADMIN.md](ADMIN.md)의 `ga107-order` 훅과 수정된 drop-in을 다시 설치한다. systemd 262의 병렬 모듈 로딩과 udev에 앞서 모듈 처리가 완료되도록 initrd 전용 서비스를 사용한다. `tools/inspect_initramfs.py`로 실제 이미지의 설정을 확인할 수 있다.

## 적용 후 검증

형제 폴더의 준비된 Python 환경을 사용한다.

```bash
.venv/bin/python -u bench/bench_extended.py
python tools/compare.py bench/baseline-2026-10-19.json bench/bench-extended-results.json
```

`bench_extended.py`는 GPU 설정을 변경하지 않지만 GPU 부하를 발생시킨다. 처리량·실제 클럭·온도·전력을 기록하고 출력 일부를 FP64 기준으로 검사한다. INT8은 텐서 커널용 transpose 배치와 일반 배치를 구분한다. 전체 행렬 수치 검증 또는 instruction 단위 포화 실험은 아니다.

## 출처와 한계

커널 코드와 테스트는 기존 `../gpu-unlock` HEAD `0ebdb1c6308b6a2072be5bf04513472942541956`를 기반으로 분리했다. 원본의 GPL-2.0 및 NVIDIA/CMP 고지는 `licenses/`와 `firmware/NOTICE.md`에 보존했다. NVIDIA 바이너리는 별도 라이선스이다.

0.1.1 부팅에서 노트북 PROM FWSEC 실행, SS0 쓰기 및 FLR 후 유지, SS1 보존과 설치된 615.78.08로의 복귀를 확인했다. 성능 제한 해제 효과는 확인하지 못했다. 같은 펌웨어를 쓴다는 사실은 실행 성공이나 손상 위험 0을 보장하지 않는다. 이 포트에는 플래시/eFuse 쓰기 기능이 없지만 실패 시 화면/GPU 정지와 전원 완전 차단이 필요할 수 있다.

업데이트 후 유지·새 커널 재빌드·영구 부팅 설정과 ComfyUI 실측은 [UPDATE-NOTES.md](UPDATE-NOTES.md)에 정리했다.

독립 환경의 입력 다운로드부터 빌드·검사·벤치마크 준비까지는 [BUILD.md](BUILD.md)를 따른다. 저장소에는 개인 식별자가 제거된 문서와 소스만 포함하며, 원시 로그·빌드 산출물은 `.gitignore`로 제외한다.
