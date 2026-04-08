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
- `hex`: Hexadecimal (Default for buses)
- `bin`: Binary (Default for 1-bit)
- `dec`: Decimal
- `oct`: Octal
- **`analog`**: Displays the signal as an analog waveform (Step/Linear)

### 2. Colors (`color` / `bg_color`)
Standard Verdi color names are supported:
- **Primary**: `red`, `green`, `blue`, `yellow`, `cyan`, `magenta`, `white`, `black`
- **Secondary**: `gray`, `orange`, `pink`, `brown`, `purple`
- **Light Variants**: `lightyellow`, `lightcyan`, `lightgray`
- **Inherit**: `-` (dash) in the signal color column inherits the group color.

### 3. Signal Height (`height`)
- Integer value in pixels.
- Default: `15`
- Recommended for Analog: `80` ~ `120`
- Recommended for Buses: `25` ~ `35`

### 4. Font Configuration
Fonts in Verdi are usually set via the global resource file or a TCL command.
While individual signal font setting is less common in standard RC files, you can adjust the global display font in Verdi via:
- `Tools -> Options -> Waveform -> Font`
- Common values: `Arial 10`, `Courier 12`, `Fixed 10`

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
