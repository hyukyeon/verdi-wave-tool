#!/usr/bin/env python3
"""
verdi_wave_tool.py — Verdi nWave Tool for LTE/NR Waveform Analysis
====================================================================
Generates:
  1. Signal RC file  (.rc)  — signal list with groups, colors, expressions
  2. TCL analysis script (.tcl) — scenario-specific analysis automation

Scenarios:
  sfr-check    SFR write → channel response latency measurement
  timing       Inter-channel timing alignment & delta analysis
  compare      Multi-instance or multi-FSDB signal comparison
  edge-count   Toggle/edge count statistics per channel
  frame-sync   LTE/NR frame/subframe/slot boundary markers
  full         All scenarios combined

Usage:
  python3 verdi_wave_tool.py -f sim.fsdb [options]
  python3 verdi_wave_tool.py -f sim.fsdb -s sfr-check -c my_config.yaml
  python3 verdi_wave_tool.py -f sim.fsdb -s compare --ref ref.fsdb
  python3 verdi_wave_tool.py -f sim.fsdb -s full --launch
"""

import argparse
import os
import sys
import json
import textwrap
import shutil
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Optional YAML support (falls back to JSON if PyYAML not installed)
# ---------------------------------------------------------------------------
try:
    import yaml
    HAS_YAML = True
    def load_config_file(path):
        with open(path) as f:
            return yaml.safe_load(f)
except ImportError:
    HAS_YAML = False
    def load_config_file(path):
        with open(path) as f:
            return json.load(f)

# ---------------------------------------------------------------------------
# Color palette & constants
# ---------------------------------------------------------------------------
CHANNEL_COLORS = {
    "PDSCH":  "cyan",
    "PUSCH":  "green",
    "PDCCH":  "yellow",
    "PUCCH":  "orange",
    "PBCH":   "magenta",
    "SSB":    "white",
    "PRACH":  "red",
    "SRS":    "lightblue",
    "CSI_RS": "pink",
    "DMRS":   "lightgreen",
    "SFR":    "lightyellow",
    "CLK":    "gray",
    "CTRL":   "lightcyan",
    "FRAME":  "lightyellow",
}

RADIX_MAP = {
    "hex": "hex", "h": "hex",
    "bin": "bin", "b": "bin",
    "dec": "dec", "d": "dec",
    "oct": "oct", "o": "oct",
}

SCENARIOS = ["sfr-check", "timing", "compare", "edge-count", "frame-sync", "full"]

# ---------------------------------------------------------------------------
# Default built-in config (used when no -c is given)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "top": "tb.dut",
    "clock": "tb.clk",
    "reset": "tb.rst_n",
    "frame_sync": "tb.dut.sfn[9:0]",
    "subframe_sync": "tb.dut.subframe_idx[3:0]",
    "slot_sync": "tb.dut.slot_idx[4:0]",
    "symbol_sync": "tb.dut.sym_idx[3:0]",

    "channels": {
        "PDSCH": {
            "color": "cyan",
            "signals": [
                {"name": "en",     "path": "pdsch_dl_en",          "radix": "bin"},
                {"name": "vld",    "path": "pdsch_dl_vld",         "radix": "bin"},
                {"name": "data",   "path": "pdsch_dl_data[127:0]", "radix": "hex", "height": 30},
                {"name": "mcs",    "path": "pdsch_dl_mcs[4:0]",    "radix": "dec"},
                {"name": "rb_num", "path": "pdsch_dl_rb_num[6:0]", "radix": "dec"},
                {"name": "ack",    "path": "pdsch_dl_ack",         "radix": "bin"},
            ],
        },
        "PUSCH": {
            "color": "green",
            "signals": [
                {"name": "en",     "path": "pusch_ul_en",          "radix": "bin"},
                {"name": "vld",    "path": "pusch_ul_vld",         "radix": "bin"},
                {"name": "data",   "path": "pusch_ul_data[127:0]", "radix": "hex", "height": 30},
                {"name": "mcs",    "path": "pusch_ul_mcs[4:0]",    "radix": "dec"},
                {"name": "rb_num", "path": "pusch_ul_rb_num[6:0]", "radix": "dec"},
                {"name": "grant",  "path": "pusch_ul_grant",       "radix": "bin"},
            ],
        },
        "PDCCH": {
            "color": "yellow",
            "signals": [
                {"name": "en",     "path": "pdcch_dl_en",          "radix": "bin"},
                {"name": "vld",    "path": "pdcch_dl_vld",         "radix": "bin"},
                {"name": "dci",    "path": "pdcch_dl_dci[39:0]",   "radix": "hex"},
                {"name": "al",     "path": "pdcch_dl_al[2:0]",     "radix": "dec"},
            ],
        },
        "PUCCH": {
            "color": "orange",
            "signals": [
                {"name": "en",     "path": "pucch_ul_en",          "radix": "bin"},
                {"name": "vld",    "path": "pucch_ul_vld",         "radix": "bin"},
                {"name": "fmt",    "path": "pucch_ul_format[2:0]", "radix": "dec"},
                {"name": "sr",     "path": "pucch_ul_sr",          "radix": "bin"},
                {"name": "ack",    "path": "pucch_ul_ack[1:0]",    "radix": "bin"},
            ],
        },
        "PBCH": {
            "color": "magenta",
            "signals": [
                {"name": "en",     "path": "pbch_dl_en",           "radix": "bin"},
                {"name": "vld",    "path": "pbch_dl_vld",          "radix": "bin"},
                {"name": "mib",    "path": "pbch_dl_mib[23:0]",    "radix": "hex"},
            ],
        },
        "SSB": {
            "color": "white",
            "signals": [
                {"name": "en",     "path": "ssb_en",               "radix": "bin"},
                {"name": "vld",    "path": "ssb_vld",              "radix": "bin"},
                {"name": "idx",    "path": "ssb_idx[2:0]",         "radix": "dec"},
                {"name": "beam",   "path": "ssb_beam_id[5:0]",     "radix": "dec"},
            ],
        },
        "PRACH": {
            "color": "red",
            "signals": [
                {"name": "en",     "path": "prach_ul_en",          "radix": "bin"},
                {"name": "vld",    "path": "prach_ul_vld",         "radix": "bin"},
                {"name": "preamble","path":"prach_ul_preamble[5:0]","radix": "dec"},
                {"name": "ta",     "path": "prach_ul_ta[11:0]",    "radix": "dec"},
            ],
        },
        "SRS": {
            "color": "lightblue",
            "signals": [
                {"name": "en",     "path": "srs_ul_en",            "radix": "bin"},
                {"name": "vld",    "path": "srs_ul_vld",           "radix": "bin"},
                {"name": "bw",     "path": "srs_ul_bw[2:0]",       "radix": "dec"},
            ],
        },
    },

    "sfr": {
        "base_path": "tb.dut.sfr",
        "registers": {
            "PDSCH_CFG": {
                "path": "pdsch_cfg[31:0]",
                "fields": {
                    "EN":     "[0]",
                    "MCS":    "[5:1]",
                    "RB_NUM": "[11:6]",
                    "MIMO":   "[13:12]",
                    "HARQ":   "[15:14]",
                },
            },
            "PUSCH_CFG": {
                "path": "pusch_cfg[31:0]",
                "fields": {
                    "EN":     "[0]",
                    "MCS":    "[5:1]",
                    "RB_NUM": "[11:6]",
                    "BETA":   "[15:12]",
                },
            },
            "PDCCH_CFG": {
                "path": "pdcch_cfg[31:0]",
                "fields": {
                    "EN":     "[0]",
                    "AL":     "[3:1]",
                    "AGG":    "[7:4]",
                },
            },
            "TIMING_CFG": {
                "path": "timing_cfg[31:0]",
                "fields": {
                    "TA":       "[11:0]",
                    "N_TA_OFF": "[15:12]",
                    "TS_DELTA": "[23:16]",
                },
            },
            "CHAN_CTRL": {
                "path": "chan_ctrl[31:0]",
                "fields": {
                    "DL_EN":    "[0]",
                    "UL_EN":    "[1]",
                    "SSB_EN":   "[2]",
                    "PRACH_EN": "[3]",
                    "SRS_EN":   "[4]",
                    "RESET":    "[31]",
                },
            },
        },
    },

    "scenarios": {
        "sfr_check": {
            "max_latency_cycles": 16,
            "watch_sfr": ["PDSCH_CFG", "PUSCH_CFG", "PDCCH_CFG", "CHAN_CTRL"],
        },
        "timing": {
            "reference_channel": "PDSCH",
            "compare_channels":  ["PUSCH", "PDCCH", "SSB"],
            "time_unit": "ns",
        },
        "compare": {
            "mode": "multi-instance",   # "multi-instance" | "multi-fsdb"
            "instances": ["ch0", "ch1"],
            "signals_to_compare": ["pdsch_dl_data[127:0]", "pdsch_dl_vld"],
        },
        "edge_count": {
            "channels": ["PDSCH", "PUSCH", "PDCCH", "PUCCH"],
            "signal_key": "vld",
            "edge_type": "rising",
        },
        "frame_sync": {
            "lte_frame_ns":    10000000,
            "nr_subframe_ns":  500000,
            "nr_slot_ns":      125000,
            "num_frames":      4,
            "standard":        "NR",   # "LTE" | "NR"
        },
    },
}


# ===========================================================================
# RC File Generator
# ===========================================================================
class RcGenerator:
    """Generates nWave signal RC file (.rc) with groups, colors, radix."""

    def __init__(self, config: dict, fsdb_path: str):
        self.cfg = config
        self.fsdb = fsdb_path
        self.top = config.get("top", "tb.dut")
        self.lines = []

    def _sig(self, rel_path: str) -> str:
        """Return full signal path under top."""
        return f"{self.top}.{rel_path}"

    def _sfr(self, rel_path: str) -> str:
        """Return full SFR path."""
        base = self.cfg.get("sfr", {}).get("base_path", f"{self.top}.sfr")
        return f"{base}.{rel_path}"

    def w(self, line: str = ""):
        self.lines.append(line)

    def _add_signal(self, full_path: str, radix: str = "hex", height: int = None,
                    color: str = None, alias: str = None):
        self.w(f"wvAddSignal {{{full_path}}}")
        if radix:
            r = RADIX_MAP.get(radix.lower(), "hex")
            self.w(f"wvSetSignalRadix -radix {r} {{{full_path}}}")
        if color:
            self.w(f"wvSetSignalColor -color {color} {{{full_path}}}")
        if height:
            self.w(f"wvSetSignalHeight -height {height} {{{full_path}}}")
        if alias:
            self.w(f"wvSetSignalAlias -alias {{{alias}}} {{{full_path}}}")

    def _group_begin(self, name: str, color: str = ""):
        bg = f" -backgroundcolor {color}" if color else ""
        self.w(f"wvSetGroupBegin -name {{{name}}}{bg}")

    def _group_end(self):
        self.w("wvSetGroupEnd")

    def _separator(self, label: str = ""):
        self.w(f"wvAddSeparator -name {{{label}}}" if label else "wvAddSeparator")

    def _add_expression(self, name: str, expr: str, color: str = "red"):
        self.w(f"wvAddExprSignal -name {{{name}}} -color {color} -expr {{{expr}}}")

    # ------------------------------------------------------------------ #
    def generate(self) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.w(f"# ============================================================")
        self.w(f"# Verdi nWave Signal RC — LTE/NR Analysis")
        self.w(f"# Generated : {ts}")
        self.w(f"# FSDB      : {self.fsdb}")
        self.w(f"# ============================================================")
        self.w()

        # Open FSDB
        self.w(f"debImport -sv4 {{{self.fsdb}}}")
        self.w()

        # Clock / Reset / Frame sync group
        self._write_timing_group()

        # SFR registers group
        self._write_sfr_group()

        # Per-channel groups
        for ch_name, ch_cfg in self.cfg.get("channels", {}).items():
            self._write_channel_group(ch_name, ch_cfg)

        # Expression signals group
        self._write_expression_group()

        self.w()
        self.w("# Fit all signals in view")
        self.w("wvZoomFit")
        self.w()
        self.w("# ============================================================")
        self.w("# RC file end")
        self.w("# ============================================================")

        return "\n".join(self.lines)

    def _write_timing_group(self):
        self.w("# ----------------------------------------------------------")
        self.w("# Timing / Frame Sync signals")
        self.w("# ----------------------------------------------------------")
        self._group_begin("TIMING / FRAME", "lightyellow")

        clk = self.cfg.get("clock", "tb.clk")
        rst = self.cfg.get("reset", "tb.rst_n")
        frame  = self.cfg.get("frame_sync",    f"{self.top}.sfn[9:0]")
        subfrm = self.cfg.get("subframe_sync", f"{self.top}.subframe_idx[3:0]")
        slot   = self.cfg.get("slot_sync",     f"{self.top}.slot_idx[4:0]")
        sym    = self.cfg.get("symbol_sync",   f"{self.top}.sym_idx[3:0]")

        for path, radix in [(clk, "bin"), (rst, "bin"),
                            (frame, "dec"), (subfrm, "dec"),
                            (slot, "dec"), (sym, "dec")]:
            self._add_signal(path, radix=radix, color="gray")

        self._group_end()
        self.w()

    def _write_sfr_group(self):
        sfr_cfg = self.cfg.get("sfr", {})
        if not sfr_cfg:
            return

        self.w("# ----------------------------------------------------------")
        self.w("# SFR Registers")
        self.w("# ----------------------------------------------------------")
        self._group_begin("SFR REGISTERS", "lightyellow")

        for reg_name, reg_cfg in sfr_cfg.get("registers", {}).items():
            reg_path = self._sfr(reg_cfg["path"])
            self._add_signal(reg_path, radix="hex", color="yellow",
                             alias=reg_name)
            # Sub-fields
            for field_name, bits in reg_cfg.get("fields", {}).items():
                field_path = f"{reg_path}{bits}"
                self._add_signal(field_path, radix="dec",
                                 alias=f"  {reg_name}.{field_name}")

        self._group_end()
        self.w()

    def _write_channel_group(self, ch_name: str, ch_cfg: dict):
        color = ch_cfg.get("color", CHANNEL_COLORS.get(ch_name, "cyan"))

        self.w(f"# ----------------------------------------------------------")
        self.w(f"# Channel: {ch_name}")
        self.w(f"# ----------------------------------------------------------")
        self._group_begin(ch_name, color)

        for sig in ch_cfg.get("signals", []):
            full_path = self._sig(sig["path"])
            self._add_signal(
                full_path,
                radix=sig.get("radix", "hex"),
                height=sig.get("height"),
                color=color,
                alias=f"{ch_name}.{sig['name']}",
            )

        # Multi-instance: add all instances
        instances = ch_cfg.get("instances", [])
        if instances:
            self._separator(f"{ch_name} instances")
            for inst in instances:
                for sig in ch_cfg.get("signals", []):
                    full_path = f"{self.top}.{inst}.{sig['path']}"
                    self._add_signal(
                        full_path,
                        radix=sig.get("radix", "hex"),
                        color=color,
                        alias=f"{ch_name}[{inst}].{sig['name']}",
                    )

        self._group_end()
        self.w()

    def _write_expression_group(self):
        self.w("# ----------------------------------------------------------")
        self.w("# Derived / Expression Signals")
        self.w("# ----------------------------------------------------------")
        self._group_begin("EXPRESSIONS", "pink")

        top = self.top
        # DL/UL concurrent active
        self._add_expression(
            "DL_UL_concurrent",
            f"{top}.pdsch_dl_en & {top}.pusch_ul_en",
            color="red",
        )
        # Any channel active
        self._add_expression(
            "any_chan_active",
            f"{top}.pdsch_dl_en | {top}.pusch_ul_en | "
            f"{top}.pdcch_dl_en | {top}.pucch_ul_en",
            color="orange",
        )
        # PDSCH data valid gated
        self._add_expression(
            "PDSCH_valid_data",
            f"{top}.pdsch_dl_vld & {top}.pdsch_dl_en",
            color="cyan",
        )
        # SFR change detect (multi-bit change any)
        self._add_expression(
            "sfr_chan_ctrl_changed",
            f"$changed({self._sfr('chan_ctrl[31:0]')})",
            color="yellow",
        )

        self._group_end()
        self.w()


# ===========================================================================
# TCL Scenario Generators
# ===========================================================================
class TclScenario:
    """Base class for TCL scenario scripts."""

    def __init__(self, config: dict, fsdb_path: str, rc_path: str,
                 output_dir: str, ref_fsdb: str = None):
        self.cfg = config
        self.fsdb = fsdb_path
        self.rc = rc_path
        self.out_dir = output_dir
        self.ref_fsdb = ref_fsdb
        self.top = config.get("top", "tb.dut")
        self.lines = []

    def _sig(self, rel_path: str) -> str:
        return f"{self.top}.{rel_path}"

    def _sfr(self, rel_path: str) -> str:
        base = self.cfg.get("sfr", {}).get("base_path", f"{self.top}.sfr")
        return f"{base}.{rel_path}"

    def w(self, line: str = ""):
        self.lines.append(line)

    def _header(self, scenario_name: str, description: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.w(f"# ============================================================")
        self.w(f"# Verdi nWave TCL — {scenario_name}")
        self.w(f"# {description}")
        self.w(f"# Generated : {ts}")
        self.w(f"# FSDB      : {self.fsdb}")
        self.w(f"# ============================================================")
        self.w()
        self.w(f"set report_dir {{{self.out_dir}}}")
        self.w(f"set fsdb_file  {{{self.fsdb}}}")
        self.w()

    def _load_rc(self):
        self.w(f"# Load signal RC (groups, colors, expressions)")
        self.w(f"source {{{self.rc}}}")
        self.w()

    def _proc_header(self, proc_name: str, description: str, args: str = ""):
        self.w(f"# ----------------------------------------------------------")
        self.w(f"# PROC: {proc_name} — {description}")
        self.w(f"# ----------------------------------------------------------")
        self.w(f"proc {proc_name} {{{args}}} {{")

    def _proc_footer(self):
        self.w("}")
        self.w()

    def generate(self) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
class SfrCheckScenario(TclScenario):
    """
    Scenario: sfr-check
    Detects SFR write events and measures latency to channel response signals.
    Creates markers at each SFR write and measures cycles to first channel output.
    """

    def generate(self) -> str:
        sc = self.cfg.get("scenarios", {}).get("sfr_check", {})
        max_lat = sc.get("max_latency_cycles", 16)
        watch_sfr = sc.get("watch_sfr", ["CHAN_CTRL", "PDSCH_CFG"])
        sfr_regs = self.cfg.get("sfr", {}).get("registers", {})

        self._header("SFR-CHECK",
                     "Measure latency from SFR write to channel output response")
        self._load_rc()

        # Helper procs
        self.w("# ----------------------------------------------------------")
        self.w("# Utility procs")
        self.w("# ----------------------------------------------------------")
        self.w()

        self._proc_header("mark_sfr_writes",
                          "Scan for SFR value changes and place markers",
                          "sfr_signal marker_prefix")
        self.w("    set cur_time [nwGetMinTime]")
        self.w("    set end_time [nwGetMaxTime]")
        self.w("    set mark_cnt 0")
        self.w("    while {$cur_time < $end_time} {")
        self.w("        set next [nwSearchNext -signal $sfr_signal \\")
        self.w("                              -type value_change \\")
        self.w("                              -from $cur_time]")
        self.w("        if {$next == \"\"} break")
        self.w("        set val [nwGetValue -signal $sfr_signal -time $next]")
        self.w("        nwAddMarker -time $next \\")
        self.w("                    -name \"${marker_prefix}_${mark_cnt}(${val})\" \\")
        self.w("                    -color yellow")
        self.w("        incr mark_cnt")
        self.w("        set cur_time [expr {$next + 1}]")
        self.w("    }")
        self.w("    return $mark_cnt")
        self._proc_footer()

        self._proc_header("measure_sfr_to_response",
                          "Measure latency from SFR change to response signal assertion",
                          "sfr_sig resp_sig max_cycles clk_period report_fd")
        self.w("    set results {}")
        self.w("    set cur_time [nwGetMinTime]")
        self.w("    set end_time [nwGetMaxTime]")
        self.w("    while {$cur_time < $end_time} {")
        self.w("        # Find next SFR value change")
        self.w("        set sfr_t [nwSearchNext -signal $sfr_sig \\")
        self.w("                               -type value_change -from $cur_time]")
        self.w("        if {$sfr_t == \"\"} break")
        self.w("        set sfr_val [nwGetValue -signal $sfr_sig -time $sfr_t]")
        self.w(f"        set search_end [expr {{$sfr_t + $max_cycles * $clk_period}}]")
        self.w("        # Find response signal rising edge within window")
        self.w("        set resp_t [nwSearchNext -signal $resp_sig \\")
        self.w("                                -type rising_edge   \\")
        self.w("                                -from $sfr_t        \\")
        self.w("                                -to   $search_end]")
        self.w("        if {$resp_t != \"\"} {")
        self.w("            set lat_ps  [expr {$resp_t - $sfr_t}]")
        self.w("            set lat_cyc [expr {$lat_ps / $clk_period}]")
        self.w("            puts $report_fd \"SFR_CHANGE @ ${sfr_t}ps  val=${sfr_val}  \"\\")
        self.w("                            \"resp @ ${resp_t}ps  latency=${lat_cyc} cycles\"")
        self.w("            # Color-code: green if within spec, red if over")
        self.w(f"            if {{$lat_cyc <= {max_lat}}} {{")
        self.w("                nwSetSignalColor -color green $resp_sig")
        self.w("            } else {")
        self.w("                nwSetSignalColor -color red $resp_sig")
        self.w("                puts $report_fd \"  *** LATENCY VIOLATION: ${lat_cyc} > "
               f"{max_lat} ***\"")
        self.w("            }")
        self.w("        } else {")
        self.w("            puts $report_fd \"SFR_CHANGE @ ${sfr_t}ps  val=${sfr_val}  \"\\")
        self.w("                            \"NO RESPONSE within window\"")
        self.w("        }")
        self.w("        set cur_time [expr {$sfr_t + 1}]")
        self.w("    }")
        self._proc_footer()

        # Main execution
        self.w("# ----------------------------------------------------------")
        self.w("# Main: SFR-Check Analysis")
        self.w("# ----------------------------------------------------------")
        self.w()
        self.w(f"set clk_period [nwGetClockPeriod {{{self.cfg.get('clock', 'tb.clk')}}}]")
        self.w(f"set rpt_path   {{$report_dir/sfr_check_report.txt}}")
        self.w(f"set rpt_fd     [open $rpt_path w]")
        self.w(f"puts $rpt_fd \"SFR-Check Report — [clock format [clock seconds]]\"")
        self.w(f"puts $rpt_fd \"FSDB: $fsdb_file\"")
        self.w(f"puts $rpt_fd \"{'='*60}\"")
        self.w()

        # Iterate watched SFRs
        for reg_name in watch_sfr:
            if reg_name in sfr_regs:
                reg_path = self._sfr(sfr_regs[reg_name]["path"])
                # Determine response signal for this SFR
                resp_map = {
                    "PDSCH_CFG":  self._sig("pdsch_dl_en"),
                    "PUSCH_CFG":  self._sig("pusch_ul_en"),
                    "PDCCH_CFG":  self._sig("pdcch_dl_en"),
                    "CHAN_CTRL":  self._sig("pdsch_dl_en"),
                    "TIMING_CFG": self._sig("pdsch_dl_vld"),
                }
                resp = resp_map.get(reg_name, self._sig("pdsch_dl_en"))

                self.w(f"# --- {reg_name} ---")
                self.w(f"puts $rpt_fd \"\"")
                self.w(f"puts $rpt_fd \"[SFR: {reg_name}] path: {reg_path}\"")
                self.w(f"mark_sfr_writes {{{reg_path}}} {{{reg_name}}}")
                self.w(f"measure_sfr_to_response \\")
                self.w(f"    {{{reg_path}}} \\")
                self.w(f"    {{{resp}}} \\")
                self.w(f"    {max_lat} $clk_period $rpt_fd")
                self.w()

        self.w("close $rpt_fd")
        self.w("puts \"SFR-Check report written to: $rpt_path\"")

        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
class TimingScenario(TclScenario):
    """
    Scenario: timing
    Inter-channel timing alignment analysis.
    Measures delta time between channel en/vld edges using reference channel.
    """

    def generate(self) -> str:
        sc = self.cfg.get("scenarios", {}).get("timing", {})
        ref_ch    = sc.get("reference_channel", "PDSCH")
        cmp_chs   = sc.get("compare_channels",  ["PUSCH", "PDCCH"])
        time_unit = sc.get("time_unit", "ns")

        self._header("TIMING", "Inter-channel timing alignment & delta analysis")
        self._load_rc()

        ch_cfg = self.cfg.get("channels", {})

        def en_sig(ch):
            sigs = ch_cfg.get(ch, {}).get("signals", [])
            for s in sigs:
                if s["name"] == "en":
                    return self._sig(s["path"])
            return f"{self.top}.{ch.lower()}_en"

        def vld_sig(ch):
            sigs = ch_cfg.get(ch, {}).get("signals", [])
            for s in sigs:
                if s["name"] == "vld":
                    return self._sig(s["path"])
            return f"{self.top}.{ch.lower()}_vld"

        # Proc: measure_delta
        self._proc_header("measure_delta",
                          "Measure time delta between rising edges of two signals",
                          "sig_a sig_b label report_fd")
        self.w("    set ref_t   [nwSearchNext -signal $sig_a -type rising_edge \\")
        self.w("                              -from [nwGetMinTime]]")
        self.w("    if {$ref_t == \"\"} {")
        self.w("        puts $report_fd \"  $label: no edge found in $sig_a\"")
        self.w("        return")
        self.w("    }")
        self.w("    set cmp_t   [nwSearchNext -signal $sig_b -type rising_edge \\")
        self.w("                              -from [nwGetMinTime]]")
        self.w("    if {$cmp_t == \"\"} {")
        self.w("        puts $report_fd \"  $label: no edge found in $sig_b\"")
        self.w("        return")
        self.w("    }")
        self.w("    set delta [expr {$cmp_t - $ref_t}]")
        self.w("    set sign  [expr {$delta >= 0 ? \"+\" : \"\"}]")
        self.w(f"    set scale [expr {{1.0 / [nwGetTimeUnit \"{time_unit}\"]}}]")
        self.w(f"    set delta_ns [expr {{$delta * $scale}}]")
        self.w("    puts $report_fd \"  $label: delta = ${sign}${delta_ns} {time_unit}\"")
        self.w("    nwAddMarker -time $ref_t -name \"REF_${label}\" -color green")
        self.w("    nwAddMarker -time $cmp_t -name \"CMP_${label}\" -color orange")
        self._proc_footer()

        # Proc: check_simultaneous
        self._proc_header("check_simultaneous",
                          "Verify two channels are active at the same time",
                          "sig_a sig_b tolerance_ps report_fd")
        self.w("    set cur [nwGetMinTime]")
        self.w("    set violations 0")
        self.w("    while {$cur < [nwGetMaxTime]} {")
        self.w("        set ta [nwSearchNext -signal $sig_a -type rising_edge -from $cur]")
        self.w("        if {$ta == \"\"} break")
        self.w("        set tb [nwSearchNext -signal $sig_b -type rising_edge \\")
        self.w("                             -from [expr {$ta - $tolerance_ps}] \\")
        self.w("                             -to   [expr {$ta + $tolerance_ps}]]")
        self.w("        if {$tb == \"\"} {")
        self.w("            puts $report_fd \"  ALIGN FAIL @ ${ta}ps : $sig_a active, $sig_b not within tolerance\"")
        self.w("            nwAddMarker -time $ta -name \"ALIGN_FAIL\" -color red")
        self.w("            incr violations")
        self.w("        }")
        self.w("        set cur [expr {$ta + 1}]")
        self.w("    }")
        self.w("    return $violations")
        self._proc_footer()

        # Main
        self.w("# ----------------------------------------------------------")
        self.w("# Main: Timing Analysis")
        self.w("# ----------------------------------------------------------")
        self.w()
        self.w(f"set clk_period [nwGetClockPeriod {{{self.cfg.get('clock', 'tb.clk')}}}]")
        self.w(f"set tolerance  [expr {{$clk_period * 2}}]")
        self.w(f"set rpt_path   {{$report_dir/timing_report.txt}}")
        self.w(f"set rpt_fd     [open $rpt_path w]")
        self.w(f"puts $rpt_fd \"Timing Analysis Report — [clock format [clock seconds]]\"")
        self.w(f"puts $rpt_fd \"Reference channel: {ref_ch}\"")
        self.w(f"puts $rpt_fd \"{'='*60}\"")
        self.w()
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"=== Enable Signal Deltas (vs {ref_ch}) ===\"")
        ref_en = en_sig(ref_ch)
        for ch in cmp_chs:
            cmp_en = en_sig(ch)
            self.w(f"measure_delta {{{ref_en}}} {{{cmp_en}}} {{{ref_ch}_vs_{ch}_en}} $rpt_fd")
        self.w()
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"=== Valid Signal Deltas (vs {ref_ch}) ===\"")
        ref_vld = vld_sig(ref_ch)
        for ch in cmp_chs:
            cmp_vld = vld_sig(ch)
            self.w(f"measure_delta {{{ref_vld}}} {{{cmp_vld}}} {{{ref_ch}_vs_{ch}_vld}} $rpt_fd")
        self.w()
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"=== Simultaneous Alignment Check ===\"")
        for ch in cmp_chs:
            self.w(f"set v [check_simultaneous {{{ref_en}}} {{{en_sig(ch)}}} $tolerance $rpt_fd]")
            self.w(f"puts $rpt_fd \"  {ref_ch}↔{ch}: $v violations\"")
        self.w()
        self.w("close $rpt_fd")
        self.w("puts \"Timing report written to: $rpt_path\"")

        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
class CompareScenario(TclScenario):
    """
    Scenario: compare
    Multi-instance or multi-FSDB signal comparison with XOR mismatch detection.
    """

    def generate(self) -> str:
        sc = self.cfg.get("scenarios", {}).get("compare", {})
        mode     = sc.get("mode", "multi-instance")
        instances = sc.get("instances", ["ch0", "ch1"])
        sigs_to_cmp = sc.get("signals_to_compare",
                             ["pdsch_dl_data[127:0]", "pdsch_dl_vld"])

        self._header("COMPARE",
                     f"Signal comparison ({mode}): mismatch detection & reporting")
        self._load_rc()

        if mode == "multi-fsdb" and self.ref_fsdb:
            self.w(f"# Load reference FSDB as overlay")
            self.w(f"debImport -sv4 {{{self.ref_fsdb}}} -overlay")
            self.w()

        # Proc: add_xor_mismatch
        self._proc_header("add_xor_mismatch",
                          "Add XOR expression signal for two paths and count mismatches",
                          "path_a path_b expr_name")
        self.w("    wvAddExprSignal -name $expr_name \\")
        self.w("                    -color red \\")
        self.w("                    -expr \"($path_a) ^ ($path_b)\"")
        self.w("    # Count how many time steps the XOR is non-zero")
        self.w("    set mismatch_cnt 0")
        self.w("    set cur [nwGetMinTime]")
        self.w("    while {$cur < [nwGetMaxTime]} {")
        self.w("        set next [nwSearchNext -signal $expr_name \\")
        self.w("                               -value {?*[^0]*} \\")
        self.w("                               -type value_change -from $cur]")
        self.w("        if {$next == \"\"} break")
        self.w("        set val [nwGetValue -signal $expr_name -time $next]")
        self.w("        nwAddMarker -time $next -name \"MISMATCH_${expr_name}\" \\")
        self.w("                    -color red")
        self.w("        incr mismatch_cnt")
        self.w("        set cur [expr {$next + 1}]")
        self.w("    }")
        self.w("    return $mismatch_cnt")
        self._proc_footer()

        # Proc: compare_instance_pair
        self._proc_header("compare_instance_pair",
                          "Compare all configured signals between two instances",
                          "inst_a inst_b report_fd")
        self.w("    global top")
        for sig_path in sigs_to_cmp:
            base_name = sig_path.replace("[", "_").replace("]", "").replace(":", "_")
            self.w(f"    set pa {{$top.$inst_a.{sig_path}}}")
            self.w(f"    set pb {{$top.$inst_b.{sig_path}}}")
            self.w(f"    set expr_nm {{xor_{base_name}_a_vs_b}}")
            self.w(f"    set n [add_xor_mismatch $pa $pb $expr_nm]")
            self.w(f"    puts $report_fd \"  {sig_path}: $n mismatch events\"")
        self._proc_footer()

        # Main
        self.w("# ----------------------------------------------------------")
        self.w("# Main: Compare Analysis")
        self.w("# ----------------------------------------------------------")
        self.w()
        self.w(f"set top {{{self.top}}}")
        self.w(f"set rpt_path {{$report_dir/compare_report.txt}}")
        self.w(f"set rpt_fd   [open $rpt_path w]")
        self.w(f"puts $rpt_fd \"Compare Report ({mode}) — [clock format [clock seconds]]\"")
        self.w(f"puts $rpt_fd \"{'='*60}\"")
        self.w()

        if mode == "multi-instance":
            for i in range(len(instances) - 1):
                inst_a = instances[i]
                inst_b = instances[i + 1]
                self.w(f"puts $rpt_fd \"\"")
                self.w(f"puts $rpt_fd \"=== {inst_a} vs {inst_b} ===\"")
                self.w(f"compare_instance_pair {{{inst_a}}} {{{inst_b}}} $rpt_fd")
        elif mode == "multi-fsdb" and self.ref_fsdb:
            self.w(f"puts $rpt_fd \"Reference FSDB: {self.ref_fsdb}\"")
            self.w(f"puts $rpt_fd \"\"")
            for sig_path in sigs_to_cmp:
                base = sig_path.replace("[", "_").replace("]", "").replace(":", "_")
                self.w(f"set pa {{{self.top}.{sig_path}}}")
                self.w(f"set pb {{ref.{self.top}.{sig_path}}}")
                self.w(f"set n [add_xor_mismatch $pa $pb xor_{base}]")
                self.w(f"puts $rpt_fd \"  {sig_path}: $n mismatch events (sim vs ref)\"")
        self.w()
        self.w("close $rpt_fd")
        self.w("puts \"Compare report written to: $rpt_path\"")

        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
class EdgeCountScenario(TclScenario):
    """
    Scenario: edge-count
    Edge/toggle count statistics per channel signal.
    """

    def generate(self) -> str:
        sc = self.cfg.get("scenarios", {}).get("edge_count", {})
        channels  = sc.get("channels", ["PDSCH", "PUSCH", "PDCCH"])
        sig_key   = sc.get("signal_key", "vld")
        edge_type = sc.get("edge_type", "rising")
        ch_cfg    = self.cfg.get("channels", {})

        self._header("EDGE-COUNT",
                     "Edge/toggle count statistics per channel")
        self._load_rc()

        # Proc: count_edges
        self._proc_header("count_edges",
                          "Count edges of given type in signal across full simulation",
                          "sig edge_type")
        self.w("    set cnt   0")
        self.w("    set cur   [nwGetMinTime]")
        self.w("    set end   [nwGetMaxTime]")
        self.w("    while {$cur < $end} {")
        self.w("        set t [nwSearchNext -signal $sig \\")
        self.w("                            -type   ${edge_type}_edge \\")
        self.w("                            -from   $cur]")
        self.w("        if {$t == \"\"} break")
        self.w("        incr cnt")
        self.w("        set cur [expr {$t + 1}]")
        self.w("    }")
        self.w("    return $cnt")
        self._proc_footer()

        # Proc: channel_stats
        self._proc_header("channel_stats",
                          "Print edge count and duty cycle for a signal",
                          "sig ch_name report_fd")
        self.w("    set rise [count_edges $sig rising]")
        self.w("    set fall [count_edges $sig falling]")
        self.w("    set total_time [expr {[nwGetMaxTime] - [nwGetMinTime]}]")
        self.w("    # Calculate high time (approximate by sampling)")
        self.w("    puts $report_fd [format \"  %-20s  rise=%-6d  fall=%-6d  total_toggle=%-6d\" \\")
        self.w("                    $ch_name $rise $fall [expr {$rise + $fall}]]")
        self._proc_footer()

        # Main
        self.w("# ----------------------------------------------------------")
        self.w("# Main: Edge Count Analysis")
        self.w("# ----------------------------------------------------------")
        self.w()
        self.w(f"set clk       {{{self.cfg.get('clock', 'tb.clk')}}}")
        self.w(f"set rpt_path  {{$report_dir/edge_count_report.txt}}")
        self.w(f"set rpt_fd    [open $rpt_path w]")
        self.w(f"puts $rpt_fd \"Edge Count Report — [clock format [clock seconds]]\"")
        self.w(f"puts $rpt_fd \"Edge type: {edge_type}  Signal key: {sig_key}\"")
        self.w(f"puts $rpt_fd \"{'='*60}\"")
        self.w()

        # Clock reference
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"Clock reference:\"")
        self.w(f"set clk_cnt [count_edges $clk rising]")
        self.w(f"puts $rpt_fd [format \"  %-20s  rise=%-6d  (= simulation length in cycles)\" \\")
        self.w(f"             {{CLK}} $clk_cnt]")
        self.w()
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"Channel statistics ({sig_key} signal):\"")

        for ch_name in channels:
            sigs = ch_cfg.get(ch_name, {}).get("signals", [])
            match = next((s for s in sigs if s["name"] == sig_key), None)
            if match:
                full_path = self._sig(match["path"])
                self.w(f"channel_stats {{{full_path}}} {{{ch_name}}} $rpt_fd")
            else:
                self.w(f"# Warning: signal key '{sig_key}' not found in {ch_name}")

        self.w()
        self.w(f"puts $rpt_fd \"\"")
        self.w(f"puts $rpt_fd \"Any-channel-active toggle count:\"")
        self.w(f"channel_stats {{any_chan_active}} {{ANY_CHAN}} $rpt_fd")
        self.w()
        self.w("close $rpt_fd")
        self.w("puts \"Edge-count report written to: $rpt_path\"")

        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
class FrameSyncScenario(TclScenario):
    """
    Scenario: frame-sync
    Generate LTE/NR frame/subframe/slot boundary markers.
    """

    def generate(self) -> str:
        sc = self.cfg.get("scenarios", {}).get("frame_sync", {})
        frame_ns  = sc.get("lte_frame_ns",   10_000_000)
        subfrm_ns = sc.get("nr_subframe_ns",    500_000)
        slot_ns   = sc.get("nr_slot_ns",        125_000)
        num_frames = sc.get("num_frames", 4)
        standard  = sc.get("standard", "NR")

        self._header("FRAME-SYNC",
                     f"{standard} frame/subframe/slot boundary marker generation")
        self._load_rc()

        self.w("# ----------------------------------------------------------")
        self.w(f"# {standard} Frame Structure")
        self.w(f"# Frame   = {frame_ns/1e6:.3f} ms  ({frame_ns} ns)")
        self.w(f"# Subframe = {subfrm_ns/1e3:.3f} us  ({subfrm_ns} ns)")
        self.w(f"# Slot     = {slot_ns/1e3:.3f} us  ({slot_ns} ns)")
        self.w("# ----------------------------------------------------------")
        self.w()

        # Proc: add_frame_markers
        self._proc_header("add_frame_markers",
                          "Place frame boundary markers starting at sim time 0",
                          "frame_ns subframe_ns slot_ns num_frames unit_ps")
        self.w("    set frame_ps    [expr {$frame_ns    * $unit_ps}]")
        self.w("    set subframe_ps [expr {$subframe_ns * $unit_ps}]")
        self.w("    set slot_ps     [expr {$slot_ns     * $unit_ps}]")
        self.w("    set max_time    [nwGetMaxTime]")
        self.w("    set frame_start [nwGetMinTime]")
        self.w("    for {set fn 0} {$fn < $num_frames} {incr fn} {")
        self.w("        set t_frame [expr {$frame_start + $fn * $frame_ps}]")
        self.w("        if {$t_frame > $max_time} break")
        self.w("        nwAddMarker -time $t_frame -name \"FRAME_${fn}\" \\")
        self.w("                    -color white")
        self.w("        # Subframes within frame")
        self.w("        set sf_per_frame [expr {$frame_ps / $subframe_ps}]")
        self.w("        for {set sf 0} {$sf < $sf_per_frame} {incr sf} {")
        self.w("            set t_sf [expr {$t_frame + $sf * $subframe_ps}]")
        self.w("            if {$sf > 0} {")
        self.w("                nwAddMarker -time $t_sf \\")
        self.w("                            -name \"F${fn}_SF${sf}\" \\")
        self.w("                            -color cyan")
        self.w("            }")
        self.w("            # Slots within subframe")
        self.w("            set slots_per_sf [expr {$subframe_ps / $slot_ps}]")
        self.w("            for {set sl 0} {$sl < $slots_per_sf} {incr sl} {")
        self.w("                set t_sl [expr {$t_sf + $sl * $slot_ps}]")
        self.w("                if {$sl > 0} {")
        self.w("                    nwAddMarker -time $t_sl \\")
        self.w("                                -name \"F${fn}_SF${sf}_SL${sl}\" \\")
        self.w("                                -color gray")
        self.w("                }")
        self.w("            }")
        self.w("        }")
        self.w("    }")
        self._proc_footer()

        # Proc: snap_to_frame
        self._proc_header("snap_to_frame",
                          "Zoom display to one frame starting from current cursor",
                          "frame_ns unit_ps")
        self.w("    set cur      [nwGetCursorTime]")
        self.w("    set frame_ps [expr {$frame_ns * $unit_ps}]")
        self.w("    nwZoom -from $cur -to [expr {$cur + $frame_ps}]")
        self._proc_footer()

        # Proc: check_frame_alignment
        self._proc_header("check_frame_alignment",
                          "Verify channel signals assert at frame/subframe boundaries",
                          "chan_sig frame_ns tolerance_ps unit_ps report_fd")
        self.w("    set frame_ps [expr {$frame_ns * $unit_ps}]")
        self.w("    set cur      [nwGetMinTime]")
        self.w("    set violations 0")
        self.w("    while {$cur < [nwGetMaxTime]} {")
        self.w("        set t [nwSearchNext -signal $chan_sig -type rising_edge -from $cur]")
        self.w("        if {$t == \"\"} break")
        self.w("        set offset [expr {$t % $frame_ps}]")
        self.w("        set tol $tolerance_ps")
        self.w("        if {$offset > $tol && $offset < ($frame_ps - $tol)} {")
        self.w("            puts $report_fd \"  FRAME_ALIGN_FAIL @ ${t}ps : offset=${offset}ps from frame boundary\"")
        self.w("            nwAddMarker -time $t -name \"FRAME_FAIL\" -color red")
        self.w("            incr violations")
        self.w("        }")
        self.w("        set cur [expr {$t + 1}]")
        self.w("    }")
        self.w("    return $violations")
        self._proc_footer()

        # Main
        self.w("# ----------------------------------------------------------")
        self.w("# Main: Frame Sync")
        self.w("# ----------------------------------------------------------")
        self.w()
        self.w(f"# Time unit conversion: 1 ns = ? ps (depends on simulation timescale)")
        self.w(f"set unit_ps 1000   ;# assume ns timescale → 1 ns = 1000 ps")
        self.w()
        self.w(f"add_frame_markers {frame_ns} {subfrm_ns} {slot_ns} {num_frames} $unit_ps")
        self.w()
        self.w(f"set rpt_path {{$report_dir/frame_sync_report.txt}}")
        self.w(f"set rpt_fd   [open $rpt_path w]")
        self.w(f"puts $rpt_fd \"Frame-Sync Report ({standard}) — [clock format [clock seconds]]\"")
        self.w(f"puts $rpt_fd \"Frame={frame_ns}ns  Subframe={subfrm_ns}ns  Slot={slot_ns}ns\"")
        self.w(f"puts $rpt_fd \"{'='*60}\"")
        self.w()

        ch_cfg = self.cfg.get("channels", {})
        for ch_name in ["PDSCH", "PUSCH", "SSB", "PRACH"]:
            sigs = ch_cfg.get(ch_name, {}).get("signals", [])
            en_sig = next((self._sig(s["path"]) for s in sigs if s["name"] == "en"), None)
            if en_sig:
                tol_ps = 1000  # 1 ns tolerance
                self.w(f"set v [check_frame_alignment {{{en_sig}}} {frame_ns} {tol_ps} $unit_ps $rpt_fd]")
                self.w(f"puts $rpt_fd \"  {ch_name}_en: $v frame-alignment violations\"")
        self.w()
        self.w("close $rpt_fd")
        self.w("puts \"Frame-sync report written to: $rpt_path\"")
        self.w()
        self.w(f"# Zoom to first frame")
        self.w(f"snap_to_frame {frame_ns} $unit_ps")

        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
class FullScenario(TclScenario):
    """Runs all scenarios by sourcing each generated TCL file."""

    def generate(self, tcl_files: dict) -> str:
        self._header("FULL", "All scenarios: sfr-check + timing + compare + edge-count + frame-sync")
        self.w(f"# Source all scenario scripts")
        self.w()
        for sc_name, tcl_path in tcl_files.items():
            self.w(f"# --- {sc_name} ---")
            self.w(f"catch {{source {{{tcl_path}}}}} err")
            self.w(f"if {{$err ne {{}}}} {{")
            self.w(f"    puts \"WARNING: {sc_name} error: $err\"")
            self.w(f"}}")
            self.w()
        self.w("puts \"Full analysis complete. Reports in: $report_dir\"")
        return "\n".join(self.lines)


# ===========================================================================
# Orchestrator
# ===========================================================================
class VerdiWaveTool:
    SCENARIO_CLASS = {
        "sfr-check":  SfrCheckScenario,
        "timing":     TimingScenario,
        "compare":    CompareScenario,
        "edge-count": EdgeCountScenario,
        "frame-sync": FrameSyncScenario,
    }

    def __init__(self, args):
        self.args = args
        self.fsdb = str(Path(args.fsdb).resolve())
        self.out_dir = Path(args.output_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = self._load_config()

    def _load_config(self) -> dict:
        if self.args.config:
            cfg = load_config_file(self.args.config)
            print(f"[+] Config loaded: {self.args.config}")
        else:
            cfg = DEFAULT_CONFIG
            print("[+] Using built-in default LTE/NR config")

        # CLI overrides
        if self.args.top:
            cfg["top"] = self.args.top
        if self.args.clock:
            cfg["clock"] = self.args.clock

        return cfg

    def _rc_path(self) -> Path:
        return self.out_dir / "signals.rc"

    def _tcl_path(self, scenario: str) -> Path:
        return self.out_dir / f"scenario_{scenario.replace('-','_')}.tcl"

    def run(self):
        scenario = self.args.scenario

        # Generate RC file (always)
        rc_gen = RcGenerator(self.cfg, self.fsdb)
        rc_content = rc_gen.generate()
        rc_path = self._rc_path()
        rc_path.write_text(rc_content)
        print(f"[+] RC file      : {rc_path}")

        # Generate TCL scenarios
        tcl_files = {}
        scenarios_to_run = (SCENARIOS[:-1] if scenario == "full"
                            else [scenario])

        for sc in scenarios_to_run:
            cls = self.SCENARIO_CLASS[sc]
            gen = cls(
                config=self.cfg,
                fsdb_path=self.fsdb,
                rc_path=str(rc_path),
                output_dir=str(self.out_dir),
                ref_fsdb=getattr(self.args, "ref_fsdb", None),
            )
            tcl_content = gen.generate()
            tcl_path = self._tcl_path(sc)
            tcl_path.write_text(tcl_content)
            tcl_files[sc] = str(tcl_path)
            print(f"[+] TCL [{sc:12s}]: {tcl_path}")

        # Generate full wrapper if needed
        if scenario == "full":
            full_gen = FullScenario(self.cfg, self.fsdb, str(rc_path),
                                    str(self.out_dir))
            full_content = full_gen.generate(tcl_files)
            full_path = self._tcl_path("full")
            full_path.write_text(full_content)
            print(f"[+] TCL [full        ]: {full_path}")
            main_tcl = full_path
        else:
            main_tcl = self._tcl_path(scenario)

        # Print launch command
        self._print_launch_cmd(main_tcl)

        # Auto-launch if requested
        if self.args.launch:
            self._launch_verdi(main_tcl)

    def _print_launch_cmd(self, main_tcl: Path):
        cmd = self._build_verdi_cmd(main_tcl)
        print()
        print("=" * 60)
        print("Launch command:")
        print(f"  {cmd}")
        print("=" * 60)

    def _build_verdi_cmd(self, main_tcl: Path) -> str:
        parts = ["verdi"]
        parts += ["-ssf", self.fsdb]
        parts += ["-rcFile", str(self._rc_path())]
        parts += ["-play",   str(main_tcl)]
        if self.args.novas:
            parts.insert(0, "novas")
        return " ".join(parts)

    def _launch_verdi(self, main_tcl: Path):
        import subprocess
        cmd = self._build_verdi_cmd(main_tcl)
        print(f"\n[+] Launching: {cmd}")
        subprocess.run(cmd, shell=True)


# ===========================================================================
# CLI
# ===========================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verdi_wave_tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Verdi nWave Tool for LTE/NR Waveform Analysis
            Generates signal RC and TCL analysis scripts.
        """),
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s -f sim.fsdb
              %(prog)s -f sim.fsdb -s sfr-check
              %(prog)s -f sim.fsdb -s compare --ref ref.fsdb
              %(prog)s -f sim.fsdb -s full -c my_config.yaml --launch
              %(prog)s -f sim.fsdb -s frame-sync --top tb.bench.dut
        """),
    )

    p.add_argument("-f",  "--fsdb",       default=None,
                   help="Input FSDB file path")
    p.add_argument("-s",  "--scenario",   default="full",
                   choices=SCENARIOS,
                   help="Analysis scenario (default: full)")
    p.add_argument("-c",  "--config",     default=None,
                   help="YAML/JSON config file (default: built-in LTE/NR)")
    p.add_argument("-o",  "--output-dir", default="./verdi_out",
                   help="Output directory for RC/TCL files (default: ./verdi_out)")
    p.add_argument("--ref",              dest="ref_fsdb", default=None,
                   help="Reference FSDB for compare scenario")
    p.add_argument("--top",              default=None,
                   help="Override top-level DUT path (e.g. tb.u_dut)")
    p.add_argument("--clock",            default=None,
                   help="Override clock signal path")
    p.add_argument("--launch",           action="store_true",
                   help="Auto-launch Verdi after generating files")
    p.add_argument("--novas",            action="store_true",
                   help="Use 'novas' command instead of 'verdi'")
    p.add_argument("--list-scenarios",   action="store_true",
                   help="List available scenarios and exit")
    p.add_argument("--dump-config",      action="store_true",
                   help="Dump built-in default config to stdout and exit")
    return p


def main():
    p = build_parser()
    args = p.parse_args()

    if args.list_scenarios:
        print("Available scenarios:")
        descs = {
            "sfr-check":  "SFR write → channel response latency measurement",
            "timing":     "Inter-channel timing alignment & delta analysis",
            "compare":    "Multi-instance / multi-FSDB signal comparison",
            "edge-count": "Toggle/edge count statistics per channel",
            "frame-sync": "LTE/NR frame/subframe/slot boundary markers",
            "full":       "All scenarios combined",
        }
        for sc, desc in descs.items():
            print(f"  {sc:<14}  {desc}")
        sys.exit(0)

    if args.dump_config:
        if HAS_YAML:
            print(yaml.dump(DEFAULT_CONFIG, default_flow_style=False, allow_unicode=True))
        else:
            print(json.dumps(DEFAULT_CONFIG, indent=2))
        sys.exit(0)

    if not args.fsdb:
        print("[!] -f/--fsdb is required", file=sys.stderr)
        sys.exit(1)

    if not Path(args.fsdb).exists():
        print(f"[!] FSDB file not found: {args.fsdb}", file=sys.stderr)
        sys.exit(1)

    tool = VerdiWaveTool(args)
    tool.run()


if __name__ == "__main__":
    main()
