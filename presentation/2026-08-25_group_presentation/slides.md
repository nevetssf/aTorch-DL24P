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

A cross-platform GUI for USB-HID device control & battery discharge testing

### My first vibe-coded project

---

## Agenda

- Background and Motivation
- The hardware
- Reverse-engineering the USB HID protocol
- Application architecture
- Threading model & the lessons it taught us
- Live demo

---

# Background and Motivation

I have a lot of camera batteries of unknown usefulness

## I needed a way to test LiIon camera battery capacity

- Batteries lose capacity with time & use
- Need to know which were good and which could be tossed

## Also needed a way to check battery *chargers*

- LiIon charging is a controlled process, needed to be sure it was being done correctly

---

## Battery Capacity Measurement

- Fully charge battery with known-good charger (eg. 1800mAh @ 2x3.7V = 13.3Ah)
- Discharge at capacity/5 (eg. 360mA)

## Battery Charger Test

- Trickle below 2x3V
- Constant Current (CC) @ 1A until 8.4V
- Constant Voltage (CV) until current drops to 100mA

## Commercial load testers exist, but with decent software they're >$1000

---

# The Hardware

## aTorch DL24P

<img src="./images/1.jpeg" height="300">

Inexpensive (~$40 on Ali Express) load 180W load sink with 4 modes:

- **Constant Current**, **Constant Voltage**
- Constant Resistance Constant Power 
## Great hardware, terrible software

- Windows only
- Crash-prone
- Limited functionality & ability to save data

---

# Claude

- Poor experiences with earlier (Opus <4.5) models during 2025 - couldn't keep thread on large codebases
- Decided to give Claude 4.5 (November 2025) a try for this project
  - Limited scope of project
  - New codebase
  - Low stakes, just personal hobby project

---

# The Plan

## Create Cross-Platform Load Tester "Workbench"
- API to control DL24 through USB-C
- Basic GUI interface to control device (mainly for testing)
- Fully-integrated automation panels for battery & battery charger testing
- Stand-alone viewer to review old data

---

# Reverse-enginering the USB Protocol

## The problem

- Software is Windows-only and very limited 
- Only 3rd party documentation for API, incomplete and inaccurate (improwis.com/projects/sw_dl24)

## Claude's Solution
- Install Wireguard on PC, issue comadns on PC software, monitor USB traffic
- Claude analyzes USB traffic and re-creates protocol

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

# The software design

## Two Applications, One Suite

**Test Bench** — `python -m load_test_bench.main`
Real-time device control + data acquisition (PySide6/Qt)

**Test Viewer** — `python -m load_test_bench.viewer`
Offline analysis of saved test data — no device needed

Both built for battery testing, characterization, and QC
with publication-quality plots and full data export (CSV/JSON/Excel)

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

## Panel State Persistence

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

## Database Logging

- All sessions are logged to a SQLite dB
- No need for user to save measurementsessions
- Separate Viewer application can review entire set of sessions

---

# 6. Live Demo

- Connect to the DL24P over USB HID
- Switch modes (CC / CP / CV / CR) and set a value
- Start a Battery Capacity test, watch live plot + status panel
- Open the Test Viewer against a previous session

*(switch to the running app)*

---

# Questions?

**Repo:** github.com/nevetssf/aTorch-DL24P
