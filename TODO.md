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
- Bluetooth connectivity support (USB HID is primary)
- Export to Excel format improvements
- Historical data comparison/overlay features

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

### Device Timing Readout
- **Issue**: The device time display in the GUI doesn't match the physical device display
- **Current state**: Tried offsets 20, 28 with various interpretations (raw seconds, ticks/48)
- **Device shows**: 10:24 (minutes:seconds)
- **GUI shows**: Different value
- **Notes**: Need to find correct offset and/or encoding for the load-on runtime counter
