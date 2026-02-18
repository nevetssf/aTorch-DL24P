# aTorch DL24P Test Bench & Viewer

A cross-platform suite of applications for controlling the aTorch DL24P electronic load and analyzing battery test data with professional visualization.

## Overview

This project includes **two applications**:

1. **Test Bench** - Real-time device control and data acquisition
2. **Test Viewer** - Offline analysis and comparison of saved test data

Both applications are designed for battery testing, characterization, and quality control with publication-quality plots and comprehensive data export.

## Features

### Test Bench (`python -m atorch.main`)

**Device Control:**
- USB HID connection (no serial adapter needed)
- Real-time plotting with auto-scaling
- Live monitoring of voltage, current, power, temperature, capacity, and energy
- Four load modes: Constant Current (CC), Constant Power (CP), Constant Voltage (CV), Constant Resistance (CR)

**Test Panels:**
- **Battery Capacity** - Discharge tests with voltage cutoff and time limits
- **Battery Load** - Load curve characterization (current/power/resistance sweep)
- **Battery Charger** - Charger output characterization
- **Wall Charger** - AC adapter load testing
- **Power Bank** - Power bank capacity and efficiency testing

**Data Management:**
- SQLite database for permanent storage
- Auto-save to JSON with test metadata
- Export to CSV, JSON, or Excel
- Database management tools (statistics, purge)
- Session state persistence across restarts

**Battery Presets:**
- 30+ camera battery presets (Canon, Nikon, Lumix, Leica, etc.)
- Household battery presets (Eneloop, 18650, etc.)
- User-defined custom presets
- Manufactured date tracking

**Automation:**
- Configurable test profiles
- Voltage cutoff detection
- Time-based tests
- Progress tracking with capacity estimation
- Alert notifications

### Test Viewer (`python -m atorch.viewer`)

**Analysis Features:**
- Multi-file comparison with checkbox selection
- Publication-quality matplotlib + seaborn plots
- Independent rendering per test type
- Color-coded datasets with legend
- X-axis selection (Time, Current, Power, Load R, Capacity, Energy)
- Y-axis auto-scaling with nice multiples (1, 2, 5, 10)

**Data Organization:**
- Automatic file discovery and categorization
- Filter by test type (Battery Capacity, Battery Load, etc.)
- Sort by date, manufacturer, name, capacity
- Display manufactured date and test conditions
- JSON and raw data viewers

**File Management:**
- Auto-reload when files change
- Preserve checkbox states across refreshes
- Date timestamps for test grouping
- Delete tests directly from viewer

## Screenshots

*Coming soon*

## Requirements

- **Python 3.10+**
- **Operating System:** Windows, macOS, or Linux
- **Hardware:** aTorch DL24P electronic load (VID=0x0483, PID=0x5750)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/nevetssf/aTorch-DL24P.git
   cd aTorch-DL24P
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Test Bench Application

Run the main application:
```bash
python -m atorch.main
```

**macOS: First-Time Setup After Power Cycle**

After power-cycling the DL24P, macOS requires a one-time initialization step before the app can communicate with the device. This is because macOS's HID driver uses SET_REPORT control transfers, while the DL24P firmware needs interrupt OUT transfers for its initialization sequence.

```bash
# Install libusb (one-time)
brew install libusb
pip install pyusb

# Run after each device power cycle (requires sudo for USB endpoint access)
sudo DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python usb_prepare.py
```

This sends the SET_IDLE HID class request and initialization sequence that Windows sends automatically during USB enumeration. You only need to run this once after power-cycling the device — the device retains its initialized state across USB disconnects.

**Quick Start:**
1. Connect your DL24P via USB
2. On macOS, run `usb_prepare.py` if the device was power-cycled (see above)
3. Select "USB HID" connection type and click "Connect"
3. Choose a test panel (Battery Capacity, Battery Load, etc.)
4. Configure test parameters
5. Click "Start Test"
6. Data is automatically saved to `~/.atorch/tests.db` and JSON files

**Battery Capacity Test:**
1. Select a battery preset or enter specs manually
2. Set discharge current (CC mode)
3. Set voltage cutoff (e.g., 3.0V for Li-Ion)
4. Optionally enable time limit
5. Click "Start Test"
6. Test stops automatically at cutoff voltage

**Battery Load Test:**
1. Configure load sweep (current, power, or resistance)
2. Set starting value, increment, and steps
3. Set dwell time per step
4. Click "Start Test"
5. Creates a load curve showing voltage vs. load

### Test Viewer Application

Run the viewer:
```bash
python -m atorch.viewer
```

**Quick Start:**
1. Application auto-loads test files from `~/.atorch/test_data/`
2. Switch between test type tabs (Battery Capacity, Battery Load, etc.)
3. Check boxes to select datasets for comparison
4. Choose X-axis parameter (Time, Current, Power, etc.)
5. Toggle Y-axis parameters (Voltage, Current, etc.)
6. Click color buttons to change dataset colors
7. View raw JSON or delete tests using buttons

## Building Executables

Create standalone executables for distribution:

### Windows:
```bash
python build.py
# Creates: dist/aTorch DL24P.exe
```

### macOS:
```bash
python build.py
# Creates: dist/aTorch DL24P.app
```

The build script automatically:
- Bundles all dependencies
- Includes battery presets and resources
- Creates platform-specific icons
- Generates single-file executables

## User Data Locations

All user data is stored in `~/.atorch/`:

- `tests.db` - SQLite database (permanent storage)
- `test_data/` - Auto-saved JSON test results
- `battery_capacity_session.json` - Battery Capacity panel state
- `battery_load_session.json` - Battery Load panel state
- `battery_presets/` - User-saved battery presets
- `test_presets/` - User-saved test configuration presets
- `battery_load_presets/` - Battery Load test presets

On Windows: `C:\Users\<YourName>\.atorch\`

## Project Structure

```
atorch/
├── atorch/
│   ├── protocol/         # Device communication (USB HID, serial)
│   ├── gui/              # Test Bench GUI panels
│   ├── viewer/           # Test Viewer application
│   ├── data/             # Database and export
│   ├── automation/       # Test profiles and runner
│   └── alerts/           # Notifications
├── tests/                # Unit tests (118 tests)
├── resources/            # Battery presets, icons
│   ├── battery_capacity/ # Camera and household battery presets
│   ├── power_bank/       # Power bank presets
│   └── icons/            # Application icons
├── build.py              # PyInstaller build script
└── run_atorch.py         # Launcher for frozen builds
```

## Testing

Run the test suite:
```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_protocol.py  # Specific test file
```

**Test Coverage:** 118 tests across 6 test files:
- Protocol encoding/decoding
- Database operations
- Test profiles and serialization
- Alert conditions
- CSV/JSON export
- PX100 protocol (legacy)

## Cross-Platform Compatibility

This application is fully cross-platform:

- **GUI:** PySide6 (Qt) - native look and feel on all platforms
- **Plots:** pyqtgraph, matplotlib, seaborn - cross-platform rendering
- **USB Communication:** hidapi - Windows/macOS/Linux support
- **Database:** SQLite - built into Python
- **File Paths:** pathlib - platform-independent

Tested on:
- macOS (Darwin 25.2.0)
- Windows 10/11
- Linux (Ubuntu 22.04+)

## Known Issues

See [TODO.md](TODO.md) for items being worked on.

**Current Limitations:**
- **macOS power-cycle initialization:** After power-cycling the DL24P, run `usb_prepare.py` once before using the app (see Quick Start above). This is not needed on Windows, where the OS sends the required HID class requests automatically during USB enumeration.
- Bluetooth/serial connection not fully functional (use USB HID instead)
- Device timing readout may need calibration
- Some device commands may not work over USB HID (e.g., Reset Counters)

## Documentation

- **CLAUDE.md** - Development guide and architecture documentation
- **TODO.md** - Roadmap and known issues
- **Protocol Documentation:** https://www.improwis.com/projects/sw_dl24/

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- **GUI Framework:** [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python)
- **Real-time Plotting:** [pyqtgraph](https://www.pyqtgraph.org/)
- **Publication Plots:** [matplotlib](https://matplotlib.org/) + [seaborn](https://seaborn.pydata.org/)
- **USB HID Support:** [hidapi](https://github.com/trezor/cython-hidapi)
- **Serial Communication:** [pyserial](https://github.com/pyserial/pyserial)
- **Data Analysis:** [pandas](https://pandas.pydata.org/) + [numpy](https://numpy.org/)
- **Protocol Documentation:** [Improwis DL24 Project](https://www.improwis.com/projects/sw_dl24/)

## Support

For issues, questions, or feature requests, please open an issue on GitHub:
https://github.com/nevetssf/aTorch-DL24P/issues

---

**Built with ❤️ for battery enthusiasts, engineers, and makers**
