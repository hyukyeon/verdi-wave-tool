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
    
    # Recursive resolution within base
    for e in envs.values():
        changed = True
        while changed:
            changed = False
            for k, v in e.items():
                for k2, v2 in e.items():
                    if k != k2 and v.startswith(k2 + '.'):
                        e[k] = v.replace(k2 + '.', v2 + '.', 1)
                        changed = True
    return envs

def parse_scn(fpath, res):
    """Parses config/scn_*.lst, keeping only [GROUPS]."""
    groups = []
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
            if idx.endswith('.'): # Group header: "1.  NAME  [color]"
                num = idx[:-1]
                name = parts[1]
                color = parts[2] if len(parts) > 2 else ""
                groups.append(Group(num, name, color, []))
            else: # Signal: "1.1  path  radix  color  [height]  [alias]"
                if not groups: continue
                path = res.r(parts[1])
                radix = parts[2]
                color = parts[3] if len(parts) > 3 and parts[3] != '-' else ""
                height = parts[4] if len(parts) > 4 and parts[4].isdigit() else ""
                alias = parts[5] if len(parts) > 5 else (parts[4] if len(parts) > 4 and not parts[4].isdigit() else "")
                groups[-1].sigs.append(Signal(path, radix, color, height, alias))
                
    return groups

def gen_rc(groups):
    """Generates a Verdi RC (Signal Save) file."""
    L = []
    def w(s=''): L.append(s)

    w("# Verdi Signal Save File")
    w()

    for g in groups:
        w('addGroup "{}"'.format(g.name))
        for sig in g.sigs:
            nwp = _nw(sig.path)
            # RC syntax: addSignal -h <height> -C <color> <path>
            opts = []
            if sig.height: opts.append("-h {}".format(sig.height))
            else:          opts.append("-h 15") # Default height
            
            if sig.color:  opts.append("-C {}".format(sig.color.upper()))
            
            w('addSignal {} {}'.format(" ".join(opts), nwp))
            
            # Radix: setRadix -<format> <path>
            if sig.radix:
                fmt = sig.radix.lower()
                if fmt == 'hex':   w('setRadix -hex {}'.format(nwp))
                elif fmt == 'bin': w('setRadix -bin {}'.format(nwp))
                elif fmt == 'dec': w('setRadix -dec {}'.format(nwp))
                elif fmt == 'oct': w('setRadix -oct {}'.format(nwp))
            
            # Alias: setAlias -name "<alias>" <path>
            if sig.alias:
                w('setAlias -name "{}" {}'.format(sig.alias, nwp))
        w()
    
    return '\n'.join(L)

def list_scenarios():
    scns = sorted([f.stem.replace('scn_', '') for f in CFG_DIR.glob('scn_*.lst') if f.stem != 'scn_base'])
    print("Available scenarios (config/scn_*.lst):")
    for s in scns:
        print("  {}".format(s))
    sys.exit(0)

def list_bases():
    envs = parse_base(BASE_FILE)
    print("BASE environments (config/scn_base.lst):")
    for name in sorted(envs):
        print("  {}".format(name))
    sys.exit(0)

def main():
    ap = argparse.ArgumentParser(description="Verdi Signal RC Generator")
    ap.add_argument("-s", "--scenario", help="Scenario name")
    ap.add_argument("-b", "--base",     help="BASE env name")
    ap.add_argument("-f", "--fsdb",     help="FSDB path (not used in RC but for consistency)")
    ap.add_argument("--reuse",      action="store_true", help="Reuse existing RC")
    ap.add_argument("--list",       action="store_true", help="List scenarios")
    ap.add_argument("--list-base",  action="store_true", help="List BASE envs")
    args = ap.parse_args()

    if args.list: list_scenarios()
    if args.list_base: list_bases()
    if not args.scenario or not args.base:
        ap.error("-s and -b are required")

    scn_name = args.scenario
    base_name = args.base

    base_envs = parse_base(BASE_FILE)
    if base_name not in base_envs:
        sys.exit("[!] BASE '{}' not found".format(base_name))

    scn_file = CFG_DIR / "scn_{}.lst".format(scn_name)
    if not scn_file.exists():
        sys.exit("[!] Scenario file not found: {}".format(scn_file))

    OUT_DIR.mkdir(exist_ok=True)
    rc_file = OUT_DIR / "{}_{}.rc".format(base_name, scn_name)

    if rc_file.exists() and args.reuse:
        print("[+] Using existing RC: {}".format(rc_file))
    else:
        res = Resolver(base_envs[base_name])
        groups = parse_scn(scn_file, res)
        rc_file.write_text(gen_rc(groups))
        print("[+] Generated RC : {}".format(rc_file))

if __name__ == "__main__":
    main()
