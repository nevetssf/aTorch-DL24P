# Items to Revisit

## Test Configuration Save/Load
- **Issue**: Need to fix what is saved and loaded in Test Configuration profiles
- **Notes**: Review the JSON profile format and ensure all relevant parameters are included
- **Also**: Show the configuration/profile name in the UI

## Time Limit Setting - RESOLVED
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

## Device Timing Readout
- **Issue**: The device time display in the GUI doesn't match the physical device display
- **Current state**: Tried offsets 20, 28 with various interpretations (raw seconds, ticks/48)
- **Device shows**: 10:24 (minutes:seconds)
- **GUI shows**: Different value
- **Notes**: Need to find correct offset and/or encoding for the load-on runtime counter
