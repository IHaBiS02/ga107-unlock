# 다운로드한 610.43.03 파일의 GA107 대조 결과

검토 날짜: 2026-10-19. 초안은 분석·빌드·테스트만 수행한 상태에서 작성했다. 이후 사용자가 `0.1.0`을 실제 부팅에서 실행해 FWSEC DMA 정렬/자원 유지 버그를 발견했다. 실패 기록과 `0.1.1` 수정 범위는 [INCIDENT-2026-10-19.md](INCIDENT-2026-10-19.md)를 참조한다. 수정본은 실제 GPU에서 실행하지 않았다.

## 입력 검증

| 입력 | SHA-256 |
|---|---|
| NVIDIA-kernel-module-source-610.43.03.tar.xz | `7e118923c7a23edc36114d63273a46e3e04e9af98695a42203e7ac2dfe9fc1dc` |
| nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst | `e17e7c92eeffa178b0fe1f40eb17a47095f8fc3ce4a77bf115cf5bd5a4df86e9` |

실제 파일 해시가 기존 매니페스트와 일치한다. `tools/prepare.py`로 재검사할 수 있다. 5개 바이너리와 NVIDIA 라이선스를 추출/생성했고, 생성기에서 모든 출력의 핀된 해시도 검증했다. NVIDIA 입력의 실행·설치는 하지 않았다.

## 공식 HAL 분기 확인

추출 위치는 `research/source/NVIDIA-kernel-module-source-610.43.03`이다. `src/nvidia/generated/g_kernel_gsp_nvoc.c`에서 다음을 직접 대조했다.

| 항목 | GA107 선택 | 위치 |
|---|---|---|
| BooterLoad | `kgspGetBinArchiveBooterLoadUcode_GA102` | 1646–1648행 |
| BooterUnload | `kgspGetBinArchiveBooterUnloadUcode_GA102` | 1679–1681행 |
| GSP boot image | `kgspGetBinArchiveGspRmBoot_GA102` | 833–835행 |
| GSP Falcon 설정 | TU102/GA100 예외에 해당하지 않아 `kgspConfigureFalcon_GA102` | 588–606행 |
| pre-scrubbed top FB | `kgspGetPrescrubbedTopFbSize_13afc5` | 1375–1377행 |
| 최소 WPR heap | `kgspGetMinWprHeapSizeMB_d2c3c5` | 1728–1730행 |
| scrubber 지원 | GA107은 지원 대상인 Ada가 아니므로 false | 478–486행 |

`g_kernel_gsp_nvoc.h` 1985행의 pre-scrubbed top은 256 MiB다. 2116행의 최소 heap은 vGPU offload가 없는 이 경로에서 88 MiB다. 이 값들은 기존 로컬 메모리 배치와 일치한다. 실제 usable FB와 VGA/메모리 잠금 값은 cold boot 레지스터에서 읽어 계산한다. 4 GB라고 고정된 물리 주소를 쓰지 않는다.

## Booter 자산과 V67

생성된 `booter_load_ga102.bin`의 외부 bundle 헤더를 파싱하면 다음과 같다.

- Booter image 60,416 bytes, engine mask 1 (SEC2), ucode ID 3.
- production signature 2개, 각 384 bytes. 실제 fuse 버전을 읽어 사용할 서명을 고른다. 지원 범위를 벗어나면 중단한다.
- GSP boot image 24,576 bytes, descriptor 84 bytes / version 5.
- GSP-RM signature 섹션은 `.fwsignature_ga10x`, 원본 크기 4,096 bytes.
- 특수 V67 signature image는 64,000 bytes다. PLM 대상 주소는 `0x00823804`다.

GA107도 **동일한 공식 Booter 바이너리**를 선택하므로 이 포트는 별도의 GA107이라는 이름으로 ROP 주소를 새로 만들어 넣지 않는다. 기존 체크섬으로 고정한 V67 체인을 그대로 사용한다. 이것은 바이너리 공유에 근거한 재사용이며, GA107 BootROM·보드 fuse에서의 취약점 실행 성공을 증명하는 것은 아니다. 이번에 Booter 전체 디스어셈블리/명령 단위 에뮬레이션을 새로 수행하지는 않았다.

## 속도 필드에 관해 확정한 범위

공식 `src/common/sdk/nvidia/inc/ctrl/ctrl2080/ctrl2080gr.h`에는 `GET_SM_ISSUE_RATE_MODIFIER`와 V2 API가 있다. FMLA16/32, FFMA, DP, IMLA0..4 등의 분류 및 full/절반 속도 보고값이 정의된다. 그러나 이것은 드라이버의 **보고 API**이며 `SS0[27:24]`처럼 실제 FEAT_OVR 비트 위치를 정의하지는 않는다. 보고 API의 full-speed=0과 override 레지스터에 쓰는 8도 동일 인코딩으로 간주하면 안 된다.

원본 CMP 리포지터리의 `research/TENSOR_CORE_ANALYSIS.md`에는 nibble별 맵이 있지만, 그 맵을 GA107의 공식 검증 자료로 쓰지 않았다. 과거 연구 문서에는 이후 결과로 뒤집힌 결론도 있어 실행 포트의 근거로 삼을 때 주의가 필요하다. pinned ref commit은 `76940ae583281daa2b883518a2e89b56c11d3a46`이다.

따라서 구현의 정책은 **SS0 전체=0x88888888, SS1 원래 값 보존**이다. 다른 연산 필드가 바뀔 수 있고, BF16만 좁게 변경한다는 주장은 하지 않는다. BF16/FP16-FP32/TF32의 절반 제한은 실제 GEMM에서 확인했지만 SS0 field와 각 타입의 일대일 관계는 아직 검증되지 않았다.

## 하드웨어 실행 전 남은 조건

- 현재 장치는 `10de:25ab / 1854:052f`, VBIOS `94.07.8D.00.21`, 드라이버 615.78.08이다. sysfs reset_method는 `flr bus`이다. 이는 FLR 지원 광고의 확인이며 cold boot 이후 실제 FLR 성공 검증은 아니다.
- 노트북의 BAR0 PROM에서 FWSEC-FRTS가 추출되는지는 미확인이다. 기존 `../gpu-unlock/vbios_sysfs.rom`은 0바이트다. 빈 파일을 펌웨어로 사용하지 않는다.
- module은 다른 board, bound/D3 장치, bus-master 상태, 기존 WPR2 초기화, 맞지 않는 ROM/서명/메모리 배치를 거절한다. 런타임 검사 통과만으로 완전한 안전성을 보장하지는 않는다.
- 설치된 드라이버를 610으로 교체하지 않는다. 610.43.03 자산으로 pre-driver 실험 후 FLR을 통해 615.78.08에 넘기는 것이 목표이며 이 handoff는 GA107에서 미검증이다.

## 검증 내용

현재 CachyOS `7.2.9-2-cachyos` 헤더와 LLVM으로 커널 모듈을 빌드했다. 모듈 이름과 5개 firmware 경로를 modinfo로 확인했다.

일반 사용자 C 테스트는 실제 parser/layout/DMA metadata/transaction 코드를 모의 PCI/MMIO와 결합한다. GA107 4 GiB 메모리 배치의 전체 거래에 실제 추출된 바이너리를 사용하고, ROM은 synthetic fixture를 사용한다. 61개 full-transaction 시나리오와 단위 실패 시나리오를 검사한다. wrong chip/board/bound 장치를 하드웨어 작업 전에 차단하고, SS1 write가 0회인지, FLR에서 SS1을 잃으면 실패하는지 검증한다. 추가한 실측 기반 geometry 시나리오는 0x980 DMEM 올림 전송, 정렬되지 않은 소스 거절, DMA 이전 실패 시 BAR/DMA 자원 반환을 검사한다. main 진입 테스트는 execute=0, 미지정 target, all/list 거절, board/bound guard, 실패 후 모듈을 유지하는 흐름을 검사한다.

**테스트 통과는 물리 GPU에서의 서명 수락·페이로드 실행·성능 개선 검증이 아니다.** 실제 적용은 수행하지 않았다.

## systemd initramfs 순서 보정

초기 boot drop-in의 `?` optional marker와 단순 MODULES 순서는 수정했다. 로컬 `/usr/lib/initcpio/install/systemd`는 MODULES 원문을 `/etc/modules-load.d/MODULES.conf`로 기록한다. 따라서 `ga107_unlock?`가 실제 로더에 전달될 수 있다. 또한 설치된 systemd 262는 모듈 로드 작업자 스레드를 사용하며, udev coldplug와도 명시적 선후관계가 없었다.

새 `ga107-order` 빌드 훅은 이미지 안에만 서비스를 생성하고 sysinit.target에서 활성화한다. 서비스는 systemd-modules-load 및 udev daemon/coldplug보다 먼저 모듈 로드를 완료한다. 해당 커널용 모듈이 설치돼 있지 않은 LTS에서는 drop-in이 모듈/훅을 제외한다. 훅 생성 결과의 systemd unit 문법과 mock present/absent 커널 선택·중복 삽입 방지를 검사했다. 실제 배포 이미지 내용은 관리자 권한으로 `tools/inspect_initramfs.py`를 실행해 확인해야 한다.
