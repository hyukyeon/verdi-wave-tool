# Verdi nWave Tool — LTE/NR Waveform Analysis Manual

## 목차

1. [개요](#1-개요)
2. [파일 구조](#2-파일-구조)
3. [설치 및 요구사항](#3-설치-및-요구사항)
4. [빠른 시작](#4-빠른-시작)
5. [시나리오 상세](#5-시나리오-상세)
   - [sfr-check — SFR→채널 응답 레이턴시 측정](#51-sfr-check--sfr→채널-응답-레이턴시-측정)
   - [timing — 채널 간 타이밍 정렬 분석](#52-timing--채널-간-타이밍-정렬-분석)
   - [compare — 멀티 인스턴스/FSDB 비교](#53-compare--멀티-인스턴스fsdb-비교)
   - [edge-count — 엣지/토글 통계](#54-edge-count--엣지토글-통계)
   - [frame-sync — 프레임 경계 마커 생성](#55-frame-sync--프레임-경계-마커-생성)
   - [full — 전체 시나리오 실행](#56-full--전체-시나리오-실행)
6. [설정 파일 (YAML) 커스터마이징](#6-설정-파일-yaml-커스터마이징)
7. [생성 파일 설명](#7-생성-파일-설명)
8. [CLI 옵션 참조](#8-cli-옵션-참조)
9. [nWave 주요 Tcl 명령어 참조](#9-nwave-주요-tcl-명령어-참조)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. 개요

`verdi_wave_tool.py`는 LTE/NR 칩 검증 환경에서 Verdi nWave 파형 분석을 자동화하는 도구입니다.

**주요 기능:**
- **Signal RC 파일 생성**: 채널별 색상 그룹, Radix 설정, Expression 신호를 포함한 `.rc` 파일 자동 생성
- **TCL 분석 스크립트 생성**: 시나리오별 분석 자동화 스크립트 생성
- **5가지 분석 시나리오**: SFR 체크, 타이밍, 비교, 엣지 카운트, 프레임 동기

**생성 결과:**
```
verdi_out/
├── signals.rc                  # nWave 신호 리스트 (그룹/색상/expression)
├── scenario_sfr_check.tcl      # SFR 응답 레이턴시 분석
├── scenario_timing.tcl         # 채널 간 타이밍 분석
├── scenario_compare.tcl        # 신호 비교 분석
├── scenario_edge_count.tcl     # 엣지 카운트 통계
├── scenario_frame_sync.tcl     # 프레임 경계 마커
├── scenario_full.tcl           # 전체 시나리오 wrapper
└── (reports/)                  # 시뮬레이션 후 생성되는 분석 결과
    ├── sfr_check_report.txt
    ├── timing_report.txt
    ├── compare_report.txt
    ├── edge_count_report.txt
    └── frame_sync_report.txt
```

---

## 2. 파일 구조

```
Verdi/
├── verdi_wave_tool.py          # 메인 Python CLI 툴
├── configs/
│   └── lte_nr_default.yaml     # 기본 LTE/NR 신호 설정 (커스터마이징용 템플릿)
├── docs/
│   └── manual.md               # 이 문서
└── output/                     # 생성 파일 기본 저장 경로 (--output-dir 변경 가능)
```

---

## 3. 설치 및 요구사항

### Python 패키지
```bash
# 필수: Python 3.6+
python3 --version

# 권장: PyYAML (없으면 JSON config만 사용 가능)
pip3 install pyyaml
# 또는
pip3 install --user pyyaml
```

### Verdi 버전
- **권장**: Verdi 2019.06 이상
- 생성되는 Tcl 명령어: `nw*` API + `wv*` RC 포맷
- Verdi 버전에 따라 일부 Tcl 명령어 이름이 다를 수 있음 → [Troubleshooting](#10-troubleshooting) 참조

---

## 4. 빠른 시작

### Step 1: 기본 설정 파일 내보내기 및 수정

```bash
# 기본 설정 파일을 현재 프로젝트에 맞게 내보내기
cd /home/hyukyeon/14_Scripts/Verdi
python3 verdi_wave_tool.py --dump-config > configs/my_project.yaml

# 편집: top path, clock, 신호 이름을 프로젝트에 맞게 수정
vim configs/my_project.yaml
```

### Step 2: RC + TCL 파일 생성

```bash
# 전체 시나리오 생성 (추천)
python3 verdi_wave_tool.py -f /path/to/sim.fsdb -s full -c configs/my_project.yaml

# 특정 시나리오만 생성
python3 verdi_wave_tool.py -f /path/to/sim.fsdb -s sfr-check -c configs/my_project.yaml

# 결과는 ./verdi_out/ 에 생성됨
```

### Step 3: Verdi 실행

```bash
# 방법 1: 툴이 출력하는 launch command 그대로 실행
verdi -ssf sim.fsdb -rcFile verdi_out/signals.rc -play verdi_out/scenario_full.tcl

# 방법 2: --launch 플래그로 자동 실행
python3 verdi_wave_tool.py -f sim.fsdb -s full --launch

# 방법 3: Verdi 실행 후 nWave Tcl console에서 수동 소스
nwSource verdi_out/scenario_sfr_check.tcl
```

---

## 5. 시나리오 상세

### 5.1 `sfr-check` — SFR→채널 응답 레이턴시 측정

**목적:** SFR(Special Function Register) 값 변경 후 채널이 몇 사이클 내에 반응하는지 측정
**사용 상황:** 채널 enable/disable, MCS 변경, TA 설정 후 동작이 spec 내에 있는지 검증

**동작:**
1. 지정된 SFR 신호에서 값 변경(value change)을 모두 스캔
2. 각 변경 시점에 **노란색 마커** 생성
3. 변경 후 `max_latency_cycles` 사이클 이내 응답 신호(channel enable/valid)의 rising edge 탐색
4. **레이턴시 위반 시**: 응답 신호를 **빨간색**으로 변경 + 리포트에 기록
5. **정상 시**: **초록색**으로 표시

**생성 리포트:** `sfr_check_report.txt`
```
[SFR: PDSCH_CFG] path: tb.dut.sfr.pdsch_cfg[31:0]
SFR_CHANGE @ 1000000ps  val=0x00000001  resp @ 1005000ps  latency=5 cycles
SFR_CHANGE @ 5000000ps  val=0x000000A1  resp @ 5015000ps  latency=15 cycles
  *** LATENCY VIOLATION: 15 > 10 ***
```

**설정 파라미터 (yaml `scenarios.sfr_check`):**
| 파라미터 | 설명 | 기본값 |
|---------|------|--------|
| `max_latency_cycles` | 허용 최대 레이턴시 (사이클) | 16 |
| `watch_sfr` | 감시할 SFR 레지스터 이름 목록 | CHAN_CTRL, PDSCH_CFG, ... |

---

### 5.2 `timing` — 채널 간 타이밍 정렬 분석

**목적:** 기준 채널(reference)과 비교 채널들 사이의 활성화 시간 차이 측정
**사용 상황:** DL/UL 채널이 같은 서브프레임에 동시 활성화되는지, PDCCH→PDSCH 순서가 올바른지 검증

**동작:**
1. 기준 채널(`reference_channel`)의 첫 번째 en/vld rising edge 탐색
2. 각 비교 채널과의 **시간 델타 측정** (ns 단위)
3. **동시 활성화 체크**: tolerance(2 사이클) 이내에 함께 활성화되는지 검증
4. 기준 마커(녹색)와 비교 마커(주황색) 생성

**생성 리포트:** `timing_report.txt`
```
=== Enable Signal Deltas (vs PDSCH) ===
  PDSCH_vs_PUSCH_en: delta = +1000 ns
  PDSCH_vs_PDCCH_en: delta = -500 ns

=== Simultaneous Alignment Check ===
  PDSCH↔PUSCH: 0 violations
  PDSCH↔PDCCH: 2 violations
```

**설정 파라미터 (yaml `scenarios.timing`):**
| 파라미터 | 설명 | 기본값 |
|---------|------|--------|
| `reference_channel` | 기준이 되는 채널 이름 | PDSCH |
| `compare_channels` | 비교 대상 채널 목록 | [PUSCH, PDCCH, SSB] |
| `time_unit` | 시간 단위 표시 | ns |

---

### 5.3 `compare` — 멀티 인스턴스/FSDB 비교

**목적:** 동일 신호를 두 개의 다른 경로/파일에서 비교하여 불일치 검출
**사용 상황:**
- 멀티 캐리어(CC0, CC1) 동작이 동일한지 비교
- 레퍼런스 모델 결과 vs RTL 출력 비교
- 다른 설정에서 동일 채널 동작 비교

**모드:**

#### multi-instance (기본)
```yaml
scenarios:
  compare:
    mode: multi-instance
    instances: [cc0, cc1]
    signals_to_compare:
      - pdsch_dl_data[127:0]
      - pdsch_dl_vld
```
→ `tb.dut.cc0.pdsch_dl_data` vs `tb.dut.cc1.pdsch_dl_data` 비교

#### multi-fsdb (두 FSDB 비교)
```bash
python3 verdi_wave_tool.py -f sim.fsdb -s compare --ref ref.fsdb
```
```yaml
scenarios:
  compare:
    mode: multi-fsdb
```
→ `sim.fsdb`의 신호 vs `ref.fsdb`의 동일 신호 비교

**동작:**
1. 두 신호 경로의 XOR Expression 신호 생성 (`xor_*`) → 불일치 시 non-zero
2. 불일치 발생 시점에 **빨간색 마커** 생성
3. 총 불일치 횟수 카운트 후 리포트

**생성 리포트:** `compare_report.txt`
```
=== cc0 vs cc1 ===
  pdsch_dl_data[127:0]: 3 mismatch events
  pdsch_dl_vld: 0 mismatch events
```

---

### 5.4 `edge-count` — 엣지/토글 통계

**목적:** 시뮬레이션 전 구간에서 채널별 신호의 rising/falling edge 횟수 집계
**사용 상황:**
- 예상한 횟수의 PDSCH 전송이 발생했는지 확인
- SFR 설정에 따른 채널 활성화 횟수 검증
- 클럭 대비 채널 가동률 확인

**동작:**
1. 전체 시뮬레이션 구간에서 각 채널의 `vld` 신호 rising/falling edge 카운트
2. 클럭 edge 카운트로 총 사이클 수 계산
3. 채널별 통계 생성

**생성 리포트:** `edge_count_report.txt`
```
Clock reference:
  CLK                   rise=50000  (= simulation length in cycles)

Channel statistics (vld signal):
  PDSCH                 rise=1024   fall=1024   total_toggle=2048
  PUSCH                 rise=512    fall=512    total_toggle=1024
  PDCCH                 rise=2048   fall=2048   total_toggle=4096
  PUCCH                 rise=256    fall=256    total_toggle=512
  SSB                   rise=80     fall=80     total_toggle=160
  PRACH                 rise=4      fall=4      total_toggle=8
```

**설정 파라미터 (yaml `scenarios.edge_count`):**
| 파라미터 | 설명 | 기본값 |
|---------|------|--------|
| `channels` | 분석할 채널 목록 | [PDSCH, PUSCH, PDCCH, ...] |
| `signal_key` | 채널 내 분석할 신호 키 | vld |
| `edge_type` | 카운트할 엣지 방향 | rising |

---

### 5.5 `frame-sync` — 프레임 경계 마커 생성

**목적:** LTE/NR 프레임/서브프레임/슬롯 경계에 마커를 생성하여 파형 분석 기준점 제공
**사용 상황:**
- 채널 활성화가 올바른 서브프레임에서 시작하는지 확인
- 프레임 번호(SFN)와 실제 파형 정렬 검증
- SSB/PRACH 주기성(periodicity) 검증

**생성 마커:**
| 마커 색상 | 의미 |
|---------|------|
| 흰색 | Frame 경계 (`FRAME_0`, `FRAME_1`, ...) |
| 청록색 | Subframe 경계 (`F0_SF1`, `F0_SF2`, ...) |
| 회색 | Slot 경계 (`F0_SF0_SL1`, ...) |
| 빨간색 | 프레임 정렬 위반 (`FRAME_FAIL`) |

**NR Numerology 대응:**
```yaml
scenarios:
  frame_sync:
    standard: "NR"
    lte_frame_ns:   10000000  # 10 ms (고정)
    nr_subframe_ns:  500000   # μ=1 (30kHz SCS) → 0.5ms
    nr_slot_ns:      125000   # μ=3 (120kHz SCS) → 0.125ms
    num_frames: 4
```

| NR μ | SCS | Subframe | Slot |
|------|-----|----------|------|
| 0 | 15 kHz | 1 ms | 1 ms |
| 1 | 30 kHz | 0.5 ms | 0.5 ms |
| 2 | 60 kHz | 0.5 ms | 0.25 ms |
| 3 | 120 kHz | 0.5 ms | 0.125 ms |

---

### 5.6 `full` — 전체 시나리오 실행

모든 시나리오(sfr-check, timing, compare, edge-count, frame-sync)를 순서대로 실행합니다.
각 시나리오 실패 시 `catch`로 오류를 잡아 나머지 시나리오는 계속 실행합니다.

```bash
python3 verdi_wave_tool.py -f sim.fsdb -s full -c my_config.yaml
```

---

## 6. 설정 파일 (YAML) 커스터마이징

### 6.1 신호 경로 수정

```yaml
top:   "tb.u_lte_nr_top"    # DUT 최상위 경로로 변경
clock: "tb.sys_clk"
reset: "tb.sys_rst_n"
```

### 6.2 채널 신호 추가/수정

```yaml
channels:
  PDSCH:
    color: cyan
    signals:
      - name: en
        path: u_pdsch.dl_enable      # 실제 RTL 신호 이름
        radix: bin
      - name: vld
        path: u_pdsch.output_valid
        radix: bin
      - name: data
        path: u_pdsch.out_data[255:0]  # 버스 폭 변경
        radix: hex
        height: 40                     # 파형 행 높이 (픽셀)
```

### 6.3 멀티 인스턴스 설정

```yaml
channels:
  PDSCH:
    color: cyan
    instances:          # 이 목록이 있으면 각 인스턴스 신호도 추가됨
      - "u_cc0.u_pdsch"
      - "u_cc1.u_pdsch"
      - "u_cc2.u_pdsch"
    signals:
      - name: vld
        path: output_valid    # 각 instance path 아래의 상대 경로
        radix: bin
```

### 6.4 SFR 레지스터 추가

```yaml
sfr:
  base_path: "tb.u_lte_nr_top.u_sfr_ctrl"
  registers:
    MY_NEW_REG:
      path: "my_reg[31:0]"
      fields:
        BIT_A: "[0]"
        FIELD_B: "[7:4]"
        VALUE_C: "[23:8]"
```

### 6.5 비교 모드 설정 (multi-fsdb)

```yaml
scenarios:
  compare:
    mode: multi-fsdb
    signals_to_compare:
      - pdsch_dl_data[127:0]
      - pdcch_dl_dci[39:0]
      - pusch_ul_data[127:0]
```

```bash
# 실행 시 --ref 로 레퍼런스 FSDB 지정
python3 verdi_wave_tool.py -f sim.fsdb -s compare --ref golden_ref.fsdb
```

---

## 7. 생성 파일 설명

### `signals.rc` — Signal RC 파일

nWave에서 신호 목록과 디스플레이 설정을 정의하는 Tcl 스크립트입니다.

**포함 내용:**
- FSDB import
- **TIMING/FRAME** 그룹: clock, reset, SFN, subframe, slot, symbol
- **SFR REGISTERS** 그룹: 모든 SFR 레지스터 + 각 비트 필드 (radix=dec)
- **채널별 그룹**: 색상 구분된 그룹에 enable/valid/data/MCS 등 신호
- **EXPRESSIONS** 그룹: XOR, AND 파생 신호

**직접 로드:**
```bash
# Verdi 실행 후 nWave에서
File → Load Signal RC → verdi_out/signals.rc
# 또는 Tcl console
nwSource verdi_out/signals.rc
```

### `scenario_*.tcl` — 시나리오 TCL 스크립트

각 시나리오별 분석 프로시저(proc)와 메인 실행 코드를 포함합니다.

**구조:**
```tcl
# 1. 헤더 및 변수 설정
set report_dir {...}
set fsdb_file  {...}

# 2. signals.rc 소스 (신호 로드)
source {verdi_out/signals.rc}

# 3. 분석 프로시저 정의
proc measure_sfr_to_response {...} { ... }

# 4. 메인 실행 코드
# - 분석 수행
# - 마커 생성
# - 리포트 파일 출력
```

---

## 8. CLI 옵션 참조

```
usage: verdi_wave_tool [-f FSDB] [-s SCENARIO] [-c CONFIG] [-o OUTPUT_DIR] [options]

필수 옵션:
  -f, --fsdb FSDB       분석할 FSDB 파일 경로

시나리오 선택:
  -s, --scenario        sfr-check | timing | compare | edge-count | frame-sync | full
                        (기본값: full)

설정:
  -c, --config FILE     YAML/JSON 설정 파일 (기본값: 내장 LTE/NR 기본값 사용)
  -o, --output-dir DIR  출력 디렉토리 (기본값: ./verdi_out)
  --top PATH            DUT 최상위 경로 재정의 (yaml top 값 덮어씀)
  --clock PATH          클럭 신호 경로 재정의

비교 시나리오:
  --ref FSDB            compare 시나리오용 레퍼런스 FSDB 파일

실행:
  --launch              파일 생성 후 Verdi 자동 실행
  --novas               verdi 대신 novas 명령어 사용

정보:
  --list-scenarios      사용 가능한 시나리오 목록 출력
  --dump-config         내장 기본 설정을 stdout으로 출력
  -h, --help            도움말 출력
```

### 사용 예시

```bash
# 1. 기본 전체 분석
python3 verdi_wave_tool.py -f sim.fsdb

# 2. SFR 체크만, 프로젝트 설정 사용
python3 verdi_wave_tool.py -f sim.fsdb -s sfr-check -c configs/my_project.yaml

# 3. 두 FSDB 비교
python3 verdi_wave_tool.py -f sim.fsdb -s compare --ref golden.fsdb

# 4. DUT path 재정의 (yaml 수정 없이)
python3 verdi_wave_tool.py -f sim.fsdb --top tb.bench.u_dut --clock tb.clk_300m

# 5. 결과를 특정 디렉토리에 저장하고 Verdi 자동 실행
python3 verdi_wave_tool.py -f /proj/sim/latest.fsdb \
    -s full \
    -c /proj/config/chip_a.yaml \
    -o /proj/verdi_scripts/ \
    --launch

# 6. NR μ=3 (120kHz) 프레임 마커
python3 verdi_wave_tool.py -f sim.fsdb -s frame-sync
# yaml에서 nr_slot_ns: 125000 으로 설정

# 7. 내장 설정 내보내기
python3 verdi_wave_tool.py --dump-config > configs/my_project.yaml
```

---

## 9. nWave 주요 Tcl 명령어 참조

생성된 TCL 파일에서 사용되는 nWave API 명령어입니다. Verdi Tcl console에서도 직접 사용 가능합니다.

### 신호 관리

```tcl
# 신호 추가
wvAddSignal {tb.dut.pdsch_dl_en}

# Radix 설정
wvSetSignalRadix -radix hex {tb.dut.pdsch_dl_data[127:0]}
wvSetSignalRadix -radix dec {tb.dut.sfn[9:0]}

# 색상 설정
wvSetSignalColor -color cyan {tb.dut.pdsch_dl_en}

# Alias (표시 이름) 설정
wvSetSignalAlias -alias {PDSCH_EN} {tb.dut.pdsch_dl_en}

# Expression 신호 추가
wvAddExprSignal -name {pdsch_mismatch} \
                -color red \
                -expr {tb.dut.cc0.pdsch_dl_data ^ tb.dut.cc1.pdsch_dl_data}

# 그룹 만들기
wvSetGroupBegin -name {PDSCH} -backgroundcolor cyan
wvAddSignal {tb.dut.pdsch_dl_en}
wvSetGroupEnd
```

### 탐색 및 측정

```tcl
# 다음 rising edge 찾기
nwSearchNext -signal {tb.dut.pdsch_dl_vld} -type rising_edge -from 0

# 다음 값 변경 찾기
nwSearchNext -signal {tb.dut.sfr.pdsch_cfg[31:0]} -type value_change -from $t

# 특정 값 찾기
nwSearchNext -signal {tb.dut.pdsch_dl_mcs[4:0]} -value 5'h1A -from 0

# 현재 시각 값 읽기
nwGetValue -signal {tb.dut.pdsch_dl_data[127:0]} -time 1000000

# 시뮬레이션 시간 범위
nwGetMinTime   ;# 시작 시각
nwGetMaxTime   ;# 끝 시각

# 클럭 주기 계산
nwGetClockPeriod {tb.clk}
```

### 마커 & 커서

```tcl
# 마커 생성
nwAddMarker -time 1000000 -name {SFR_WRITE} -color yellow

# 커서 이동
nwSetCursor -time 2000000

# Reference cursor 이동
nwSetRefCursor -time 1000000
```

### 줌 & 뷰

```tcl
# 특정 범위로 줌
nwZoom -from 0 -to 10000000

# 전체 보기
wvZoomFit

# 현재 커서 위치로 줌
nwZoomToCursor
```

---

## 10. Troubleshooting

### Q: `wvAddSignal: command not found`

Verdi 버전에 따라 `wv*` 대신 `nw*` 접두어를 사용할 수 있습니다.

```tcl
# 구버전
wvAddSignal {tb.clk}

# 신버전 nWave
nwAddSignal {tb.clk}
```

`signals.rc` 파일에서 `wv` → `nw` 로 전체 치환:
```bash
sed -i 's/^wv/nw/g' verdi_out/signals.rc
```

### Q: 생성된 TCL에서 신호가 FSDB에 없다고 에러

신호 경로가 실제 FSDB와 다를 때 발생합니다.

1. Verdi에서 FSDB를 열고 Signal Browser에서 실제 경로 확인
2. `configs/my_project.yaml`의 `top`, 각 채널의 `path` 수정
3. `--top` 옵션으로 빠르게 재정의 가능:
   ```bash
   python3 verdi_wave_tool.py -f sim.fsdb --top tb.u_chip.u_modem
   ```

### Q: `nwGetClockPeriod` 가 0을 반환

FSDB에 클럭 신호가 저장되지 않은 경우입니다.

```tcl
# TCL 파일에서 수동으로 클럭 주기 설정
set clk_period 1000  ;# 1 ns = 1000 ps (1GHz 클럭 예시)
```

또는 yaml에서:
```yaml
# clock_period_ps 필드 추가 (향후 버전 지원 예정)
```

### Q: 프레임 마커 타이밍이 시뮬레이션과 맞지 않음

`frame_sync` 시나리오의 `unit_ps` 설정을 시뮬레이션 timescale에 맞게 수정합니다.

```tcl
# scenario_frame_sync.tcl 파일에서
set unit_ps 1     ;# timescale 1ps/1ps 인 경우
set unit_ps 1000  ;# timescale 1ns/1ps 인 경우 (기본값)
```

또는 FSDB의 첫 번째 값 변경 시점을 확인하고 frame_start를 보정합니다.

### Q: compare 시나리오에서 모든 비교가 mismatch

멀티 인스턴스 경로가 올바른지 확인합니다:
```yaml
scenarios:
  compare:
    mode: multi-instance
    instances:
      - "u_cc_top.u_cc0"     # tb.dut. 이후 경로
      - "u_cc_top.u_cc1"
```

### Q: edge-count 결과가 0

`signal_key` 가 채널의 `name` 필드와 일치하는지 확인합니다:
```yaml
channels:
  PDSCH:
    signals:
      - name: valid      # ← signal_key: "vld" 와 불일치!
        path: pdsch_vld

scenarios:
  edge_count:
    signal_key: "valid"  # ← name 필드와 일치시켜야 함
```

---

*Generated by verdi_wave_tool — LTE/NR Waveform Analysis Tool*
