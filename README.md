# verdi-wave-tool

Verdi nWave automation tool for LTE/NR waveform analysis.
Generates a signal RC file and a TCL analysis script from a simple numbered list format, then launches Verdi with both files.

---

## Repository Layout

```
verdi-wave-tool/
├── verdi_wave_tool.py        # Single entry point
└── config/
    ├── scn_base.lst          # Simulation environment hierarchy definitions
    ├── scn_lte_crs.lst       # LTE CRS debug scenario
    └── scn_nr_ssb.lst        # NR SSB debug scenario
```

**Generated output** (written to `./output/` at runtime, not tracked in git):

```
output/
├── signals.rc                # nWave signal RC  (groups / colors / radix / aliases)
└── analysis.tcl              # nWave TCL script (helper procs + scenario runs)
```

---

## Requirements

- Python 3.8+  (no third-party packages required)
- Verdi / nWave (tested with Verdi 2019.06+)

---

## Quick Start

```bash
# 1. List available scenarios
python3 verdi_wave_tool.py --list

# 2. Generate RC + TCL for a scenario
python3 verdi_wave_tool.py -f /path/to/sim.fsdb -s scn_lte_crs

# 3. Copy the printed command and run it, or use --launch to auto-start Verdi
python3 verdi_wave_tool.py -f /path/to/sim.fsdb -s scn_nr_ssb --launch
```

The tool always prints the exact Verdi command to use:

```
verdi -ssf sim.fsdb -rcFile output/signals.rc -play output/analysis.tcl
```

---

## Config File Format

### `config/scn_base.lst` — Simulation environment hierarchy

Each `[section]` defines one sim environment.
The scenario file references it with `sim = <section_name>` in its `[BASE]` block.

```ini
[topsim_lte]
top    = tb.u_top.u_lte_bb      # full path to DUT top
clk    = tb.sys_clk
rst    = tb.sys_rst_n
sfr    = tb.u_top.u_lte_bb.u_sfr
frame  = top.sfn[9:0]           # top. prefix is resolved automatically
subfrm = top.subframe_cnt[3:0]
slot   = top.slot_cnt[0]
sym    = top.sym_cnt[3:0]
```

**Path keywords** available in scenario files:
`clk` `rst` `frame` `subfrm` `slot` `sym` → resolved to the values above
`top.X` → `{top}.X`
`sfr.X` → `{sfr}.X`

---

### `config/scn_*.lst` — Scenario definition

A scenario file has four sections: `[BASE]`, `[GROUPS]`, `[EXPRESSIONS]`, `[SCENARIOS]`.

#### `[BASE]`

```
[BASE]
sim = topsim_lte        # must match a section name in scn_base.lst
```

#### `[GROUPS]`

Numbered entries define the signal list displayed in nWave.

```
# N.     GROUP_NAME    [bg_color]           ← group header
# N.M    path          radix  color  [height]  [alias]   ← signal
# N.M.K  path          radix  -      [height]  [alias]   ← sub-field (- = inherit group color)
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
| path | Signal path using `top.`, `sfr.`, or a keyword |
| radix | `hex` `bin` `dec` `oct` |
| color | nWave color name; `-` inherits from the group |
| height | (optional) row height in pixels |
| alias | (optional) display name shown in nWave |

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
may be written as **group entry numbers** (`N.M`) — they are resolved to full signal paths automatically.

Example:

```
S1     sfr-check
S1.1   watch       = 2.1, 2.2        # resolved to full SFR paths
S1.2   response    = 3.1             # resolved to top.crs_en
S1.3   max_latency = 8

S2     timing
S2.1   reference   = 3.1
S2.2   compare     = 4.2, 5.2
```

---

## Included Scenarios

### `scn_lte_crs` — TopSim LTE CRS Debug

| # | Scenario | What it checks |
|---|----------|---------------|
| S1 | sfr-check | SFR write (CRS_CFG, CHAN_CTRL, TIMING_CFG) → `crs_en` latency ≤ 8 cycles |
| S2 | timing | First activation delta of `pdsch_dl_vld` and `pdcch_dl_vld` relative to `crs_en` |
| S3 | edge-count | Rising edge count on `crs_vld`, `pdsch_dl_vld`, `pdcch_dl_vld` |
| S4 | frame-sync | LTE frame (10 ms) / subframe (1 ms) / slot (0.5 ms) markers, 8 frames |

Signal groups: **TIMING · SFR · CRS · PDSCH · PDCCH**

---

### `scn_nr_ssb` — BlockSim NR SSB Debug

| # | Scenario | What it checks |
|---|----------|---------------|
| S1 | sfr-check | SFR write (SSB_CFG, CHAN_CTRL) → `ssb_en` latency ≤ 4 cycles |
| S2 | timing | First-activation order of `pss_vld`, `sss_vld`, `pbch_vld` relative to `ssb_en` |
| S3 | edge-count | Rising edge count on `ssb_vld`, `pss_vld`, `sss_vld`, `pbch_vld` |
| S4 | frame-sync | NR frame (10 ms) / subframe (0.5 ms) / slot (0.25 ms, μ=1) markers, 20 frames |

Signal groups: **TIMING · SFR · SSB · PSS · SSS · PBCH · BEAM**

---

## Adding a New Scenario

1. Add a new environment block to `config/scn_base.lst` if the DUT hierarchy differs.
2. Create `config/scn_<name>.lst` following the format above.
3. Run `python3 verdi_wave_tool.py --list` to confirm it is detected.
4. Run `python3 verdi_wave_tool.py -f sim.fsdb -s scn_<name>`.

No changes to `verdi_wave_tool.py` are needed.

---

## Generated Output Details

### `output/signals.rc`

Pure Tcl sourced by nWave via `-rcFile`. Contains:
- `debImport -sv4 {fsdb}` — loads the FSDB
- `wvSetGroupBegin / wvAddSignal / wvSetSignalRadix / wvSetSignalColor / wvSetSignalAlias` — per group
- `wvAddExprSignal` — for each expression
- `wvZoomFit` — fits all signals in view on open

### `output/analysis.tcl`

Tcl script sourced by nWave via `-play`. Contains:
- `source output/signals.rc` — loads the RC
- Auto-detect clock period (`nwGetClockPeriod`), fallback 1000 ps
- Helper procs: `count_edges`, `scan_changes`, `measure_latency`
- One block per scenario — runs sequentially, writes a `.txt` report to `output/`

---

## Troubleshooting

**`wvAddSignal: command not found`**
Some Verdi versions use `nw*` instead of `wv*`. Bulk-replace in the generated RC:
```bash
sed -i 's/^wv/nw/g' output/signals.rc
```

**Signal not found in FSDB**
Open the FSDB in Verdi's Signal Browser, confirm the actual hierarchy, then update `top` / `sfr` in `scn_base.lst` or adjust the `path` entries in the scenario file.

**Clock period returns 0**
Set the fallback manually in `output/analysis.tcl`:
```tcl
set clk_period 2000   ;# e.g. 500 MHz clock -> 2000 ps
```

**Frame markers don't align with waveform**
Adjust `unit_ps` in `output/analysis.tcl` to match the simulation timescale:
```tcl
set unit_ps 1     ;# timescale 1ps/1ps
set unit_ps 1000  ;# timescale 1ns/1ps  (default)
```
