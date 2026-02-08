"""Export functions for test data."""

from pathlib import Path
from typing import Union
import csv
import json

from .models import TestSession


def export_csv(session: TestSession, path: Union[str, Path]) -> None:
    """Export a test session to CSV format.

    Args:
        session: TestSession to export
        path: Output file path
    """
    path = Path(path)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)

        # Write header with metadata as comments
        f.write(f"# Test: {session.name}\n")
        f.write(f"# Battery: {session.battery_name}\n")
        f.write(f"# Start: {session.start_time.isoformat()}\n")
        if session.end_time:
            f.write(f"# End: {session.end_time.isoformat()}\n")
        f.write(f"# Type: {session.test_type}\n")
        if session.notes:
            f.write(f"# Notes: {session.notes}\n")
        f.write("#\n")

        # Write column headers
        writer.writerow([
            "timestamp",
            "runtime_s",
            "voltage_V",
            "current_A",
            "power_W",
            "energy_Wh",
            "capacity_mAh",
            "temp_C",
            "ext_temp_C",
        ])

        # Write readings
        for reading in session.readings:
            # Calculate runtime as time delta from session start
            if session.start_time and reading.timestamp:
                runtime_delta = (reading.timestamp - session.start_time).total_seconds()
            else:
                runtime_delta = reading.runtime_seconds

            writer.writerow([
                reading.timestamp.isoformat(),
                f"{runtime_delta:.1f}",
                f"{reading.voltage:.3f}",
                f"{reading.current:.4f}",
                f"{reading.power:.2f}",
                f"{reading.energy_wh:.4f}",
                f"{reading.capacity_mah:.1f}",
                reading.temperature_c,
                reading.ext_temperature_c,
            ])


def export_json(session: TestSession, path: Union[str, Path]) -> None:
    """Export a test session to JSON format.

    Args:
        session: TestSession to export
        path: Output file path
    """
    path = Path(path)

    # Build data dict with runtime as time delta from start
    data = {
        "name": session.name,
        "battery_name": session.battery_name,
        "start_time": session.start_time.isoformat() if session.start_time else None,
        "end_time": session.end_time.isoformat() if session.end_time else None,
        "test_type": session.test_type,
        "notes": session.notes,
        "readings": [],
    }

    for reading in session.readings:
        # Calculate runtime as time delta from session start
        if session.start_time and reading.timestamp:
            runtime_delta = (reading.timestamp - session.start_time).total_seconds()
        else:
            runtime_delta = reading.runtime_seconds

        data["readings"].append({
            "timestamp": reading.timestamp.isoformat() if reading.timestamp else None,
            "runtime_seconds": runtime_delta,
            "voltage": reading.voltage,
            "current": reading.current,
            "power": reading.power,
            "energy_wh": reading.energy_wh,
            "capacity_mah": reading.capacity_mah,
            "temperature_c": reading.temperature_c,
            "ext_temperature_c": reading.ext_temperature_c,
        })

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def export_excel(session: TestSession, path: Union[str, Path]) -> None:
    """Export a test session to Excel format.

    Requires pandas and openpyxl.

    Args:
        session: TestSession to export
        path: Output file path
    """
    import pandas as pd

    path = Path(path)

    # Create DataFrame from readings
    data = []
    for reading in session.readings:
        # Calculate runtime as time delta from session start
        if session.start_time and reading.timestamp:
            runtime_delta = (reading.timestamp - session.start_time).total_seconds()
        else:
            runtime_delta = reading.runtime_seconds

        data.append({
            "Timestamp": reading.timestamp,
            "Runtime (s)": runtime_delta,
            "Voltage (V)": reading.voltage,
            "Current (A)": reading.current,
            "Power (W)": reading.power,
            "Energy (Wh)": reading.energy_wh,
            "Capacity (mAh)": reading.capacity_mah,
            "Temperature (°C)": reading.temperature_c,
            "Ext Temperature (°C)": reading.ext_temperature_c,
        })

    df = pd.DataFrame(data)

    # Create Excel writer with multiple sheets
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Write readings data
        df.to_excel(writer, sheet_name="Readings", index=False)

        # Write summary sheet
        summary = pd.DataFrame([{
            "Test Name": session.name,
            "Battery": session.battery_name,
            "Test Type": session.test_type,
            "Start Time": session.start_time,
            "End Time": session.end_time,
            "Duration (s)": session.duration_seconds,
            "Final Capacity (mAh)": session.final_capacity_mah,
            "Final Energy (Wh)": session.final_energy_wh,
            "Average Voltage (V)": session.average_voltage,
            "Min Voltage (V)": session.min_voltage,
            "Max Temperature (°C)": session.max_temperature,
            "Notes": session.notes,
        }])
        summary.to_excel(writer, sheet_name="Summary", index=False)
