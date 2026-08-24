---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Load Test Bench — aTorch DL24P Control'
style: |
  section { font-size: 26px; }
  h1 { color: #1a5276; }
  h2 { color: #1a5276; }
  code { color: #a03; }
---

# Load Test Bench
### Controlling the aTorch DL24P Electronic Load

A cross-platform GUI for USB-HID device control & battery discharge testing

---

## Agenda

- What is this project?
- The hardware
- Reverse-engineering the USB HID protocol
- Application architecture
- Threading model & the lessons it taught us
- Live demo

---

# What is this project

To test quality of camera batteries and chargers

- Batteries age with use & over time, and lose current output capacity
- Chargers (even expensive ones!) charge improperly & can be dangerous

Battery
- Total capacity (mAh)
- Discharge curve (V vs capacity)

Charger
- Trickle
- Constant current
- Constant voltage
- Taper off

---

# The Hardware

# What is this project?

---

## Two Applications, One Suite

**Test Bench** — `python -m load_test_bench.main`
Real-time device control + data acquisition (PySide6/Qt)

**Test Viewer** — `python -m load_test_bench.viewer`
Offline analysis of saved test data — no device needed

Both built for battery testing, characterization, and QC
with publication-quality plots and full data export (CSV/JSON/Excel)

---

## Test Types Supported

- **Battery Capacity** — CC discharge with voltage cutoff & time limit
- **Battery Load** — load-curve sweeps (current / power / resistance)
- **Battery Charger** — charger output characterization
- **Charger Load** — AC adapter load testing
- **Power Bank Capacity** — capacity + efficiency testing

Each has a dedicated panel, its own state persistence, and its own
graph configuration in the plot and viewer apps.

---

# The Hardware

## aTorch DL24P

Inexpensive (~$40 on Ali Express) load 180W load sink with 4 modes

- **Constant Current**
- **Constant Voltage**
- Constant Resistance
- Constant Power 

Great hardware, terrible software

- Windows only
- Crash-prone
- Limited functionality & ability to save data

---

## The aTorch DL24P

- Electronic load: sinks current, measures V / I / P / capacity / temp
- USB HID device — **VID 0x0483, PID 0x5750**
- No official cross-platform software — vendor app is Android/Windows only
- We reverse-engineered / adapted a documented protocol
  (protocol docs: improwis.com/projects/sw_dl24)

**The problem:** how do you drive it reliably, in real time, from Python,
on macOS/Windows/Linux, for multi-hour unattended tests?

---

# USB HID Protocol

---

## Packet Format

Device does **not** push data — the host must poll.

```
Commands:  55 05 [cmd_type] [sub_cmd] [data...] EE FF   (64B, zero-padded)
Responses: AA 05 [cmd_type] [sub_cmd] [payload...] EE FF
```

- Init sequence: `55 05 [01-0a] 04 00 00 00 00 EE FF` (fire-and-forget)
- Query: `55 05 01 [03|05] EE FF` → device responds with payload
- Set value: `55 05 01 [sub_cmd] [4-byte IEEE-754 float] EE FF`
- No checksum — but query commands must **not** carry extra data bytes

---

## Polling Loop

Every **1 second**, `USBHIDDevice._poll_loop()` queries two things:

| Sub-Cmd | Purpose |
|---|---|
| `0x05` | Counters — voltage, current, capacity, temperature, load state |
| `0x03` | Live data — active mode, value_set, voltage cutoff |

Key sub-commands for control:

| Sub-Cmd | Action |
|---|---|
| `0x21` | Set current / power / voltage / resistance (mode-dependent) |
| `0x25` | Load on/off |
| `0x31` | Set discharge time |
| `0x34` | Clear accumulated data |

---

## Gotchas We Hit

- **Mode numbering mismatch** — GUI: 0=CC 1=CP 2=CV 3=CR,
  device: 0=CC 1=CV 2=CR 3=CP → explicit translation layer required
- Temperatures arrive in **milli-°C**
- Energy lives at a fixed byte offset (20) in the counters payload
- **macOS-specific:** device needs a one-time `usb_prepare.py` step after
  power-cycle — macOS HID driver uses SET_REPORT, firmware wants interrupt
  OUT transfers (Windows sends this automatically during enumeration)
- Apple Silicon: device isn't detected on Thunderbolt directly — needs a
  USB hub for USB 2.0 speed negotiation

---

# Application Architecture

---

## Layers

```
protocol/    USBHIDDevice / Device — packet building & parsing
automation/  TestRunner, profiles, scheduler — drives a running test
alerts/      Threshold conditions (voltage, temp, capacity...) + notifier
data/        Models, SQLite database, CSV/JSON/Excel export
gui/         Qt panels — one per test type + shared controls
viewer/      Standalone offline analysis app (matplotlib/seaborn + plotly)
```

Two device classes (`Device` serial, `USBHIDDevice` primary) expose
**identical APIs** — panels don't know which transport is underneath.

---

## Data Flow, End to End

```
USBHIDDevice._poll_loop()
        │  parses response → DeviceStatus dataclass
        ▼
device callback → status_updated.emit(status)      [background thread]
        ▼
MainWindow._on_status_updated()                     [Qt main thread]
        ▼
status_updated signal → all panels
        ▼
ControlPanel / PlotPanel / StatusPanel update from DeviceStatus
```

Readings are also queued to a **background DB writer thread** and kept
in a bounded in-memory deque (`_accumulated_readings`, 48h @ 1Hz) for
JSON export — never appended to the unbounded session list.

---

## State Persistence Pattern

Every test panel auto-saves its full configuration to
`sessions/<panel>_session.json` on every change, and restores it on
startup — batteries, presets, cutoffs, everything.

```python
def _connect_save_signals(self):
    self.some_widget.valueChanged.connect(self._on_settings_changed)

def _on_settings_changed(self):
    if not self._loading_settings:   # guards against recursive saves
        self._save_session()
```

Same pattern, repeated consistently across 5 test panels.

---

# Threading Model & Lessons Learned

---

## Rule #1: Never Touch the GUI from a Background Thread

Device polling runs on its own thread. Every device→GUI update goes
through a Qt **signal**, never a direct call:

```python
# background thread
self.status_updated.emit(status)

# main thread
@Slot(DeviceStatus)
def _update_ui_status(self, status): ...
```

GUI-initiated device commands (turn on/off, set params) use a
**1-second lock timeout** so a slow/suspended USB device fails fast
instead of freezing the UI.

---

## Case Study: The 90-Minute Freeze

Long discharge tests would lock up the GUI after ~30–90 minutes.
Three compounding causes:

1. **Signal queue overflow** — if one UI update took >0.5s, Qt signals
   queued faster than they drained; thousands could pile up over hours
2. **SQLite commit-per-row** — `commit()` after *every* reading (fsync
   each time) at 1 Hz → 5,400+ commits in 1.5 hours
3. **Unbounded session list** — `_current_session.readings` grew forever

---

## The Fixes

- **Drop, don't queue:** skip emitting a new status if the previous one
  is still being processed (`_processing_status` flag)
- **Batch commits:** `add_reading(commit=False)`, explicit
  `database.commit()` every 10s and at test end
- **Bounded storage:** replaced the unbounded list with a
  `maxlen=172800` deque; DB is the permanent record
- **Slower, steadier polling:** 0.5s → 1.0s interval
- **Debug window:** only updates its DOM when actually visible
  (was 21,600 GUI ops/hour when just *closed*)

---

# 6. Live Demo

- Connect to the DL24P over USB HID
- Switch modes (CC / CP / CV / CR) and set a value
- Start a Battery Capacity test, watch live plot + status panel
- Open the Test Viewer against a previous session

*(switch to the running app)*

---

# 7. What's Next

- **Database schema overhaul** — bring `tests.db` schema back in sync
  with how logging actually works today (bounded deque, batched commits,
  all 5 test panel types)
- **Pre-test reset sequence** — load off → clear counters → 5s settle
  → start, consistently across all panels
- Parameter-naming cleanup across `DeviceStatus` / JSON export
- PyInstaller Windows build validation + macOS code signing
- Gzip-compressed JSON exports for long sessions

---

# Questions?

**Repo:** github.com/nevetssf/aTorch-DL24P
**Protocol reference:** improwis.com/projects/sw_dl24
