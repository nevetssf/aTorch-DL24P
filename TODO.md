# TODO

## Pending Features

### PyInstaller Builds
- Windows build not yet tested
- Consider code signing for macOS distribution

### Database Schema Overhaul
- **Issue**: The current database schema and how it's populated are out of sync with how data logging actually works
- The schema was designed early on and hasn't kept pace with changes to the logging pipeline (bounded deque, commit batching, test panel types, etc.)
- Needs a full review of:
  - Table structure (sessions, readings) — do they match current test types and data flow?
  - How sessions are created, updated, and finalized across all test panels
  - Which fields are actually populated vs left empty/stale
  - Whether the schema supports all current test types (battery capacity, battery load, battery charger, charger load, power bank)
  - Alignment between database storage and JSON export format
- Consider migration strategy for existing `tests.db` files

### Future Enhancements
- Export to Excel format improvements
- Historical data comparison/overlay features
- Gzip-compressed JSON (.json.gz) for smaller session files (built-in `gzip` module, 70-90% compression)
- **Clean up parameter naming above the chart** - Review and standardize the labels and units displayed in the control/status area above the plot panel for better clarity and consistency
- **Consider moving Status indicator (ON/OFF) next to Load on/off switch** - May improve UI flow by grouping related controls/indicators together in the Control Panel instead of keeping status in Live Readings panel
- **Standardize reading parameter naming and add missing parameters**
  - Review and clean up parameter names in DeviceStatus dataclass and throughout codebase
  - Ensure consistent naming conventions (e.g., voltage vs V, current vs I, capacity_mah vs capacity)
  - Add missing parameters that device provides but aren't currently exposed
  - Update JSON export schema to use standardized names
  - Consider backwards compatibility for existing JSON test files
  - Document parameter naming conventions in CLAUDE.md

---

## Known Issues

### Bluetooth Communication Not Working
- **Issue**: DL24P connects via Bluetooth SPP but doesn't respond to commands
- **Tested protocols**:
  - Atorch protocol (`FF 55 ...`) - commands sent, no response
  - PX100 protocol (`B1 B2 ...`) - queries sent, no response
- **Port detected**: `/dev/cu.DL24_SPP` (macOS Bluetooth SPP)
- **Possible causes**:
  - Device may use proprietary protocol for Bluetooth (official app only)
  - Bluetooth module may need unknown initialization sequence
  - May only support one-way communication (app -> device)
- **Current state**: USB HID works perfectly; Bluetooth disabled in UI
- **Workaround**: Use USB HID connection (primary supported method)
- **Next step**: Capture Bluetooth traffic from official iOS app using Apple's PacketLogger to reverse-engineer the protocol

### Display Precision vs USB Protocol Precision
- **Issue**: Device screen shows more precision than USB protocol transmits
- **Current state**: Device transmits integer values via USB HID:
  - Current: integer mA (e.g., 49 mA, not 49.123 mA)
  - Power: integer mW (calculated from V×I)
  - Energy: integer mWh (e.g., 2 mWh, not 1.84 mWh)
- **Device screen**: Shows calculated values with more precision (e.g., 1.84 mWh)
- **App display**: Shows integer values with .000 decimal places (e.g., 2.000 mWh)
- **Root cause**: DL24P firmware rounds to integers before USB transmission
- **Possible improvements**:
  - Calculate energy locally from accumulated V×I×time for more precision
  - Interpolate between readings for smoother display
  - Add option to show calculated vs device-reported values
  - Document limitation in user guide
- **Note**: Saved data (JSON, CSV) uses same precision as USB protocol

### Battery Resistance Protocol Parsing
- **Issue**: Battery internal resistance value fluctuates more than expected when reading from device protocol
- **Current location**: Offset 36-37 in counters response (sub-cmd 0x05), uint16 big-endian, milli-ohms
- **Problem**: The bytes overlap with MOSFET temperature (offset 36-39 as uint32 LE)
  - When temp low byte is 0x05: reads as 1380 mΩ (correct, matches device screen)
  - When temp low byte is 0xe6: reads as 58980 mΩ (invalid, device screen shows 1300-1400 mΩ)
- **Validation added**: Only accept values in 1000-2000 mΩ range, ignore others
- **Current workaround**: Using calculated method (R_total - R_load) instead of device value
  - R_total = V / I (total circuit resistance)
  - R_load from device at offset 16-17
  - R_battery = R_total - R_load
- **Device screen shows**: 1300-1400 mΩ stable range (1380 mΩ typical)
- **Next steps**:
  - Investigate if battery R is stored at a different offset
  - Check if there's a different encoding or data packing scheme
  - Monitor more payload samples to find consistent storage location
  - May need to capture USB traffic when battery R changes significantly

---

## Resolved Issues

### Package Rename - DONE (2026-02-19)
- Renamed Python package from `atorch/` to `load_test_bench/`
- All imports, build scripts, pyproject.toml, and tests updated
- Entry point: `run_load_test_bench.py` (was `run_atorch.py`)

### Help System - DONE (2026-02-19)
- Moved from in-app QTextBrowser dialog to standalone HTML opened in system browser
- `resources/help/help.html` with dark mode, table of contents, anchor links
- Help → Connection Troubleshooting opens to #troubleshooting anchor

### Control Panel Mode-Specific Inputs - DONE (2026-02-19)
- After test ends/aborts, only the input for the active mode is re-enabled
- Uses `control_panel._update_mode_controls()` instead of blindly enabling all spinboxes

### All Test Panels Implemented - DONE
- **Battery Capacity** - Constant current discharge with capacity measurement
- **Battery Load** - Stepped load characterization (CC/CR/CP)
- **Battery Charger** - CC-CV charging profile analysis via CV mode simulation
- **Charger Load** - Power adapter output testing with stepped loads
- **Power Bank Capacity** - Full discharge capacity testing with auto-voltage detection

### Auto-Connect on Test Start - DONE
- `_try_auto_connect()` in `main_window.py` works across all test panels
- Automatically connects when Start is clicked if device is detected but not connected

### GUI Freezing During Long Tests - DONE (2026-02-09)
- Signal queue overflow prevention (skip updates if still processing)
- Database commit batching (every 10s instead of per-reading)
- Reduced USB HID polling from 0.5s to 1.0s
- Removed periodic auto-save during acquisition
- Stopped appending to unbounded `_current_session.readings` list
- All data preserved in database and bounded `_accumulated_readings` deque (48h capacity)

### Window Recovery Responsivity - DONE (2026-02-10)
- 1-second lock timeout for GUI-called device methods (fail gracefully vs freeze)
- Debug window only updated when visible (eliminates 21,600+ unnecessary GUI ops/hour)

### Data Directory Migration - DONE (2026-02-18)
- Centralized via `load_test_bench/config.py` → `get_data_dir()`
- macOS: `~/Library/Application Support/Load Test Bench/`
- Legacy `~/.atorch/` auto-migrated on first run
- User presets in `<data_dir>/presets/` (organized by type)

### Test Conditions Save/Load - DONE
- Preset system with Save/Delete buttons across all panels
- Default presets in `resources/` subdirectories
- User presets saved to `<data_dir>/presets/`
- Session state persists across app restarts

### Time Limit Setting - DONE
- Device protocol supports minutes mode (flag=0x02) and hours mode (flag=0x01)
- Device does NOT support combined hours+minutes (limitation of firmware)
- Fixed in `set_discharge_time()` to use correct mode based on hours value
