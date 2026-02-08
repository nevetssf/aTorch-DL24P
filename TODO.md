# Items to Revisit

## Test Configuration Save/Load
- **Issue**: Need to fix what is saved and loaded in Test Configuration profiles
- **Notes**: Review the JSON profile format and ensure all relevant parameters are included
- **Also**: Show the configuration/profile name in the UI

## Time Limit (Discharge Time) - Minutes Not Setting
- **Issue**: Setting discharge time only sets hours, minutes are ignored
- **Tested formats that didn't work**:
  - `[hours, minutes, 0x00, enable]` - current implementation
  - `[minutes, hours, 0x00, enable]` - swapped
  - `[hours, minutes, enable, 0x00]` - swapped last bytes
  - Total minutes as uint16 LE
  - Various byte positions
  - BCD encoding (0x01, 0x30 for 1h 30m)
  - Combined decimal values
- **Notes**: Need to capture actual USB traffic when setting time via device buttons to find correct format

## Reset Counters Button
- **Issue**: Reset Counters button not working correctly
- **Notes**: May need to find correct USB HID command or sequence

## Device Timing Readout
- **Issue**: The device time display in the GUI doesn't match the physical device display
- **Current state**: Tried offsets 20, 28 with various interpretations (raw seconds, ticks/48)
- **Device shows**: 10:24 (minutes:seconds)
- **GUI shows**: Different value
- **Notes**: Need to find correct offset and/or encoding for the load-on runtime counter
