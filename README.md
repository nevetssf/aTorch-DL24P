# aTorch DL24P Control & Logging Application

A cross-platform GUI application to control the aTorch DL24P electronic load and log battery discharge data with real-time visualization.

## Features

- **USB HID Connection** - Direct USB connection to DL24P (no serial adapter needed)
- **Real-time Plotting** - Live graphs for voltage, current, power, temperature, and capacity
- **Data Logging** - Record discharge tests with SQLite storage
- **Export** - Save data to CSV, JSON, or Excel formats
- **Test Automation** - Configure discharge and timed tests with profiles
- **Device Control** - Set current, voltage cutoff, and time limits

## Screenshots

*Coming soon*

## Requirements

- Python 3.10+
- macOS or Windows
- aTorch DL24P electronic load

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/nevetssf/aTorch-DL24P.git
   cd aTorch-DL24P
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application:
```bash
python -m atorch.main
```

### Quick Start

1. Connect your DL24P via USB
2. Select "USB HID" connection type
3. Click "Connect"
4. Set your desired current and voltage cutoff
5. Click "Start Test" in the Test Automation panel

### Data Logging

- Use the **Logging** toggle in the Data Logging section to start/stop recording
- Click **Save Data...** to export to CSV, JSON, or Excel
- Click **Clear** to reset the plot data

### Test Automation

1. Set test parameters (Current, V Cutoff, Duration)
2. Click **Start Test** to begin
3. Use **Pause** to temporarily stop (data is preserved)
4. Click **Stop Test** to end the test

## Project Structure

```
atorch/
├── atorch/
│   ├── protocol/      # Device communication (USB HID)
│   ├── gui/           # PySide6 GUI components
│   ├── data/          # Database and export
│   ├── automation/    # Test profiles and runner
│   └── alerts/        # Notifications
├── tests/             # Unit tests
└── resources/         # Icons and styles
```

## Known Issues

See [TODO.md](TODO.md) for items being worked on:
- Device timing readout needs calibration
- Reset Counters may not work over USB HID
- Time Limit minutes setting needs protocol investigation

## License

MIT License

## Acknowledgments

- Built with [PySide6](https://doc.qt.io/qtforpython/) and [pyqtgraph](https://www.pyqtgraph.org/)
- USB HID support via [hidapi](https://github.com/trezor/cython-hidapi)
