# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

aTorch DL24P Control is a PySide6 GUI application for controlling the aTorch DL24P electronic load via USB HID. Used primarily for battery discharge testing with real-time data visualization.

## Commands

```bash
# Run the application
python -m atorch.main

# Run all tests
pytest

# Run a single test file
pytest tests/test_protocol.py

# Run with verbose output
pytest -v
```

## Architecture

### Device Communication (`atorch/protocol/`)

Two device classes with identical APIs:
- `Device` - Serial communication (Bluetooth, legacy)
- `USBHIDDevice` - USB HID communication (primary, VID=0x0483, PID=0x5750)

Both use a polling thread that queries the device every 500ms for:
1. Counters (sub-cmd 0x05) - voltage, current, capacity, temperature, load state
2. Live data (sub-cmd 0x03) - mode settings, value_set, voltage cutoff

**USB HID Protocol Format:**
- Commands: `55 05 [cmd_type] [sub_cmd] [data...] [checksum] EE FF` (64 bytes padded)
- Responses: `AA 05 [cmd_type] [sub_cmd] [payload...] EE FF`
- Checksum: `(sum of bytes from offset 2 to end of data) XOR 0x44`

**Mode Numbering Mismatch:**
- GUI buttons: 0=CC, 1=CP, 2=CV, 3=CR
- Device internal: 0=CC, 1=CV, 2=CR, 3=CP
- Translation required when reading mode from device status

### GUI Structure (`atorch/gui/`)

- `MainWindow` - Orchestrates device connection, manages `TestRunner`, routes status updates
- `ControlPanel` - Connection UI, mode buttons (CC/CP/CV/CR), load on/off, parameter spinboxes
- `PlotPanel` - Real-time pyqtgraph plots with auto-scaling
- `StatusPanel` - Live readings display (voltage, current, power, temperature)
- `AutomationPanel` - Test profiles, start/stop/pause controls

### Data Flow

1. `USBHIDDevice._poll_loop()` queries device, parses response into `DeviceStatus`
2. Status callback triggers `MainWindow._on_status_updated()`
3. MainWindow emits `status_updated` signal to all panels
4. Each panel updates its UI from the `DeviceStatus` dataclass

### Test Automation (`atorch/automation/`)

`TestRunner` manages discharge tests with configurable:
- Current setpoint
- Voltage cutoff (stop condition)
- Time limit (hours/minutes)

Profiles saved as JSON in `profiles/` directory.

## Key Files

- `atorch/protocol/device.py` - USB HID communication, packet building, response parsing
- `atorch/protocol/atorch_protocol.py` - `DeviceStatus` dataclass, serial protocol (legacy)
- `atorch/gui/control_panel.py` - Mode switching, parameter sync between GUI and device
- `atorch/gui/main_window.py` - Application lifecycle, device connection handling

## Known Protocol Details

- Temperatures from device are in milli-°C (divide by 1000)
- Energy is in mWh at offset 20 of counters response
- Load on/off flag at byte 48 of counters payload
- Query commands must NOT include extra data bytes (breaks checksum)

## USB HID Sub-Commands

| Sub-Cmd | Description |
|---------|-------------|
| 0x03 | Get live data (mode, value_set, voltage cutoff) |
| 0x05 | Get counters (voltage, current, capacity, temperature) |
| 0x21 | Set current/power/voltage/resistance (mode-dependent) |
| 0x22 | Set voltage cutoff |
| 0x25 | Power on/off (0x01=on, 0x00=off) |
| 0x31 | Set discharge time (hours/minutes) |
| 0x33 | Restore factory defaults |
| 0x34 | Clear accumulated data (mAh, Wh, time) |

## Qt Threading Safety

**Critical**: Device status callbacks run in a background thread. Never access GUI elements or perform database operations directly from callbacks.

Pattern used:
1. Device callback emits a signal: `self.status_updated.emit(status)`
2. Main thread slot handles UI updates: `@Slot(DeviceStatus) def _update_ui_status()`

## User Data Locations

All user data stored in `~/.atorch/`:
- `last_session.json` - Persisted settings (restored on app restart)
- `battery_presets/` - User-saved battery presets
- `test_presets/` - User-saved test configuration presets
- `test_data/` - Auto-saved JSON test results
- `tests.db` - SQLite database for test sessions

## Preset Organization

Default presets in `resources/battery_capacity/`:
- `presets_camera.json` - Camera batteries (Canon, Leica, Lumix, Nikon, etc.)
- `presets_household.json` - Household batteries (Eneloop NiMH, Imuto Li-Ion)
- `presets_test.json` - Test configuration presets (CC, CP, CR modes)

Each battery preset includes `technology` field (Li-Ion, NiMH, LiPo, etc.)

## Collapsible Panel Implementation

The Test Automation panel uses a custom collapse approach:
- Toggle button with arrow (▼/▶) controls visibility
- Only `bottom_tabs` is hidden, header stays visible
- Window height adjusted via `setFixedHeight()` during toggle, then constraints removed
- `automation_content.setFixedHeight(0)` when collapsed prevents layout issues

## PyInstaller Builds

Build script: `build.py` using `run_atorch.py` as entry point (handles frozen imports).

```bash
python build.py  # Creates dist/aTorch DL24P.app (macOS) or .exe (Windows)
```

Hidden imports required: PySide6, pyqtgraph, numpy, pandas, serial, hid

## External Resources

- **DL24 Protocol Documentation**: https://www.improwis.com/projects/sw_dl24/
  - Covers both PX100 (legacy) and Atorch protocols
  - Packet structures, checksum calculation, command codes
  - Hardware architecture details (HC32F030E8PA MCU, RN8209C power measurement)
