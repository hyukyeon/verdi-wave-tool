# verdi-wave-tool

Verdi Signal Layout automation tool for LTE/NR waveform analysis.
Generates a Verdi RC (Signal Save/Restore) file from a simple numbered list format, then launches Verdi with the signal layout pre-loaded.

---

## Repository Layout

```
verdi-wave-tool/
+-- run_verdi                 # Wrapper script (main entry point)
+-- verdi_wave_tool.py        # Python generator
+-- config/
    +-- scn_base.lst          # Simulation environment hierarchy definitions
    +-- scn_lte_crs.lst       # LTE CRS signal list
    +-- scn_nr_ssb.lst        # NR SSB signal list
```

**Generated output** (written to `./output/` at runtime, not tracked in git):

```
output/
+-- {BASE}_{SCN}.rc           # Verdi Signal Save file
```

---

## Quick Start

```bash
# 1. List available scenarios and BASE environments
./run_verdi --list

# 2. Generate RC and launch Verdi
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb

# 3. Reuse existing RC (skip regeneration)
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb --reuse
```

The wrapper prints and runs:

```
verdi -ssf sim.fsdb -sswr output/topsim_lte_lte_crs.rc
```

---

## Config File Format

### `config/scn_base.lst` -- Simulation environment hierarchy

Each `[section]` defines one sim environment. Pass the section name as `BASE` when running.

```ini
[topsim_lte]
top    = tb.u_top.u_lte_bb
clk    = tb.sys_clk
frame  = top.sfn[9:0]
```

### `config/scn_*.lst` -- Scenario definition

Only the `[GROUPS]` section is used.

#### `[GROUPS]`

```
# N.     GROUP_NAME    [bg_color]
# N.M    path          radix  color  [height]  [alias]
```

Example:

```
1.     TIMING          gray
1.1    clk             bin    gray
1.2    rst             bin    gray
1.3    frame           dec    gray

2.     SFR             lightyellow
2.1    sfr.crs_cfg[31:0]      hex    yellow         CRS_CFG
```

| Column | Description |
|--------|-------------|
| path | Signal path using a defined prefix key or a literal hierarchy path |
| radix | `hex` `bin` `dec` `oct` |
| color | nWave color name (e.g., `red`, `yellow`, `gray`) |
| height | (optional) row height in pixels |
| alias | (optional) display name shown in nWave |

---

## Why use RC mode?

1. **Version Independence**: RC files use the standard Signal Save/Restore syntax, which is highly compatible across different Verdi versions.
2. **Stability**: Avoids "invalid command" errors common with version-specific TCL commands like `wvSetSignalRadix`.
3. **Speed**: Loading an RC file via `-sswr` is typically faster for large signal lists than executing TCL commands.

---

## Generated Output

### `output/{BASE}_{SCN}.rc`

A standard Verdi Signal Save file. It contains commands like:
- `addGroup "NAME"`
- `addSignal -h 15 -C RED /path/to/sig`
- `setRadix -hex /path/to/sig`
- `setAlias -name "ALIAS" /path/to/sig`
