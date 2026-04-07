#!/usr/bin/env bash
# =============================================================================
# run_debug.sh — Verdi nWave Debug Mode Launcher
# =============================================================================
# 사용법:
#   ./run_debug.sh <mode> <fsdb> [scenario] [extra options...]
#
# 모드:
#   lte-crs     TopSim LTE CRS debugging
#   nr-ssb      BlockSim NR SSB debugging
#   default     기본 LTE/NR 전체 채널
#
# 시나리오 (선택, 기본값: full):
#   sfr-check | timing | compare | edge-count | frame-sync | full
#
# 예시:
#   ./run_debug.sh lte-crs /sim/topsim_lte.fsdb
#   ./run_debug.sh nr-ssb  /sim/blocksim_nr.fsdb  sfr-check
#   ./run_debug.sh lte-crs /sim/run1.fsdb compare --ref /sim/run2.fsdb
#   ./run_debug.sh nr-ssb  /sim/ssb.fsdb  timing   --launch
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="${SCRIPT_DIR}/verdi_wave_tool.py"

# ---------------------------------------------------------------------------
# 인자 파싱
# ---------------------------------------------------------------------------
MODE="${1:-}"
FSDB="${2:-}"
SCENARIO="${3:-full}"

# 3번째 인자가 시나리오가 아니면 full로 설정
if [[ "${SCENARIO}" == --* ]]; then
    SCENARIO="full"
    shift 2
else
    shift 3 2>/dev/null || shift $#
fi

EXTRA_ARGS="$@"

# ---------------------------------------------------------------------------
# 도움말
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") <mode> <fsdb> [scenario] [options]

Modes:
  lte-crs    TopSim LTE CRS debugging   (configs/modes/topsim_lte_crs.yaml)
  nr-ssb     BlockSim NR SSB debugging  (configs/modes/blocksim_nr_ssb.yaml)
  default    Default LTE/NR full        (built-in config)

Scenarios: sfr-check | timing | compare | edge-count | frame-sync | full (default)

Options (passed through to verdi_wave_tool.py):
  --ref <fsdb>      Reference FSDB for compare scenario
  --launch          Auto-launch Verdi after generating files
  --top <path>      Override DUT top path
  --clock <path>    Override clock signal path
  -o <dir>          Output directory

Examples:
  $0 lte-crs  sim.fsdb
  $0 nr-ssb   sim.fsdb  sfr-check
  $0 lte-crs  sim.fsdb  compare  --ref ref.fsdb
  $0 nr-ssb   sim.fsdb  full     --launch
  $0 default  sim.fsdb
EOF
    exit 0
}

[[ -z "${MODE}" || "${MODE}" == "-h" || "${MODE}" == "--help" ]] && usage

# ---------------------------------------------------------------------------
# 모드 → config 파일 매핑
# ---------------------------------------------------------------------------
case "${MODE}" in
    lte-crs)
        CONFIG="${SCRIPT_DIR}/configs/modes/topsim_lte_crs.yaml"
        OUT_DIR="${SCRIPT_DIR}/output/lte_crs"
        MODE_LABEL="TopSim LTE CRS"
        ;;
    nr-ssb)
        CONFIG="${SCRIPT_DIR}/configs/modes/blocksim_nr_ssb.yaml"
        OUT_DIR="${SCRIPT_DIR}/output/nr_ssb"
        MODE_LABEL="BlockSim NR SSB"
        ;;
    default)
        CONFIG=""
        OUT_DIR="${SCRIPT_DIR}/output/default"
        MODE_LABEL="Default LTE/NR"
        ;;
    *)
        echo "[!] Unknown mode: '${MODE}'"
        echo "    Available: lte-crs | nr-ssb | default"
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# FSDB 확인
# ---------------------------------------------------------------------------
if [[ -z "${FSDB}" ]]; then
    echo "[!] FSDB file not specified"
    usage
fi

if [[ ! -f "${FSDB}" ]]; then
    echo "[!] FSDB not found: ${FSDB}"
    exit 1
fi

# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Verdi Debug Mode : ${MODE_LABEL}"
echo "  FSDB             : ${FSDB}"
echo "  Scenario         : ${SCENARIO}"
echo "  Output           : ${OUT_DIR}"
echo "============================================================"

CMD="python3 ${TOOL} -f ${FSDB} -s ${SCENARIO} -o ${OUT_DIR}"
[[ -n "${CONFIG}" ]] && CMD="${CMD} -c ${CONFIG}"
[[ -n "${EXTRA_ARGS}" ]] && CMD="${CMD} ${EXTRA_ARGS}"

echo "[+] Running: ${CMD}"
echo ""
eval "${CMD}"
