# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

aTorch DL24P Control is a PySide6 GUI application for controlling the aTorch DL24P electronic load via USB HID. Used primarily for battery discharge testing with real-time data visualization.

## Development Guidelines

**IMPORTANT**: Always verify method names and API calls before implementing functionality:
- Do NOT assume method names - always check the actual implementation in the codebase
- Use Grep or Read tools to verify the correct method signatures
- Example: Device control uses `turn_on()` and `turn_off()`, NOT `set_load_on()`
- Check both `Device` and `USBHIDDevice` classes as they should have identical APIs
- When in doubt, search the codebase for existing usage patterns

## Commands

```bash
# Run the application (Test Bench - device control + testing)
python -m atorch.main

# Run the Test Viewer (standalone, no device needed)
python -m atorch.viewer

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
- Commands: `55 05 [cmd_type] [sub_cmd] [data...] EE FF` (64 bytes zero-padded, no checksum)
- Responses: `AA 05 [cmd_type] [sub_cmd] [payload...] EE FF`
- Init: `55 05 [01-0a] 04 00 00 00 00 EE FF` (fire-and-forget, ~160ms apart)
- Queries: `55 05 01 [03|05] EE FF` (device responds with payload)
- Set value: `55 05 01 [sub_cmd] [4-byte IEEE 754 float] EE FF`

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

**Data Storage During Logging:**
- Readings are stored in TWO places (NOT in `_current_session.readings`):
  1. **Database** - Background thread writes every reading via `_db_queue`
  2. **`_accumulated_readings`** - Bounded deque (maxlen=172800, ~48 hours at 1Hz)
- JSON export uses `_accumulated_readings`, NOT `_current_session.readings`
- IMPORTANT: Do NOT append to `_current_session.readings` - it's an unbounded list that causes GUI hang

### Graph Display Configuration by Test Type

When loading test data from the History panel, the graph axes should be configured appropriately for each test type:

**Battery Capacity:**
- X-axis: Time
- Y-axis: Voltage (V) enabled by default
- Purpose: Shows voltage discharge curve over time

**Battery Load:**
- X-axis: Current, Power, or Load R (depending on load_type in test_config)
  - Current tests: X = Current (A)
  - Power tests: X = Power (W)
  - Resistance tests: X = Load R (Ω)
- Y-axis: Voltage (V) enabled by default
- Purpose: Shows voltage vs. load characteristic curve

**Future Test Types:**
As new test panels are implemented, add their graph configurations here:
- Battery Charger: TBD
- Cable Resistance: TBD
- Charger: TBD
- Power Bank: TBD

Implementation: See `_on_history_json_selected()` and `_load_battery_load_history()` in `main_window.py`

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

## Lock Timeout for GUI Operations

**Problem**: When screen turns off or system enters power management, macOS suspends/throttles USB devices. This causes USB I/O to become slow (1-3+ seconds instead of 500ms), and the poll thread holds the device lock during this slow I/O. Any GUI operation that needs the device (turn on/off, change settings) blocks waiting for the lock, making the GUI sluggish.

**Solution**: All device methods called from GUI use a 1-second lock timeout:
```python
GUI_LOCK_TIMEOUT = 1.0  # seconds

def turn_on(self) -> bool:
    return self._send_command(..., lock_timeout=self.GUI_LOCK_TIMEOUT)
```

**Benefits**:
- GUI operations fail gracefully after 1 second instead of blocking indefinitely
- User gets immediate feedback (button press doesn't hang)
- Command-response atomicity maintained (lock still held during USB I/O)
- Poll thread unaffected (uses no timeout, blocks as needed)

**Tradeoff**: GUI operations might fail if device is busy, but this is preferable to a frozen UI.

## Debug Window Optimization

**Problem**: Debug window was updated on every device poll (6 messages/second = 21,600/hour) even when hidden, causing GUI sluggishness over time. Each update performs HTML formatting, DOM updates, line counting, and scrolling on the main thread.

**Solution**: Only update debug window when visible:
```python
def _on_debug_message(self, event_type: str, message: str, data: bytes) -> None:
    # ... file logging ...

    if not self.debug_window.isVisible():
        return  # Skip GUI updates when hidden

    self.debug_window.log(message, event_type)
```

**Impact**: Eliminates 21,600+ GUI operations per hour when debug window is closed, significantly improving long-term responsiveness.

## User Data Locations

All user data stored in `~/.atorch/`:
- `battery_capacity_session.json` - Battery Capacity panel state (restored on app restart)
- `battery_load_session.json` - Battery Load panel state (restored on app restart)
- `battery_presets/` - User-saved battery presets
- `test_presets/` - User-saved test configuration presets (Battery Capacity)
- `battery_load_presets/` - User-saved test configuration presets (Battery Load)
- `test_data/` - Auto-saved JSON test results
- `tests.db` - SQLite database for test sessions (permanent storage, accessible via Tools → Database Management)

## Test Automation Panel State Persistence

**IMPORTANT**: All Test Automation panels MUST save and restore their state on app restart.

Each panel should:
1. Save all UI settings to a panel-specific JSON file in `~/.atorch/` (e.g., `battery_capacity_session.json`, `battery_load_session.json`)
2. Implement `_save_session()` - saves all form fields to JSON
3. Implement `_load_session()` - restores all form fields from JSON on startup
4. Implement `_connect_save_signals()` - connects all UI widgets to trigger auto-save
5. Use `_loading_settings` flag to prevent recursive saves during load
6. Save whenever any field changes (auto-save pattern)

State to persist includes:
- Test configuration parameters (all spinboxes, combos, checkboxes)
- Battery info fields (name, manufacturer, capacity, etc.)
- Selected presets (both battery and test presets)
- Any other user-configurable settings

Pattern:
```python
self._loading_settings = False
self._session_file = self._atorch_dir / "panel_name_session.json"

def _connect_save_signals(self):
    # Connect all widgets to _on_settings_changed
    self.some_widget.valueChanged.connect(self._on_settings_changed)

def _on_settings_changed(self):
    if not self._loading_settings:
        self._save_session()
```

## Preset Organization

Default presets in `resources/battery_capacity/`:
- `presets_camera.json` - Camera batteries (Canon, Leica, Lumix, Nikon, etc.)
- `presets_household.json` - Household batteries (Eneloop NiMH, Imuto Li-Ion)
- `presets_test.json` - Test configuration presets (CC, CP, CR modes)

Each battery preset includes `technology` field (Li-Ion, NiMH, LiPo, etc.)

## Database Management

The database management dialog (`Tools → Database Management`) provides:

**Statistics Display:**
- File location (with "Show in Folder" button)
- File size (human-readable format: B/KB/MB/GB)
- Created date/time
- Last modified date/time
- Number of sessions stored
- Total number of readings

**Database Purge:**
- Permanently deletes all sessions and readings from `tests.db`
- Two-step confirmation: dialog + type "DELETE" to confirm
- Exported JSON/CSV files are NOT affected (remain on disk)
- Use case: Clean up test database after long testing periods

**Implementation:** `atorch/gui/database_dialog.py` - DatabaseDialog class

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

## Debugging

When debugging device communication issues:
1. **Always check `debug.log`** in the project root - it contains timestamped SEND/RECV/INFO/ERROR events
2. Run the app with Debug Log checkbox enabled (on by default)
3. Look for:
   - `RECV` entries to confirm data is being received
   - `PARSE` entries to see decoded packet contents
   - `ERROR` entries for communication failures
4. Use `tail -f debug.log` to monitor in real-time

## Protocol Differences: USB HID vs Bluetooth

**USB HID** (primary, working):
- Host must poll device - device does NOT push data
- Uses custom HID protocol with `55 05` header
- Polling every 500ms for counters (0x05) and live data (0x03)

**Bluetooth/Serial** (not working - see TODO.md):
- Tested both Atorch (`FF 55` header) and PX100 (`B1 B2` header) protocols
- Device connects but never responds to any commands or queries
- Likely uses proprietary protocol only supported by official app
- **Recommendation**: Use USB HID instead (fully functional)

## External Resources

- **DL24 Protocol Documentation**: https://www.improwis.com/projects/sw_dl24/
  - Covers both PX100 (legacy) and Atorch protocols
  - Packet structures, checksum calculation, command codes
  - Hardware architecture details (HC32F030E8PA MCU, RN8209C power measurement)

## GUI Freezing Issues - Session Notes (2026-02-09)

### Problem
The GUI was freezing after ~1-1.5 hours of continuous test running. User reported freezes at 30min, 1h26m, and 1h30m intervals.

### Root Causes Identified

1. **Signal Queue Overflow**: Device status updates were emitted at 2 Hz (0.5s intervals), but if `_update_ui_status()` occasionally took longer than 0.5s, Qt signals would queue up faster than they were processed. Over hours, this queue could grow to thousands of pending signals.

2. **Database Commit Overhead**: `database.add_reading()` was calling `commit()` after every single INSERT. At 1 Hz logging, that's 5400+ commits over 1.5 hours. SQLite commits involve fsync which is expensive.

3. **Periodic Auto-save (removed)**: Was writing full JSON files every 30 seconds, which blocked the main thread.

### Fixes Implemented

1. **Signal Queue Prevention** (`main_window.py`):
   ```python
   self._processing_status = False  # Flag in __init__

   def _on_device_status(self, status):
       if self._processing_status:
           return  # Skip if still processing previous update
       self.status_updated.emit(status)

   def _update_ui_status(self, status):
       self._processing_status = True
       try:
           self._do_update_ui_status(status)
       finally:
           self._processing_status = False
   ```

2. **Database Commit Batching** (`database.py`, `main_window.py`):
   - `add_reading()` now has `commit=False` default parameter
   - Added `database.commit()` method
   - Main window commits every 10 seconds via `_last_db_commit_time` tracking
   - Explicit `database.commit()` called when session ends

3. **Reduced Polling Rate** (`device.py`):
   - Changed `USBHIDDevice.POLL_INTERVAL` from 0.5s to 1.0s
   - Now matches serial device rate, reduces main thread pressure

4. **Removed Periodic Auto-save**:
   - JSON auto-save during acquisition was removed
   - Data only saved when test completes (load turns off) or user clicks Save

5. **Stopped Appending to `_current_session.readings`** (unbounded list):
   - This was an unbounded Python list that grew indefinitely, causing memory pressure
   - All data is preserved in two places:
     - Database: Background thread writes every reading (permanent storage)
     - `_accumulated_readings`: Bounded deque with maxlen=172800 (48 hours at 1Hz)
   - JSON export uses `_accumulated_readings`, NOT `_current_session.readings`
   - `TestSession.readings` is now left empty during logging (only used for count display)

### Key Code Locations

- `main_window.py:95` - `_processing_status` flag initialization
- `main_window.py:988-992` - Signal queue prevention in `_on_device_status`
- `main_window.py:1014-1022` - `_update_ui_status` wrapper with try/finally
- `main_window.py:1039-1044` - Periodic database commit logic
- `database.py:149-185` - Modified `add_reading()` with optional commit
- `device.py:591` - `POLL_INTERVAL = 1.0`

### Testing Status

User is currently running a long-duration test to verify fixes. Previous freezes occurred at:
- ~30 minutes
- ~1 hour 26 minutes
- ~1 hour 30 minutes

If freezing persists, investigate:
1. Debug file logging (`_on_debug_message`) - writes to file on every device message if enabled
2. Plot panel memory usage - pyqtgraph with 3600+ points (added downsampling/clipping optimizations)
3. `_accumulated_readings` is bounded (maxlen=172800) so should not be an issue

### Reference
Forum post on PySide threading issues: https://forum.pythonguis.com/t/struggling-with-pyside-i-want-help-with-ui-freezing-issue/1951

Key insight: Use QThreadPool with QRunnable for heavy operations, or implement rate limiting to prevent signal queue buildup.

## Test Coverage

118 tests total across 6 test files:
- `test_protocol.py` (38) - Atorch protocol encoding/decoding
- `test_database.py` (13) - SQLite operations and models
- `test_profiles.py` (12) - Test profile serialization
- `test_alerts.py` (30) - Alert conditions (voltage, temp, capacity, etc.)
- `test_export.py` (19) - CSV and JSON export
- `test_px100_protocol.py` (31) - PX100 protocol commands/parsing

Run with: `pytest -v`
