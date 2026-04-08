# verdi-wave-tool

Verdi Signal Layout automation tool for LTE/NR waveform analysis.
Generates a Verdi RC (Signal Save/Restore) file from a simple numbered list format, then launches Verdi with the signal layout and FSDB loaded.

---

## Repository Layout

```
verdi-wave-tool/
+-- run_verdi                 # Wrapper script (main entry point)
+-- verdi_wave_tool.py        # Python generator
+-- config/
    +-- scn_base.lst          # Simulation environment hierarchy definitions
    +-- scn_lte_crs.lst       # LTE CRS signal list
    +-- scn_example.lst       # Example showing advanced RC features
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

# 2. Launch Verdi (generates RC on first run, reuses it thereafter)
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb

# 3. Force regenerate RC (if scenario/base config changed)
./run_verdi lte_crs topsim_lte /path/to/sim.fsdb --regen
```

---

## Config File Format (`config/scn_*.lst`)

A scenario file can contain세 sections: `[GROUPS]`, `[VIRTUAL_BUSES]`, and `[MARKERS]`.

### 1. `[GROUPS]` - Main Signal List

```
# N.     GROUP_NAME    [bg_color]
# N.M    path          radix/type  color  [height]  [alias]
```

### 2. `[VIRTUAL_BUSES]` - Signal Combination

```ini
[VIRTUAL_BUSES]
# Name      =  Signal1, Signal2, ...
VBUS_STATE  =  top.state[2], top.state[1], top.state[0]
```

### 3. `[MARKERS]` - Time Annotations

```ini
[MARKERS]
# Time(ps)   Name          Color
1000000      START_DATA    white
```

---

## Reference: Supported Values

### 1. Radix (`radix/type`)
- `hex`: Hexadecimal
- `bin`: Binary
- `dec`: Decimal
- `oct`: Octal
- **`analog`**: Displays the signal as an analog waveform

### 2. Colors (`color` / `bg_color`)
The tool maps these names to standard Verdi color IDs (e.g., `ID_RED5`):
- `red`, `green`, `blue`, `yellow`, `cyan`, `magenta`, `white`, `black`
- `gray`, `orange`, `pink`, `brown`, `purple`

### 3. Signal Height (`height`)
- Integer value in pixels. (Default: `15`)

---

## Key Features

1. **RC Reuse (Default)**: RC files are independent of the FSDB path. Startup is fast.
2. **Integrated Syntax**: Uses single-line `addSignal` commands for maximum compatibility.
3. **Analog Waveforms**: Simply set radix to `analog` for IQ/Filter data.
4. **Virtual Buses**: Combine bits into buses instantly.
5. **Version Independence**: Uses standard RC syntax compatible across Verdi versions.

---

## Generated Output (`output/{BASE}_{SCN}.rc`)

A standard Verdi Signal Save file. Example:
```tcl
addSignal -h 15 -color ID_CYAN5 -HEX /top/dut/addr[31:0]
addSignal -h 80 -color ID_GREEN5 -analog /top/dut/tx_iq_q
addBus -h 30 -color ID_YELLOW5 -HEX -name "MY_BUS"
```
