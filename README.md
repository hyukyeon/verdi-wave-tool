# verdi-wave-tool

Verdi nWave automation tool for LTE/NR waveform analysis.
Generates a combined TCL script (signal layout + analysis) from a simple numbered list format, then launches Verdi.

---

## Repository Layout

```
verdi-wave-tool/
+-- run_verdi                 # Wrapper script (main entry point)
+-- verdi_wave_tool.py        # Python generator
+-- config/
    +-- scn_base.lst          # Simulation environment hierarchy definitions
    +-- scn_lte_crs.lst       # LTE CRS debug scenario
    +-- scn_nr_ssb.lst        # NR SSB debug scenario
```

**Generated output** (written to `./output/` at runtime, not tracked in git):

```
output/
+-- {BASE}_{SCN}.tcl          # Combined nWave TCL (signal layout + analysis)
```

---

## Requirements

- Python 3.6+  (no third-party packages required)
- Verdi / nWave

---

## Quick Start

```bash
# 1. List available scenarios and BASE environments
./run_verdi --list
python3 verdi_wave_tool.py --list
python3 verdi_wave_tool.py --list-base

# 2. Generate TCL and launch Verdi
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb

# 3. Reuse existing TCL (skip regeneration)
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb

# 4. Force regenerate TCL
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb --regen
```

The wrapper prints and runs:

```
verdi -ssf sim.fsdb -play output/topsim_lte_lte_crs.tcl
```

### Without the wrapper

```bash
python3 verdi_wave_tool.py -s lte_crs -b topsim_lte -f sim.fsdb
verdi -ssf sim.fsdb -play output/topsim_lte_lte_crs.tcl
```

---

## Config File Format

### `config/scn_base.lst` -- Simulation environment hierarchy

Each `[section]` defines one sim environment. Pass the section name as `BASE` when running.

```ini
[topsim_lte]
top    = tb.u_top.u_lte_bb      # any key name works as a path prefix
clk    = tb.sys_clk
rst    = tb.sys_rst_n
sfr    = tb.u_top.u_lte_bb.u_sfr
frame  = top.sfn[9:0]           # values may use other keys as prefixes
subfrm = top.subframe_cnt[3:0]
slot   = top.slot_cnt[0]
sym    = top.sym_cnt[3:0]
```

**Path resolution in scenario files:**

- Exact key match: `clk` -> `tb.sys_clk`
- Prefix notation: `top.signal` -> `tb.u_top.u_lte_bb.signal`
- Any key works as a prefix: `sfr.reg` -> `tb.u_top.u_lte_bb.u_sfr.reg`
- Literal paths (first component not a key) are passed through unchanged

The key names (`top`, `sfr`, etc.) are not reserved -- name them anything.
Literal signal paths like `tb.dut.top.sub` are never expanded even if `top` is a defined key.

---

### `config/scn_*.lst` -- Scenario definition

A scenario file has three sections: `[GROUPS]`, `[EXPRESSIONS]`, `[SCENARIOS]`.
The BASE environment is no longer declared inside the file -- it is passed on the command line.

#### `[GROUPS]`

Numbered entries define the signal list displayed in nWave.

```
# N.     GROUP_NAME    [bg_color]
# N.M    path          radix  color  [height]  [alias]
# N.M.K  path          radix  -      [height]  [alias]   (- = inherit group color)
```

Example:

```
1.     TIMING          gray
1.1    clk             bin    gray
1.2    rst             bin    gray
1.3    frame           dec    gray

2.     SFR             lightyellow
2.1    sfr.crs_cfg[31:0]      hex    yellow         CRS_CFG
2.1.1  sfr.crs_cfg[0]         bin    -              .EN
2.1.2  sfr.crs_cfg[2:1]       dec    -              .ANT_PORT

3.     CRS             red
3.1    top.crs_en             bin    red
3.2    top.crs_vld            bin    red
3.3    top.crs_seq[127:0]     hex    red    35
```

| Column | Description |
|--------|-------------|
| path | Signal path using a defined prefix key or a literal hierarchy path |
| radix | `hex` `bin` `dec` `oct` |
| color | nWave color name; `-` inherits from the group |
| height | (optional) row height in pixels |
| alias | (optional) display name shown in nWave |

Gaps in numbering are fine -- just omit entries you do not need.

#### `[EXPRESSIONS]`

Derived signals computed by nWave from an expression string.

```
# EN  {expression}  radix  color  alias
E1    {top.pdsch_dl_en & top.pdsch_ce_done}   bin    orange    PDSCH_CE_READY
```

#### `[SCENARIOS]`

```
# SN    scenario-type
# SN.M  key = value
```

Supported scenario types:

| Type | Required keys | Description |
|------|--------------|-------------|
| `sfr-check` | `watch`, `response`, `max_latency` | Measures cycles from SFR value change to response signal rising edge |
| `timing` | `reference`, `compare` | Reports time delta between first rising edges |
| `edge-count` | `signals`, `edge` | Counts rising/falling edges across the full simulation |
| `frame-sync` | `standard`, `frame_ns`, `subfrm_ns`, `slot_ns`, `num_frames` | Places frame/subframe/slot boundary markers |

Values for `watch`, `response`, `reference`, `compare`, and `signals`
may be written as **group entry numbers** (`N.M`) -- they are resolved to full signal paths automatically.

Example:

```
S1     sfr-check
S1.1   watch       = 2.1, 2.2        # resolved to full SFR paths
S1.2   response    = 3.1             # resolved to top.crs_en path
S1.3   max_latency = 8

S2     timing
S2.1   reference   = 3.1
S2.2   compare     = 4.2, 5.2
```

---

## Included Scenarios

### `scn_lte_crs` -- TopSim LTE CRS Debug

BASE: `topsim_lte`

| # | Scenario | What it checks |
|---|----------|---------------|
| S1 | sfr-check | SFR write (CRS_CFG, CHAN_CTRL, TIMING_CFG) -> `crs_en` latency <= 8 cycles |
| S2 | timing | First activation delta of `pdsch_dl_vld` and `pdcch_dl_vld` relative to `crs_en` |
| S3 | edge-count | Rising edge count on `crs_vld`, `pdsch_dl_vld`, `pdcch_dl_vld` |
| S4 | frame-sync | LTE frame (10 ms) / subframe (1 ms) / slot (0.5 ms) markers, 8 frames |

Signal groups: **TIMING / SFR / CRS / PDSCH / PDCCH**

```bash
./run_verdi lte_crs topsim_lte sim.fsdb
```

---

### `scn_nr_ssb` -- BlockSim NR SSB Debug

BASE: `blocksim_nr_ssb`

| # | Scenario | What it checks |
|---|----------|---------------|
| S1 | sfr-check | SFR write (SSB_CFG, CHAN_CTRL) -> `ssb_en` latency <= 4 cycles |
| S2 | timing | First-activation order of `pss_vld`, `sss_vld`, `pbch_vld` relative to `ssb_en` |
| S3 | edge-count | Rising edge count on `ssb_vld`, `pss_vld`, `sss_vld`, `pbch_vld` |
| S4 | frame-sync | NR frame (10 ms) / subframe (0.5 ms) / slot (0.25 ms, u=1) markers, 20 frames |

Signal groups: **TIMING / SFR / SSB / PSS / SSS / PBCH / BEAM**

```bash
./run_verdi nr_ssb blocksim_nr_ssb sim.fsdb
```

---

## Adding a New Scenario

1. Add a new environment block to `config/scn_base.lst` if the DUT hierarchy differs.
2. Create `config/scn_<name>.lst` with `[GROUPS]`, `[EXPRESSIONS]`, `[SCENARIOS]` sections.
3. Run `python3 verdi_wave_tool.py --list` to confirm detection.
4. Run `./run_verdi <name> <BASE> sim.fsdb`.

No changes to `verdi_wave_tool.py` are needed.

---

## Generated Output

### `output/{BASE}_{SCN}.tcl`

Single TCL script loaded by Verdi via `-play`. Contains two parts:

**Signal layout** (TCL nWave commands):
- `wvSetGroupBegin / wvSetGroupEnd` -- group boundaries
- `wvAddSignal` -- add signal to waveform view
- `wvSetSignalRadix / wvSetSignalColor / wvSetSignalHeight / wvSetSignalAlias` -- display attributes
- `wvAddExprSignal` -- derived expression signals
- `wvZoomFit` -- fit all signals on open

**Analysis**:
- Auto-detect clock period (`nwGetClockPeriod`), fallback 1000 ps
- Helper procs: `count_edges`, `scan_changes`, `measure_latency`
- One block per scenario -- runs sequentially, writes a `.txt` report to `output/`

If the output TCL already exists it is reused without regeneration.
Use `--regen` to force a rebuild.

---

## Troubleshooting

**Signal not found in FSDB**
Open the FSDB in Verdi's Signal Browser, confirm the actual hierarchy path,
then update the key values in `scn_base.lst` or the `path` entries in the scenario file.

**Clock period returns 0**
Set the fallback manually at the top of the generated TCL:
```tcl
set clk_period 2000   ;# e.g. 500 MHz -> 2000 ps
```

**Frame markers do not align with waveform**
Adjust `unit_ps` in the generated TCL to match the simulation timescale:
```tcl
set unit_ps 1     ;# timescale 1ps/1ps
set unit_ps 1000  ;# timescale 1ns/1ps  (default)
```
