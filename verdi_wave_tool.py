#!/usr/bin/env python3
"""
verdi_wave_tool.py - Verdi nWave LTE/NR Waveform Analysis Tool
===============================================================
Config  ./config/scn_base.lst       sim environment hierarchy
        ./config/scn_<NAME>.lst     signal groups + scenario definitions

Output  ./output/<BASE>_<SCN>.tcl   combined nWave TCL (signal layout + analysis)

Usage:
  python3 verdi_wave_tool.py -s lte_crs -b topsim_lte -f sim.fsdb
  python3 verdi_wave_tool.py --list
  python3 verdi_wave_tool.py --list-base

Verdi:
  verdi -ssf sim.fsdb -play output/topsim_lte_lte_crs.tcl
"""

import argparse, re, sys, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

BASE_DIR  = Path(__file__).parent
CFG_DIR   = BASE_DIR / "config"
OUT_DIR   = BASE_DIR / "output"
BASE_FILE = CFG_DIR  / "scn_base.lst"


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
        self.color = color
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

def parse_base(path):
    # type: (Path) -> Dict[str, Dict[str, str]]
    """Parse  [env_name]  key = value  blocks -> {env: {key: val}}"""
    envs = {}
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

    def __init__(self, env):
        # type: (Dict[str, str]) -> None
        self.env = env
        self._keys = sorted(env.keys(), key=len, reverse=True)

    def r(self, p):
        # type: (str) -> str
        p = p.strip()
        if p in self.env:
            val = self.env[p]
            return self.r(val) if val != p else p
        dot = p.find('.')
        if dot > 0:
            prefix = p[:dot]
            if prefix in self.env:
                return "{}.{}".format(self.r(self.env[prefix]), p[dot+1:])
        return p

    def expr(self, s):
        # type: (str) -> str
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

_RG  = re.compile(r'^(\d+)\.\s+(.*)')
_RS  = re.compile(r'^(\d+)\.(\d+)\s+(.*)')
_RSF = re.compile(r'^(\d+)\.(\d+)\.(\d+)\s+(.*)')
_RSP = re.compile(r'^(S\d+\.\d+)\s+(.*)')
_RSH = re.compile(r'^(S\d+)\s+(.*)')
_RE  = re.compile(r'^(E\d+)\s+(.*)')


def _mk_sig(num, rest, gc):
    cols   = rest.split()
    path   = cols[0] if cols else ''
    radix  = cols[1] if len(cols) > 1 else 'hex'
    color  = cols[2] if len(cols) > 2 else '-'
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


def parse_scn(path, res):
    """
    Parse scn_*.lst (no [BASE] section).
    Returns (groups, exprs, scenarios, sig_index).
    sig_index maps 'N.M' -> Sig for scenario reference resolution.
    """
    groups    = []   # type: List[Group]
    exprs     = []   # type: List[Expr]
    scenarios = []   # type: List[Scenario]
    idx       = {}   # type: Dict[str, Sig]
    cur_g     = None # type: Optional[Group]
    cur_s     = None # type: Optional[Scenario]
    section   = ''

    for raw in open(path):
        line = raw.split('#')[0].rstrip()
        s    = line.strip()
        if not s:
            continue
        m = re.match(r'^\[(\w+)\]$', s)
        if m:
            section = m.group(1)
            continue

        # -- [GROUPS] --------------------------------------------------------
        if section == 'GROUPS':
            m = _RSF.match(s)
            if m:
                num = "{}.{}.{}".format(m.group(1), m.group(2), m.group(3))
                sig = _mk_sig(num, m.group(4), cur_g.color if cur_g else None)
                sig.path = res.r(sig.path)
                if cur_g:
                    cur_g.sigs.append(sig)
                idx[num] = sig
                continue

            m = _RS.match(s)
            if m:
                num = "{}.{}".format(m.group(1), m.group(2))
                sig = _mk_sig(num, m.group(3), cur_g.color if cur_g else None)
                sig.path = res.r(sig.path)
                if cur_g:
                    cur_g.sigs.append(sig)
                idx[num] = sig
                continue

            m = _RG.match(s)
            if m:
                parts = m.group(2).split()
                cur_g = Group(num=m.group(1), name=parts[0],
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
            if m:
                if '=' in m.group(2) and cur_s:
                    k, _, v = m.group(2).partition('=')
                    key, val = k.strip(), v.strip()
                    if key in ('watch', 'response', 'reference', 'compare', 'signals'):
                        val = ','.join(
                            idx[r.strip()].path if r.strip() in idx else r.strip()
                            for r in val.split(',')
                        )
                    cur_s.params[key] = val
                continue

            m = _RSH.match(s)
            if m:
                cur_s = Scenario(num=m.group(1), type_=m.group(2).strip())
                scenarios.append(cur_s)

    return groups, exprs, scenarios, idx


# =============================================================================
# Path format conversion
# =============================================================================

def _nw(path):
    """Convert dot-notation path to nWave slash-notation with escaped brackets.
    e.g. tb.u_top.sfn[9:0]  ->  /tb/u_top/sfn\\[9:0\\]
    """
    p = '/' + path.replace('.', '/')
    p = p.replace('[', '\\[').replace(']', '\\]')
    return p


def _nw_expr(expr):
    """Convert all dot-notation signal paths inside an expression string."""
    # Match hierarchy paths: word chars + dots + optional brackets
    def repl(m):
        tok = m.group(0)
        # Only convert if it looks like a hierarchy path (contains a dot)
        if '.' in tok:
            return _nw(tok)
        return tok
    return re.sub(r'[\w]+(?:\.[\w]+)+(?:\[[\d:]+\])?', repl, expr)


# =============================================================================
# TCL Generator  ->  output/<BASE>_<SCN>.tcl
# =============================================================================

def gen_tcl(fsdb, base_name, scn_name, clk_sig, groups, exprs, scenarios, out_dir):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    L  = [
        "# {}".format('='*62),
        "# Verdi nWave Analysis TCL",
        "# Generated : {}".format(ts),
        "# BASE      : {}".format(base_name),
        "# Scenario  : {}".format(scn_name),
        "# FSDB      : {}".format(fsdb),
        "# {}".format('='*62),
        "",
        "set report_dir {{{}}}".format(str(out_dir)),
        "set fsdb_file  {{{}}}".format(fsdb),
        "",
    ]
    def w(s=''):
        L.append(s)

    # -- Open nWave window and load FSDB --------------------------------------
    w("# {}".format('='*62))
    w("# Open nWave window and load FSDB")
    w("# {}".format('='*62))
    w()
    w("set nwave_win [wvCreateWindow]")
    w("wvOpenFile -win $nwave_win {{{}}}".format(fsdb))
    w()

    # -- Signal layout --------------------------------------------------------
    w("# {}".format('='*62))
    w("# Signal Layout")
    w("# {}".format('='*62))
    w()
    for g in groups:
        bg = " -backgroundcolor {}".format(g.color) if g.color else ""
        w("# {}".format('-'*62))
        w("# {}.  {}".format(g.num, g.name))
        w("# {}".format('-'*62))
        w("wvSetGroupBegin -win $nwave_win -name {{{}}}{}".format(g.name, bg))
        for sig in g.sigs:
            nwp = _nw(sig.path)
            w("wvAddSignal -win $nwave_win {{{}}}".format(nwp))
            w("wvSetSignalRadix -win $nwave_win -radix {} {{{}}}".format(sig.radix, nwp))
            if sig.color:
                w("wvSetSignalColor -win $nwave_win -color {} {{{}}}".format(sig.color, nwp))
            if sig.height:
                w("wvSetSignalHeight -win $nwave_win -height {} {{{}}}".format(sig.height, nwp))
            if sig.alias:
                w("wvSetSignalAlias -win $nwave_win -alias {{{}}} {{{}}}".format(sig.alias, nwp))
        w("wvSetGroupEnd -win $nwave_win")
        w("wvAddBlankLine -win $nwave_win")
        w()

    if exprs:
        w("# {}".format('-'*62))
        w("# EXPRESSIONS")
        w("# {}".format('-'*62))
        w("wvSetGroupBegin -win $nwave_win -name {EXPRESSIONS} -backgroundcolor pink")
        for e in exprs:
            w("wvAddExprSignal -win $nwave_win -name {{{}}} -color {} -expr {{{}}}".format(
                e.alias, e.color, _nw_expr(e.expr)))
        w("wvSetGroupEnd -win $nwave_win")
        w("wvAddBlankLine -win $nwave_win")
        w()

    w("wvZoomFit -win $nwave_win")
    w()

    # -- Clock detection ------------------------------------------------------
    w("# {}".format('='*62))
    w("# Analysis")
    w("# {}".format('='*62))
    w()
    w("# Clock period (ps) - auto-detect, fallback to 1000 ps (1 ns)")
    w("if {[catch {set clk_period [nwGetClockPeriod -win $nwave_win {" + _nw(clk_sig) + "}]}]} {")
    w("    set clk_period 1000")
    w("}")
    w()

    _write_procs(w)

    for scn in scenarios:
        w("# {}".format('='*62))
        w("# Scenario {} : {}".format(scn.num, scn.type))
        w("# {}".format('='*62))
        _DISPATCH.get(scn.type, _scn_unknown)(w, scn)
        w()

    return '\n'.join(L)


# -- Common helper procs -------------------------------------------------------

def _write_procs(w):
    w("# -- Helper Procs -----------------------------------------------------")
    w()

    w("proc count_edges {sig etype} {")
    w("    global nwave_win")
    w("    set n 0; set t [nwGetMinTime -win $nwave_win]; set end [nwGetMaxTime -win $nwave_win]")
    w("    while {$t < $end} {")
    w("        set t [nwSearchNext -win $nwave_win -signal $sig -type ${etype}_edge -from $t]")
    w("        if {$t eq {}} break")
    w("        incr n; incr t")
    w("    }; return $n")
    w("}")
    w()

    w("proc scan_changes {sfr_sig prefix} {")
    w("    global nwave_win")
    w("    set n 0; set t [nwGetMinTime -win $nwave_win]; set end [nwGetMaxTime -win $nwave_win]")
    w("    while {$t < $end} {")
    w("        set t [nwSearchNext -win $nwave_win -signal $sfr_sig -type value_change -from $t]")
    w("        if {$t eq {}} break")
    w("        set v [nwGetValue -win $nwave_win -signal $sfr_sig -time $t]")
    w("        nwAddMarker -win $nwave_win -time $t -name \"${prefix}[incr n](${v})\" -color yellow")
    w("        incr t")
    w("    }; return $n")
    w("}")
    w()

    w("proc measure_latency {sfr_sig resp_sig max_cyc clk_per fd} {")
    w("    global nwave_win")
    w("    set ok 0; set fail 0; set t [nwGetMinTime -win $nwave_win]; set end [nwGetMaxTime -win $nwave_win]")
    w("    while {$t < $end} {")
    w("        set ts [nwSearchNext -win $nwave_win -signal $sfr_sig -type value_change -from $t]")
    w("        if {$ts eq {}} break")
    w("        set win_end [expr {$ts + $max_cyc * $clk_per}]")
    w("        set tr  [nwSearchNext -win $nwave_win -signal $resp_sig -type rising_edge \\")
    w("                              -from $ts -to $win_end]")
    w("        set v   [nwGetValue -win $nwave_win -signal $sfr_sig -time $ts]")
    w("        if {$tr ne {}} {")
    w("            set lat [expr {($tr - $ts) / $clk_per}]")
    w("            puts $fd [format \"  CHANGE @%10sps  val=%-12s  resp +%d cyc  OK\" \\")
    w("                      $ts $v $lat]")
    w("            incr ok")
    w("        } else {")
    w("            puts $fd [format \"  CHANGE @%10sps  val=%-12s  NO resp in %d cyc  FAIL\" \\")
    w("                      $ts $v $max_cyc]")
    w("            nwAddMarker -win $nwave_win -time $ts -name {LAT_FAIL} -color red")
    w("            incr fail")
    w("        }")
    w("        set t [expr {$ts + 1}]")
    w("    }; return [list $ok $fail]")
    w("}")
    w()

    w("# ---------------------------------------------------------------------")
    w()


# -- Per-scenario TCL writers --------------------------------------------------

def _scn_sfr_check(w, scn):
    watch    = [p.strip() for p in scn.params.get('watch', '').split(',') if p.strip()]
    response = scn.params.get('response', '')
    max_lat  = scn.params.get('max_latency', '16')
    rpt      = "$report_dir/{}_sfr_check.txt".format(scn.num)

    w("set fd [open {{{}}} w]".format(rpt))
    w("puts $fd \"SFR-Check {} - [clock format [clock seconds]]\"".format(scn.num))
    w("puts $fd \"response : {}\"".format(response))
    w("puts $fd \"max_lat  : {} cycles\"".format(max_lat))
    w("puts $fd \"{}\"".format('='*60))
    for sfr in watch:
        lbl = sfr.rsplit('.', 1)[-1]
        w("puts $fd \"\"")
        w("puts $fd \"--- {} ---\"".format(lbl))
        w("scan_changes {{{}}} {{{}_}}".format(_nw(sfr), lbl))
        w("set r [measure_latency {{{}}} {{{}}} {} $clk_period $fd]".format(
            _nw(sfr), _nw(response), max_lat))
        w("puts $fd \"  -> [lindex $r 0] OK  [lindex $r 1] FAIL\"")
    w("close $fd")
    w("puts \"{} sfr-check -> {}\"".format(scn.num, rpt))


def _scn_timing(w, scn):
    ref  = scn.params.get('reference', '')
    cmps = [p.strip() for p in scn.params.get('compare', '').split(',') if p.strip()]
    rpt  = "$report_dir/{}_timing.txt".format(scn.num)

    w("set fd [open {{{}}} w]".format(rpt))
    w("puts $fd \"Timing {} - [clock format [clock seconds]]\"".format(scn.num))
    w("puts $fd \"reference : {}\"".format(ref))
    w("puts $fd \"{}\"".format('='*60))
    w("set t_ref [nwSearchNext -win $nwave_win -signal {{{}}} -type rising_edge \\".format(_nw(ref)))
    w("                        -from [nwGetMinTime -win $nwave_win]]")
    w("if {$t_ref eq {}} {")
    w("    puts $fd \"  [WARN] reference signal has no rising edge\"")
    w("} else {")
    w("    nwAddMarker -win $nwave_win -time $t_ref -name {REF} -color green")
    w("    puts $fd \"  REF first edge @ ${t_ref}ps\"")
    w("    puts $fd \"\"")
    for cmp in cmps:
        lbl = cmp.rsplit('.', 1)[-1]
        w("    set t_c [nwSearchNext -win $nwave_win -signal {{{}}} -type rising_edge \\".format(_nw(cmp)))
        w("                         -from [nwGetMinTime -win $nwave_win]]")
        w("    if {$t_c ne {}} {")
        w("        set d [expr {$t_c - $t_ref}]")
        w("        nwAddMarker -win $nwave_win -time $t_c -name {{CMP_{}}} -color orange".format(lbl))
        w("        puts $fd [format \"  {} : delta = %+d ps\" $d]".format(lbl))
        w("    } else {")
        w("        puts $fd \"  {} : no rising edge\"".format(lbl))
        w("    }")
    w("}")
    w("close $fd")
    w("puts \"{} timing -> {}\"".format(scn.num, rpt))


def _scn_edge_count(w, scn):
    sigs = [p.strip() for p in scn.params.get('signals', '').split(',') if p.strip()]
    edge = scn.params.get('edge', 'rising')
    rpt  = "$report_dir/{}_edge_count.txt".format(scn.num)

    w("set fd [open {{{}}} w]".format(rpt))
    w("puts $fd \"Edge-Count {} - [clock format [clock seconds]]\"".format(scn.num))
    w("puts $fd \"edge: {}\"".format(edge))
    w("puts $fd \"{}\"".format('='*60))
    w("set clk_cnt [count_edges [nwGetClockSignal -win $nwave_win] rising]")
    w("puts $fd [format \"  %-54s %d\" {CLK total cycles} $clk_cnt]")
    for sig in sigs:
        lbl = sig.rsplit('.', 1)[-1]
        w("puts $fd [format \"  %-54s %d\" {{{}}} [count_edges {{{}}} {}]]".format(
            lbl, _nw(sig), edge))
    w("close $fd")
    w("puts \"{} edge-count -> {}\"".format(scn.num, rpt))


def _scn_frame_sync(w, scn):
    std      = scn.params.get('standard',   'NR')
    f_ns     = int(scn.params.get('frame_ns',   '10000000'))
    sf_ns    = int(scn.params.get('subfrm_ns',   '500000'))
    sl_ns    = int(scn.params.get('slot_ns',     '125000'))
    n_frames = int(scn.params.get('num_frames',  '4'))

    w("# {}: frame={}ns  subframe={}ns  slot={}ns  n={}".format(
        std, f_ns, sf_ns, sl_ns, n_frames))
    w("set unit_ps 1000   ;# 1ns=1000ps - adjust for your timescale")
    w("set f_ps  [expr {{{}  * $unit_ps}}]".format(f_ns))
    w("set sf_ps [expr {{{}  * $unit_ps}}]".format(sf_ns))
    w("set sl_ps [expr {{{}  * $unit_ps}}]".format(sl_ns))
    w("set t0 [nwGetMinTime -win $nwave_win]; set tmax [nwGetMaxTime -win $nwave_win]")
    w("for {set fn 0} {$fn < " + str(n_frames) + "} {incr fn} {")
    w("    set tf [expr {$t0 + $fn * $f_ps}]")
    w("    if {$tf > $tmax} break")
    w("    nwAddMarker -win $nwave_win -time $tf -name \"F${fn}\" -color white")
    w("    set nsf [expr {$f_ps / $sf_ps}]")
    w("    for {set sf 1} {$sf < $nsf} {incr sf} {")
    w("        set tsf [expr {$tf + $sf * $sf_ps}]")
    w("        nwAddMarker -win $nwave_win -time $tsf -name \"F${fn}_SF${sf}\" -color cyan")
    w("        set nsl [expr {$sf_ps / $sl_ps}]")
    w("        for {set sl 1} {$sl < $nsl} {incr sl} {")
    w("            nwAddMarker -win $nwave_win -time [expr {$tsf + $sl * $sl_ps}] \\")
    w("                        -name \"F${fn}_SF${sf}_SL${sl}\" -color gray")
    w("        }")
    w("    }")
    w("}")
    w("puts \"{} {} frame markers ({} frames)\"".format(scn.num, std, n_frames))
    w("nwZoom -win $nwave_win -from $t0 -to [expr {$t0 + $f_ps}]")


def _scn_unknown(w, scn):
    w("puts \"[WARN] unknown scenario type: {}\"".format(scn.type))


_DISPATCH = {
    'sfr-check':  _scn_sfr_check,
    'timing':     _scn_timing,
    'edge-count': _scn_edge_count,
    'frame-sync': _scn_frame_sync,
}


# =============================================================================
# CLI
# =============================================================================

def _scn_name(raw):
    """Strip optional 'scn_' prefix so user can pass either form."""
    return raw[4:] if raw.startswith('scn_') else raw


def list_scenarios():
    print("Scenarios (config/scn_*.lst):")
    for f in sorted(CFG_DIR.glob("scn_*.lst")):
        if f.name == "scn_base.lst":
            continue
        print("  {}".format(_scn_name(f.stem)))
    sys.exit(0)


def list_bases():
    if not BASE_FILE.exists():
        sys.exit("[!] Missing: {}".format(BASE_FILE))
    envs = parse_base(BASE_FILE)
    print("BASE environments (config/scn_base.lst):")
    for name in sorted(envs):
        print("  {}".format(name))
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(
        description="Verdi nWave LTE/NR Analysis Tool",
        epilog=(
            "examples:\n"
            "  %(prog)s -s lte_crs -b topsim_lte -f sim.fsdb\n"
            "  %(prog)s -s nr_ssb  -b blocksim_nr_ssb -f sim.fsdb\n"
            "  %(prog)s --list\n"
            "  %(prog)s --list-base"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-s", "--scenario", help="Scenario name (e.g. lte_crs)")
    ap.add_argument("-b", "--base",     help="BASE env name from scn_base.lst")
    ap.add_argument("-f", "--fsdb",     help="FSDB dump file path")
    ap.add_argument("--reuse",      action="store_true",
                    help="Reuse existing TCL if it exists (skip regeneration)")
    ap.add_argument("--list",       action="store_true", help="List scenarios")
    ap.add_argument("--list-base",  action="store_true", help="List BASE envs")
    args = ap.parse_args()

    if args.list:
        list_scenarios()
    if args.list_base:
        list_bases()

    if not args.scenario or not args.base or not args.fsdb:
        ap.error("-s, -b, and -f are all required  (or use --list / --list-base)")

    scn_name = _scn_name(args.scenario)
    base_name = args.base
    fsdb = str(Path(args.fsdb).resolve())

    if not Path(fsdb).exists():
        sys.exit("[!] FSDB not found: {}".format(fsdb))

    if not BASE_FILE.exists():
        sys.exit("[!] Missing: {}".format(BASE_FILE))
    base_envs = parse_base(BASE_FILE)
    if base_name not in base_envs:
        sys.exit("[!] BASE '{}' not in {}\n    Available: {}".format(
            base_name, BASE_FILE, list(base_envs)))

    scn_file = CFG_DIR / "scn_{}.lst".format(scn_name)
    if not scn_file.exists():
        sys.exit("[!] Scenario not found: {}".format(scn_file))

    OUT_DIR.mkdir(exist_ok=True)
    tcl_file = OUT_DIR / "{}_{}.tcl".format(base_name, scn_name)

    if tcl_file.exists() and args.reuse:
        print("[+] Using existing TCL: {}".format(tcl_file))
    else:
        res = Resolver(base_envs[base_name])
        groups, exprs, scenarios, _ = parse_scn(scn_file, res)
        clk_sig = res.r('clk')
        tcl_file.write_text(
            gen_tcl(fsdb, base_name, scn_name, clk_sig,
                    groups, exprs, scenarios, OUT_DIR)
        )
        print("[+] Generated TCL : {}".format(tcl_file))

    launch_cmd = "verdi -play {}".format(tcl_file)

    print("[+] BASE     : {}".format(base_name))
    print("[+] Scenario : {}".format(scn_name))
    print("[+] TCL      : {}".format(tcl_file))
    print()
    print("=" * 64)
    print("  {}".format(launch_cmd))
    print("=" * 64)


if __name__ == "__main__":
    main()
