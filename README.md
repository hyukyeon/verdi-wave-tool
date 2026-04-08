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

A scenario file can contain three sections: `[GROUPS]`, `[VIRTUAL_BUSES]`, and `[MARKERS]`.

### 1. `[GROUPS]` - Main Signal List
Defines the visual hierarchy in nWave.

```
# N.     GROUP_NAME    [bg_color]
# N.M    path          radix/type  color  [height]  [alias]
```

- **radix/type**: `hex`, `bin`, `dec`, `oct` or **`analog`** (for wave display).
- **path**: Use prefix keys from `scn_base.lst` (e.g., `top.sig`) or a name defined in `[VIRTUAL_BUSES]`.

### 2. `[VIRTUAL_BUSES]` - Signal Combination
Combine multiple discrete bits into a single bus for display.

```ini
[VIRTUAL_BUSES]
# Name      =  Signal1, Signal2, ...
VBUS_STATE  =  top.state[2], top.state[1], top.state[0]
```

### 3. `[MARKERS]` - Time Annotations
Place markers at specific simulation times (in ps) automatically.

```ini
[MARKERS]
# Time(ps)   Name          Color
1000000      START_DATA    white
5500000      IRQ_TRIGGER   red
```

---

## Advanced Features Example (`config/scn_example.lst`)

```ini
[GROUPS]
1.     RF_SIGNALS      lightcyan
1.1    top.tx_i        analog      cyan    80      TX_I_WAVE
1.2    top.tx_q        analog      green   80      TX_Q_WAVE

2.     STATE_MON       yellow
2.1    VBUS_STATE      hex         yellow  30      CURR_STATE

[VIRTUAL_BUSES]
VBUS_STATE  =  top.s0, top.s1, top.s2

[MARKERS]
1000000    INIT_DONE     white
```

---

## Key Features

1. **RC Reuse (Default)**: RC files are independent of the FSDB path. Startup is fast as long as the scenario config hasn't changed.
2. **Analog Waveforms**: Simply set radix to `analog` to visualize IQ or filter data as graphs.
3. **Virtual Buses**: Combine bits into buses without modifying RTL/Bench code.
4. **Auto-Markers**: Navigate to key simulation events instantly using pre-placed markers.
5. **Version Independence**: Uses standard RC syntax compatible across Verdi versions.

---

## Generated Output (`output/{BASE}_{SCN}.rc`)

A standard Verdi Signal Save file containing:
- `addGroup`, `addSignal`, `addBus`, `addBusSignal`
- `setRadix`, `setAlias`, `addMarker`
- Attributes like `-h` (height), `-C` (color), and `-analog`.
