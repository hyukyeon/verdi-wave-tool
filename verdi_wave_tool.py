#!/usr/bin/env python3
import sys
import argparse
import re
from pathlib import Path
from collections import namedtuple

# -- Constants & Paths ---------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
CFG_DIR    = SCRIPT_DIR / "config"
OUT_DIR    = SCRIPT_DIR / "output"
BASE_FILE  = CFG_DIR / "scn_base.lst"

# -- Data Structures -----------------------------------------------------------
Group  = namedtuple('Group', ['num', 'name', 'color', 'sigs'])
Signal = namedtuple('Signal', ['path', 'radix', 'color', 'height', 'alias'])
Marker = namedtuple('Marker', ['time', 'name', 'color'])

# -- Color Mapping (Verdi ID style) --------------------------------------------
COLOR_MAP = {
    'red': 'ID_RED5', 'green': 'ID_GREEN5', 'blue': 'ID_BLUE5',
    'yellow': 'ID_YELLOW5', 'cyan': 'ID_CYAN5', 'magenta': 'ID_MAGENTA5',
    'white': 'ID_WHITE', 'black': 'ID_BLACK', 'gray': 'ID_GRAY5',
    'orange': 'ID_ORANGE5', 'pink': 'ID_PINK5', 'brown': 'ID_BROWN5',
    'purple': 'ID_PURPLE5',
}

# -- Core Logic ----------------------------------------------------------------

class Resolver:
    def __init__(self, env_dict):
        self.env = env_dict

    def r(self, path):
        """Resolves a signal path using prefixes from scn_base.lst."""
        if not path or '.' not in path:
            return self.env.get(path, path)
        
        parts = path.split('.')
        prefix = parts[0]
        if prefix in self.env:
            resolved_prefix = self.env[prefix]
            return resolved_prefix + '.' + '.'.join(parts[1:])
        return path

def _nw(path):
    """Converts dot-notation to Verdi slash-notation: a.b[0] -> /a/b\[0\]"""
    p = path.replace('.', '/')
    if not p.startswith('/'):
        p = '/' + p
    p = p.replace('[', '\\[').replace(']', '\\]')
    return p

def parse_base(fpath):
    """Parses config/scn_base.lst."""
    envs = {}
    curr = None
    if not fpath.exists(): return envs
    for line in fpath.read_text().splitlines():
        line = line.split('#')[0].strip()
        if not line: continue
        if line.startswith('[') and line.endswith(']'):
            curr = line[1:-1]
            envs[curr] = {}
        elif curr and '=' in line:
            k, v = line.split('=', 1)
            envs[curr][k.strip()] = v.strip()
    return envs

def parse_scn(fpath, res):
    """Parses config/scn_*.lst with GROUPS, VIRTUAL_BUSES, and MARKERS."""
    groups = []
    vbus_dict = {}
    markers = []
    curr_section = None
    lines = fpath.read_text().splitlines()
    
    for line in lines:
        raw = line.split('#')[0].strip()
        if not raw: continue
        
        if raw.startswith('[') and raw.endswith(']'):
            curr_section = raw[1:-1].upper()
            continue
            
        if curr_section == 'GROUPS':
            parts = re.split(r'\s+', raw)
            idx = parts[0]
            if idx.endswith('.'): # Group header
                num = idx[:-1]
                name = parts[1]
                color = parts[2] if len(parts) > 2 else ""
                groups.append(Group(num, name, color, []))
            else: # Signal
                if not groups: continue
                path = parts[1]
                radix = parts[2]
                color = parts[3] if len(parts) > 3 and parts[3] != '-' else ""
                height = parts[4] if len(parts) > 4 and parts[4].isdigit() else ""
                alias = parts[5] if len(parts) > 5 else (parts[4] if len(parts) > 4 and not parts[4].isdigit() else "")
                groups[-1].sigs.append(Signal(path, radix, color, height, alias))
                
        elif curr_section == 'VIRTUAL_BUSES':
            if '=' in raw:
                name, sigs_str = raw.split('=', 1)
                sigs = [res.r(s.strip()) for s in sigs_str.split(',')]
                vbus_dict[name.strip()] = sigs

        elif curr_section == 'MARKERS':
            parts = re.split(r'\s+', raw)
            if len(parts) >= 2:
                time = parts[0]
                name = parts[1]
                color = parts[2] if len(parts) > 2 else "white"
                markers.append(Marker(time, name, color))
                
    return groups, vbus_dict, markers

def gen_rc(groups, vbus_dict, markers, res):
    """Generates a Verdi RC file using single-line addSignal/addBus commands."""
    L = []
    def w(s=''): L.append(s)

    w("# Verdi Signal Save File")
    w()

    # -- Markers ---------------------------------------------------------------
    for m in markers:
        w('addMarker -time {} -name "{}" -color {}'.format(m.time, m.name, m.color.upper()))
    w()

    # -- Signal Groups ---------------------------------------------------------
    for g in groups:
        w('addGroup "{}"'.format(g.name))
        for sig in g.sigs:
            opts = []
            
            # Height
            h = sig.height if sig.height else "15"
            opts.append("-h {}".format(h))
            
            # Color
            c = sig.color if sig.color else g.color
            if c and c.lower() in COLOR_MAP:
                opts.append("-color {}".format(COLOR_MAP[c.lower()]))
            
            # Radix
            if sig.radix == 'analog':
                opts.append("-analog")
            elif sig.radix.lower() in ['hex', 'bin', 'dec', 'oct']:
                opts.append("-{}".format(sig.radix.upper()))
            
            # Alias
            if sig.alias:
                opts.append("-alias \"{}\"".format(sig.alias))

            # Check if it's a Virtual Bus
            if sig.path in vbus_dict:
                bus_name = sig.alias if sig.alias else sig.path
                w('addBus {} -name "{}"'.format(" ".join(opts), bus_name))
                for bsig in vbus_dict[sig.path]:
                    w('  addBusSignal {}'.format(_nw(bsig)))
            else:
                # Normal signal
                resolved_path = _nw(res.r(sig.path))
                w('addSignal {} {}'.format(" ".join(opts), resolved_path))
        w()
    
    return '\n'.join(L)

def main():
    ap = argparse.ArgumentParser(description="Verdi Advanced RC Generator")
    ap.add_argument("-s", "--scenario", help="Scenario name")
    ap.add_argument("-b", "--base",     help="BASE env name")
    ap.add_argument("--regen",      action="store_true", help="Force regenerate RC")
    ap.add_argument("--list",       action="store_true", help="List scenarios")
    ap.add_argument("--list-base",  action="store_true", help="List BASE envs")
    args = ap.parse_args()

    if args.list: 
        scns = sorted([f.stem.replace('scn_', '') for f in CFG_DIR.glob('scn_*.lst') if f.stem != 'scn_base'])
        print("Scenarios:"); [print("  "+s) for s in scns]; sys.exit(0)
    if args.list_base: 
        envs = parse_base(BASE_FILE); print("Bases:"); [print("  "+e) for e in envs]; sys.exit(0)

    if not args.scenario or not args.base: ap.error("-s and -b required")

    base_envs = parse_base(BASE_FILE)
    if args.base not in base_envs: sys.exit("[!] BASE '{}' not found".format(args.base))

    scn_file = CFG_DIR / "scn_{}.lst".format(args.scenario)
    if not scn_file.exists(): sys.exit("[!] Scenario file not found: {}".format(scn_file))

    OUT_DIR.mkdir(exist_ok=True)
    rc_file = OUT_DIR / "{}_{}.rc".format(args.base, args.scenario)

    env_res = Resolver(base_envs[args.base])

    if rc_file.exists() and not args.regen:
        print("[+] Using existing RC: {}".format(rc_file))
    else:
        groups, vbus_dict, markers = parse_scn(scn_file, env_res)
        rc_file.write_text(gen_rc(groups, vbus_dict, markers, env_res))
        print("[+] Generated RC : {}".format(rc_file))

if __name__ == "__main__":
    main()
