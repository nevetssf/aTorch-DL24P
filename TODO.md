# TODO

## Pending Features

### Placeholder Test Panels
The following test automation tabs are placeholders and need implementation:
- **Battery Charger** - Test and analyze battery charger performance
- **Cable Resistance** - Measure USB cable resistance and voltage drop
- **Charger** - Test power adapter output and efficiency

### PyInstaller Builds
- Windows build not yet tested
- Consider code signing for macOS distribution

### Future Enhancements
- Export to Excel format improvements
- Historical data comparison/overlay features
- Gzip-compressed JSON (.json.gz) for smaller session files (built-in `gzip` module, 70-90% compression)

---

## Resolved Issues

### Test Conditions Save/Load - DONE
- Implemented preset system with Save/Delete buttons
- Default presets in `resources/battery_capacity/presets_test.json`
- User presets saved to `~/.atorch/test_presets/`
- Settings persist across app restarts via `last_session.json`

### Time Limit Setting - RESOLVED
- **Device protocol has two modes**:
  - Minutes mode (flag=0x02): `[minutes, 0x00, 0x00, 0x02]` - for times < 60 min
  - Hours mode (flag=0x01): `[hours, 0x00, 0x00, 0x01]` - for times >= 60 min
- **Limitation**: Device does NOT support combined hours+minutes. When hours > 0, only whole hours are sent (minutes discarded)
- **pcapng data verified**:
  - 10m: `0a 00 00 02` (10 minutes, minutes mode)
  - 30m: `1e 00 00 02` (30 minutes, minutes mode)
  - 45m: `2d 00 00 02` (45 minutes, minutes mode)
  - 1h45m: `01 00 00 01` (1 hour only, hours mode - 45min dropped by PC app!)
- **Implementation**: Fixed in `set_discharge_time()` to use correct mode based on hours value

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

### Device Timing Readout
- **Issue**: The device time display in the GUI doesn't match the physical device display
- **Current state**: Tried offsets 20, 28 with various interpretations (raw seconds, ticks/48)
- **Device shows**: 10:24 (minutes:seconds)
- **GUI shows**: Different value
- **Notes**: Need to find correct offset and/or encoding for the load-on runtime counter

### GUI Freezing During Long Tests - UNDER INVESTIGATION
- **Issue**: GUI freezes after ~1-1.5 hours of continuous test running
- **Observed freezes**: ~30min, ~1h26m, ~1h30m
- **Fixes applied (2026-02-09)**:
  1. Signal queue overflow prevention - skip updates if still processing previous one
  2. Database commit batching - commit every 10s instead of per-reading
  3. Reduced USB HID polling from 0.5s to 1.0s
  4. Removed periodic auto-save during acquisition
- **Status**: Testing in progress - user running long-duration test to verify
- **If still freezing, investigate**:
  - Debug file logging blocking main thread
  - Plot panel memory with 3600+ data points
  - Unbounded `_accumulated_readings` list growth
  - Unbounded `_current_session.readings` list growth
- **Reference**: See CLAUDE.md "GUI Freezing Issues" section for full details

### Display Precision vs USB Protocol Precision - NEEDS INVESTIGATION
- **Issue**: Device screen shows more precision than USB protocol transmits
- **Current state**: Device transmits integer values via USB HID:
  - Current: integer mA (e.g., 49 mA, not 49.123 mA)
  - Power: integer mW (calculated from V×I)
  - Energy: integer mWh (e.g., 2 mWh, not 1.84 mWh)
- **Device screen**: Shows calculated values with more precision (e.g., 1.84 mWh)
- **App display**: Shows integer values with .000 decimal places (e.g., 2.000 mWh)
- **Root cause**: DL24P firmware rounds to integers before USB transmission
- **Current workaround**: Display with 3 decimals (shows .000 for integer values)
- **Possible improvements**:
  - Calculate energy locally from accumulated V×I×time for more precision
  - Interpolate between readings for smoother display
  - Add option to show calculated vs device-reported values
  - Document limitation in user guide
- **Note**: Saved data (JSON, CSV) uses same precision as USB protocol

### Battery Resistance Protocol Parsing - NEEDS INVESTIGATION
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

### Window Recovery Responsivity
- **Issue**: Application may be slow to respond when recovering the window after being minimized for extended periods
- **Impact**: Affects usability when user returns to the app after leaving it minimized
- **Investigation needed**:
  - Check if GUI update throttling is too aggressive during minimized state
  - Verify Qt event processing resumes properly on window restore
  - Consider if data backlog builds up during minimize (plots, status updates)
  - Test if polling thread continues running and queuing updates
- **Possible solutions**:
  - Detect window minimize/restore state changes
  - Pause non-critical updates when minimized
  - Force refresh/redraw on window restore event
  - Clear stale queued updates on restore
