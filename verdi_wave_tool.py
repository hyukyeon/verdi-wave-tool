#!/usr/bin/env python3
"""
verdi_wave_tool.py - Verdi nWave LTE/NR Waveform Analysis Tool
==============================================================
Config  ./config/scn_base.lst   sim environment hierarchy
        ./config/scn_*.lst      signal groups + scenario definitions
Output  ./output/signals.rc     nWave signal RC
        ./output/analysis.tcl   nWave TCL analysis script

Usage:
  python3 verdi_wave_tool.py -f sim.fsdb -s scn_lte_crs [--launch]
  python3 verdi_wave_tool.py --list

Verdi:
  verdi -ssf sim.fsdb -rcFile output/signals.rc -play output/analysis.tcl
"""

import argparse, re, sys, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

BASE_DIR  = Path(__file__).parent
CFG_DIR   = BASE_DIR / "config"
OUT_DIR   = BASE_DIR / "output"
BASE_FILE = CFG_DIR  / "scn_base.lst"
RC_FILE   = OUT_DIR  / "signals.rc"
TCL_FILE  = OUT_DIR  / "analysis.tcl"


# =============================================================================
# Data Models
# =============================================================================

class Sig:
    def __init__(self, num, path, radix="hex", color="cyan", height=None, alias=None):
        self.num    = num
        self.path   = path
        self.radix  = radix
        self.color  = color
        self.height = height
        self.alias  = alias

class Group:
    def __init__(self, num, name, color=None):
        self.num   = num
        self.name  = name
        self.color = color   # group background + default waveform color
        self.sigs  = []      # type: List[Sig]

class Expr:
    def __init__(self, num, expr, radix="bin", color="red", alias=""):
        self.num   = num
        self.expr  = expr
        self.radix = radix
        self.color = color
        self.alias = alias

class Scenario:
    def __init__(self, num, type_):
        self.num    = num
        self.type   = type_
        self.params = {}     # type: Dict[str, str]


# =============================================================================
# scn_base.lst Parser
# =============================================================================

def parse_base(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse  [env_name]  key = value  blocks -> {env: {key: val}}"""
    envs: Dict[str, Dict] = {}
    cur = None
    for raw in open(path):
        line = raw.split('#')[0].strip()
        if not line:
            continue
        m = re.match(r'^\[(\w+)\]$', line)
        if m:
            cur = m.group(1)
            envs[cur] = {}
        elif cur and '=' in line:
            k, _, v = line.partition('=')
            envs[cur][k.strip()] = v.strip()
    return envs


# =============================================================================
# Path Resolver
# =============================================================================

class Resolver:
    """
    Resolves path tokens in scn_*.lst to full signal paths.

    Exact env key  ->  env[key] value, recursively expanded
      e.g. clk  ->  tb.sys_clk
           frame ->  top.sfn[9:0]  ->  tb.u_top.u_lte_bb.sfn[9:0]

    Prefix notation  ->  env[key].rest, recursively expanded
      e.g. top.signal  ->  tb.u_top.u_lte_bb.signal
           ABC.sub     ->  tb.dut.aa.sub   (if ABC = tb.dut.aa in base)

    Literal paths (first component not an env key)  ->  unchanged
      e.g. tb.dut.ABC  ->  tb.dut.ABC     (safe even if ABC is an env key)
    """

    def __init__(self, env: Dict[str, str]):
        self.env = env
        # Sort longest-first so longer keys take precedence over shorter prefixes
        self._keys = sorted(env.keys(), key=len, reverse=True)

    def r(self, p: str) -> str:
        p = p.strip()
        # Exact match: the whole token is an env key
        if p in self.env:
            val = self.env[p]
            return self.r(val) if val != p else p
        # Prefix match: first dot-separated component is an env key
        dot = p.find('.')
        if dot > 0:
            prefix = p[:dot]
            if prefix in self.env:
                return f"{self.r(self.env[prefix])}.{p[dot+1:]}"
        return p

    def expr(self, s: str) -> str:
        """Resolve env-key-prefixed tokens inside an expression string."""
        for key in self._keys:
            pat = re.escape(key) + r'\.[\w\[\]:.]+'
            for m in re.finditer(pat, s):
                s = s.replace(m.group(), self.r(m.group()), 1)
        return s


# =============================================================================
# scn_*.lst Parser
# =============================================================================
#
# [GROUPS] entry number formats
#   N.       group header  "1.    NAME  [bg_color]"
#   N.M      signal        "1.1   path  radix  color  [height]  [alias]"
#   N.M.K    sub-field     "1.1.1 path  radix  -      [height]  [alias]"
#
# [EXPRESSIONS]
#   EN       "E1  {expr}  radix  color  alias"
#
# [SCENARIOS]
#   SN       "S1  scenario-type"
#   SN.M     "S1.1  key = value"
#
# Signal path columns: path  radix  color  [height|alias ...]
# color '-' inherits from the parent group color.

_RG   = re.compile(r'^(\d+)\.\s+(.*)')               # group header
_RS   = re.compile(r'^(\d+)\.(\d+)\s+(.*)')           # signal entry
_RSF  = re.compile(r'^(\d+)\.(\d+)\.(\d+)\s+(.*)')    # sub-field entry
_RSP  = re.compile(r'^(S\d+\.\d+)\s+(.*)')            # scenario param
_RSH  = re.compile(r'^(S\d+)\s+(.*)')                 # scenario header
_RE   = re.compile(r'^(E\d+)\s+(.*)')                 # expression


def _mk_sig(num: str, rest: str, gc: Optional[str]) -> Sig:
    """Build Sig from 'path radix color [height] [alias]' token string."""
    cols  = rest.split()
    path  = cols[0] if cols else ''
    radix = cols[1] if len(cols) > 1 else 'hex'
    color = cols[2] if len(cols) > 2 else '-'
    height, alias = None, None
    if len(cols) > 3:
        if cols[3].lstrip('-').isdigit():
            height = int(cols[3])
            alias  = ' '.join(cols[4:]) or None
        else:
            alias  = ' '.join(cols[3:]) or None
    if color == '-':
        color = gc or 'cyan'
    return Sig(num=num, path=path, radix=radix, color=color,
               height=height, alias=alias)


def parse_scn(path: Path, res: Resolver):
    """
    Parse scn_*.lst.
    Returns (sim_name, groups, exprs, scenarios, sig_index).
    sig_index maps "N.M" -> Sig for scenario reference resolution.
    """
    sim                        = ''
    groups:    List[Group]     = []
    exprs:     List[Expr]      = []
    scenarios: List[Scenario]  = []
    idx:       Dict[str, Sig]  = {}
    cur_g: Optional[Group]     = None
    cur_s: Optional[Scenario]  = None
    section                    = ''

    for raw in open(path):
        line = raw.split('#')[0].rstrip()
        s    = line.strip()
        if not s:
            continue
        m = re.match(r'^\[(\w+)\]$', s)
        if m:
            section = m.group(1)
            continue

        # -- [BASE] ----------------------------------------------------------
        if section == 'BASE':
            if '=' in s:
                k, _, v = s.partition('=')
                if k.strip() == 'sim':
                    sim = v.strip()

        # -- [GROUPS] --------------------------------------------------------
        elif section == 'GROUPS':
            m = _RSF.match(s)
            if m:                                           # N.M.K  sub-field
                num = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                sig = _mk_sig(num, m.group(4), cur_g.color if cur_g else None)
                sig.path = res.r(sig.path)
                if cur_g: cur_g.sigs.append(sig)
                idx[num] = sig
                continue

            m = _RS.match(s)
            if m:                                           # N.M    signal
                num = f"{m.group(1)}.{m.group(2)}"
                sig = _mk_sig(num, m.group(3), cur_g.color if cur_g else None)
                sig.path = res.r(sig.path)
                if cur_g: cur_g.sigs.append(sig)
                idx[num] = sig
                continue

            m = _RG.match(s)
            if m:                                           # N.    group header
                parts  = m.group(2).split()
                cur_g  = Group(num=m.group(1), name=parts[0],
                               color=parts[1] if len(parts) > 1 else None)
                groups.append(cur_g)

        # -- [EXPRESSIONS] ---------------------------------------------------
        elif section == 'EXPRESSIONS':
            m = _RE.match(s)
            if m:
                rest = m.group(2)
                if rest.startswith('{'):
                    end  = rest.index('}')
                    expr = res.expr(rest[1:end])
                    tail = rest[end+1:].split()
                else:
                    tail = rest.split()
                    expr = res.expr(tail[0])
                    tail = tail[1:]
                exprs.append(Expr(
                    num   = m.group(1),
                    expr  = expr,
                    radix = tail[0] if tail else 'bin',
                    color = tail[1] if len(tail) > 1 else 'red',
                    alias = tail[2] if len(tail) > 2 else m.group(1),
                ))

        # -- [SCENARIOS] -----------------------------------------------------
        elif section == 'SCENARIOS':
            m = _RSP.match(s)
            if m:                                           # S1.M  param
                if '=' in m.group(2) and cur_s:
                    k, _, v = m.group(2).partition('=')
                    key, val = k.strip(), v.strip()
                    # Resolve N.M signal references -> actual paths
                    if key in ('watch', 'response', 'reference', 'compare', 'signals'):
                        val = ','.join(
                            idx[r.strip()].path if r.strip() in idx else r.strip()
                            for r in val.split(',')
                        )
                    cur_s.params[key] = val
                continue

            m = _RSH.match(s)
            if m:                                           # S1  type
                cur_s = Scenario(num=m.group(1), type_=m.group(2).strip())
                scenarios.append(cur_s)

    return sim, groups, exprs, scenarios, idx


def _peek_sim(path: Path) -> str:
    """Quick scan: return sim = <value> from [BASE] section."""
    in_base = False
    for raw in open(path):
        s = raw.split('#')[0].strip()
        if s == '[BASE]':
            in_base = True
        elif s.startswith('[') and in_base:
            break
        elif in_base and s.startswith('sim') and '=' in s:
            return s.split('=', 1)[1].strip()
    return ''


# =============================================================================
# RC Generator  ->  output/signals.rc
# =============================================================================

def gen_rc(fsdb: str, groups: List[Group], exprs: List[Expr]) -> str:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    L: List[str] = [
        f"# {'='*62}",
        f"# Verdi nWave Signal RC",
        f"# Generated : {ts}",
        f"# FSDB      : {fsdb}",
        f"# {'='*62}", "",
        f"debImport -sv4 {{{fsdb}}}", "",
    ]
    def w(s=''): L.append(s)

    for g in groups:
        bg = f" -backgroundcolor {g.color}" if g.color else ""
        w(f"# {'-'*62}")
        w(f"# {g.num}.  {g.name}")
        w(f"# {'-'*62}")
        w(f"wvSetGroupBegin -name {{{g.name}}}{bg}")
        for sig in g.sigs:
            w(f"wvAddSignal {{{sig.path}}}")
            w(f"wvSetSignalRadix -radix {sig.radix} {{{sig.path}}}")
            if sig.color:
                w(f"wvSetSignalColor -color {sig.color} {{{sig.path}}}")
            if sig.height:
                w(f"wvSetSignalHeight -height {sig.height} {{{sig.path}}}")
            if sig.alias:
                w(f"wvSetSignalAlias -alias {{{sig.alias}}} {{{sig.path}}}")
        w("wvSetGroupEnd")
        w()

    if exprs:
        w(f"# {'-'*62}")
        w("# EXPRESSIONS")
        w(f"# {'-'*62}")
        w("wvSetGroupBegin -name {EXPRESSIONS} -backgroundcolor pink")
        for e in exprs:
            w(f"wvAddExprSignal -name {{{e.alias}}} -color {e.color} -expr {{{e.expr}}}")
        w("wvSetGroupEnd")
        w()

    w("wvZoomFit")
    return '\n'.join(L)


# =============================================================================
# TCL Generator  ->  output/analysis.tcl
# =============================================================================

def gen_tcl(fsdb: str, clk_sig: str, scenarios: List[Scenario]) -> str:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    L: List[str] = [
        f"# {'='*62}",
        f"# Verdi nWave Analysis TCL",
        f"# Generated : {ts}",
        f"# FSDB      : {fsdb}",
        f"# {'='*62}", "",
        f"set report_dir {{{str(OUT_DIR)}}}",
        f"set fsdb_file  {{{fsdb}}}", "",
        f"source {{{str(RC_FILE)}}}", "",
        f"# Clock period (ps) - auto-detect, fallback to 1000 ps (1 ns)",
        f"if {{[catch {{set clk_period [nwGetClockPeriod {{{clk_sig}}}]}}]}} {{",
        f"    set clk_period 1000",
        f"}}", "",
    ]
    def w(s=''): L.append(s)

    _write_procs(w)

    for scn in scenarios:
        w(f"# {'='*62}")
        w(f"# Scenario {scn.num} : {scn.type}")
        w(f"# {'='*62}")
        _DISPATCH.get(scn.type, _scn_unknown)(w, scn)
        w()

    return '\n'.join(L)


# -- Common helper procs -------------------------------------------------------

def _write_procs(w):
    w("# -- Helper Procs -----------------------------------------------------")
    w()

    w("proc count_edges {sig etype} {")
    w("    set n 0; set t [nwGetMinTime]; set end [nwGetMaxTime]")
    w("    while {$t < $end} {")
    w("        set t [nwSearchNext -signal $sig -type ${etype}_edge -from $t]")
    w("        if {$t eq {}} break")
    w("        incr n; incr t")
    w("    }; return $n")
    w("}")
    w()

    w("proc scan_changes {sfr_sig prefix} {")
    w("    set n 0; set t [nwGetMinTime]; set end [nwGetMaxTime]")
    w("    while {$t < $end} {")
    w("        set t [nwSearchNext -signal $sfr_sig -type value_change -from $t]")
    w("        if {$t eq {}} break")
    w("        set v [nwGetValue -signal $sfr_sig -time $t]")
    w("        nwAddMarker -time $t -name \"${prefix}[incr n](${v})\" -color yellow")
    w("        incr t")
    w("    }; return $n")
    w("}")
    w()

    w("proc measure_latency {sfr_sig resp_sig max_cyc clk_per fd} {")
    w("    set ok 0; set fail 0; set t [nwGetMinTime]; set end [nwGetMaxTime]")
    w("    while {$t < $end} {")
    w("        set ts [nwSearchNext -signal $sfr_sig -type value_change -from $t]")
    w("        if {$ts eq {}} break")
    w("        set win [expr {$ts + $max_cyc * $clk_per}]")
    w("        set tr  [nwSearchNext -signal $resp_sig -type rising_edge \\")
    w("                              -from $ts -to $win]")
    w("        set v   [nwGetValue -signal $sfr_sig -time $ts]")
    w("        if {$tr ne {}} {")
    w("            set lat [expr {($tr - $ts) / $clk_per}]")
    w("            puts $fd [format \"  CHANGE @%10sps  val=%-12s  resp +%d cyc  OK\" \\")
    w("                      $ts $v $lat]")
    w("            incr ok")
    w("        } else {")
    w("            puts $fd [format \"  CHANGE @%10sps  val=%-12s  NO resp in %d cyc  FAIL\" \\")
    w("                      $ts $v $max_cyc]")
    w("            nwAddMarker -time $ts -name {LAT_FAIL} -color red")
    w("            incr fail")
    w("        }")
    w("        set t [expr {$ts + 1}]")
    w("    }; return [list $ok $fail]")
    w("}")
    w()

    w("# ---------------------------------------------------------------------")
    w()


# -- Per-scenario TCL writers --------------------------------------------------

def _scn_sfr_check(w, scn: Scenario):
    watch    = [p.strip() for p in scn.params.get('watch', '').split(',') if p.strip()]
    response = scn.params.get('response', '')
    max_lat  = scn.params.get('max_latency', '16')
    rpt      = f"$report_dir/{scn.num}_sfr_check.txt"

    w(f"set fd [open {{{rpt}}} w]")
    w(f"puts $fd \"SFR-Check {scn.num} - [clock format [clock seconds]]\"")
    w(f"puts $fd \"response : {response}\"")
    w(f"puts $fd \"max_lat  : {max_lat} cycles\"")
    w(f"puts $fd \"{'='*60}\"")
    for sfr in watch:
        lbl = sfr.rsplit('.', 1)[-1]
        w(f"puts $fd \"\"")
        w(f"puts $fd \"--- {lbl} ---\"")
        w(f"scan_changes {{{sfr}}} {{{lbl}_}}")
        w(f"set r [measure_latency {{{sfr}}} {{{response}}} {max_lat} $clk_period $fd]")
        w(f"puts $fd \"  -> [lindex $r 0] OK  [lindex $r 1] FAIL\"")
    w(f"close $fd")
    w(f"puts \"[{scn.num}] sfr-check -> {rpt}\"")


def _scn_timing(w, scn: Scenario):
    ref  = scn.params.get('reference', '')
    cmps = [p.strip() for p in scn.params.get('compare', '').split(',') if p.strip()]
    rpt  = f"$report_dir/{scn.num}_timing.txt"

    w(f"set fd [open {{{rpt}}} w]")
    w(f"puts $fd \"Timing {scn.num} - [clock format [clock seconds]]\"")
    w(f"puts $fd \"reference : {ref}\"")
    w(f"puts $fd \"{'='*60}\"")
    w(f"set t_ref [nwSearchNext -signal {{{ref}}} -type rising_edge \\")
    w(f"                        -from [nwGetMinTime]]")
    w(f"if {{$t_ref eq {{}}}} {{")
    w(f"    puts $fd \"  [WARN] reference signal has no rising edge\"")
    w(f"}} else {{")
    w(f"    nwAddMarker -time $t_ref -name {{REF}} -color green")
    w(f"    puts $fd \"  REF first edge @ ${{t_ref}}ps\"")
    w(f"    puts $fd \"\"")
    for cmp in cmps:
        lbl = cmp.rsplit('.', 1)[-1]
        w(f"    set t_c [nwSearchNext -signal {{{cmp}}} -type rising_edge \\")
        w(f"                         -from [nwGetMinTime]]")
        w(f"    if {{$t_c ne {{}}}} {{")
        w(f"        set d [expr {{$t_c - $t_ref}}]")
        w(f"        nwAddMarker -time $t_c -name {{CMP_{lbl}}} -color orange")
        w(f"        puts $fd [format \"  {lbl} : delta = %+d ps\" $d]")
        w(f"    }} else {{")
        w(f"        puts $fd \"  {lbl} : no rising edge\"")
        w(f"    }}")
    w(f"}}")
    w(f"close $fd")
    w(f"puts \"[{scn.num}] timing -> {rpt}\"")


def _scn_edge_count(w, scn: Scenario):
    sigs = [p.strip() for p in scn.params.get('signals', '').split(',') if p.strip()]
    edge = scn.params.get('edge', 'rising')
    rpt  = f"$report_dir/{scn.num}_edge_count.txt"

    w(f"set fd [open {{{rpt}}} w]")
    w(f"puts $fd \"Edge-Count {scn.num} - [clock format [clock seconds]]\"")
    w(f"puts $fd \"edge: {edge}\"")
    w(f"puts $fd \"{'='*60}\"")
    w(f"set clk_cnt [count_edges [nwGetClockSignal] rising]")
    w(f"puts $fd [format \"  %-54s %d\" {{CLK total cycles}} $clk_cnt]")
    for sig in sigs:
        lbl = sig.rsplit('.', 1)[-1]
        w(f"puts $fd [format \"  %-54s %d\" {{{lbl}}} [count_edges {{{sig}}} {edge}]]")
    w(f"close $fd")
    w(f"puts \"[{scn.num}] edge-count -> {rpt}\"")


def _scn_frame_sync(w, scn: Scenario):
    std      = scn.params.get('standard',  'NR')
    f_ns     = int(scn.params.get('frame_ns',  '10000000'))
    sf_ns    = int(scn.params.get('subfrm_ns',  '500000'))
    sl_ns    = int(scn.params.get('slot_ns',    '125000'))
    n_frames = int(scn.params.get('num_frames', '4'))

    w(f"# {std}: frame={f_ns}ns  subframe={sf_ns}ns  slot={sl_ns}ns  n={n_frames}")
    w(f"set unit_ps 1000   ;# 1ns=1000ps - adjust for your timescale")
    w(f"set f_ps  [expr {{{f_ns}  * $unit_ps}}]")
    w(f"set sf_ps [expr {{{sf_ns} * $unit_ps}}]")
    w(f"set sl_ps [expr {{{sl_ns} * $unit_ps}}]")
    w(f"set t0 [nwGetMinTime]; set tmax [nwGetMaxTime]")
    w(f"for {{set fn 0}} {{$fn < {n_frames}}} {{incr fn}} {{")
    w(f"    set tf [expr {{$t0 + $fn * $f_ps}}]")
    w(f"    if {{$tf > $tmax}} break")
    w(f"    nwAddMarker -time $tf -name \"F${{fn}}\" -color white")
    w(f"    set nsf [expr {{$f_ps / $sf_ps}}]")
    w(f"    for {{set sf 1}} {{$sf < $nsf}} {{incr sf}} {{")
    w(f"        set tsf [expr {{$tf + $sf * $sf_ps}}]")
    w(f"        nwAddMarker -time $tsf -name \"F${{fn}}_SF${{sf}}\" -color cyan")
    w(f"        set nsl [expr {{$sf_ps / $sl_ps}}]")
    w(f"        for {{set sl 1}} {{$sl < $nsl}} {{incr sl}} {{")
    w(f"            nwAddMarker -time [expr {{$tsf + $sl * $sl_ps}}] \\")
    w(f"                        -name \"F${{fn}}_SF${{sf}}_SL${{sl}}\" -color gray")
    w(f"        }}")
    w(f"    }}")
    w(f"}}")
    w(f"puts \"[{scn.num}] {std} frame markers ({n_frames} frames)\"")
    w(f"nwZoom -from $t0 -to [expr {{$t0 + $f_ps}}]")


def _scn_unknown(w, scn: Scenario):
    w(f"puts \"[WARN] unknown scenario type: {scn.type}\"")


_DISPATCH = {
    'sfr-check':  _scn_sfr_check,
    'timing':     _scn_timing,
    'edge-count': _scn_edge_count,
    'frame-sync': _scn_frame_sync,
}


# =============================================================================
# CLI
# =============================================================================

def list_scenarios():
    print("Scenarios (config/scn_*.lst):")
    for f in sorted(CFG_DIR.glob("scn_*.lst")):
        if f.name == "scn_base.lst":
            continue
        sim = _peek_sim(f)
        print(f"  {f.stem:<24}  sim={sim}")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(
        description="Verdi nWave LTE/NR Analysis Tool",
        epilog=(
            "examples:\n"
            "  %(prog)s -f sim.fsdb -s scn_lte_crs\n"
            "  %(prog)s -f sim.fsdb -s scn_nr_ssb --launch\n"
            "  %(prog)s --list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-f", "--fsdb",     help="FSDB file path")
    ap.add_argument("-s", "--scenario", help="Scenario name (e.g. scn_lte_crs)")
    ap.add_argument("--launch", action="store_true", help="Auto-launch Verdi")
    ap.add_argument("--list",   action="store_true", help="List available scenarios")
    args = ap.parse_args()

    if args.list:
        list_scenarios()

    if not args.fsdb or not args.scenario:
        ap.error("-f and -s are required  (or use --list)")

    fsdb = str(Path(args.fsdb).resolve())
    if not Path(fsdb).exists():
        sys.exit(f"[!] FSDB not found: {fsdb}")

    if not BASE_FILE.exists():
        sys.exit(f"[!] Missing: {BASE_FILE}")
    base_envs = parse_base(BASE_FILE)

    scn_file = CFG_DIR / f"{args.scenario}.lst"
    if not scn_file.exists():
        sys.exit(f"[!] Scenario not found: {scn_file}")

    sim_name = _peek_sim(scn_file)
    if sim_name not in base_envs:
        sys.exit(f"[!] Sim env '{sim_name}' not in {BASE_FILE}\n"
                 f"    Available: {list(base_envs)}")

    res                               = Resolver(base_envs[sim_name])
    sim, groups, exprs, scenarios, _  = parse_scn(scn_file, res)
    clk_sig                           = res.r('clk')

    OUT_DIR.mkdir(exist_ok=True)
    RC_FILE.write_text(gen_rc(fsdb, groups, exprs))
    TCL_FILE.write_text(gen_tcl(fsdb, clk_sig, scenarios))

    launch_cmd = (f"verdi -ssf {fsdb}"
                  f" -rcFile {RC_FILE}"
                  f" -play {TCL_FILE}")

    print(f"[+] sim      : {sim_name}")
    print(f"[+] scenario : {args.scenario}")
    print(f"[+] RC       : {RC_FILE}")
    print(f"[+] TCL      : {TCL_FILE}")
    print()
    print("=" * 64)
    print(f"  {launch_cmd}")
    print("=" * 64)

    if args.launch:
        print("\n[+] launching Verdi ...")
        subprocess.run(launch_cmd, shell=True)


if __name__ == "__main__":
    main()
