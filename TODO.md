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

### Test Configuration Save/Load - DONE
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
