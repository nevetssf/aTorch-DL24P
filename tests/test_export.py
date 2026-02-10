"""Tests for export functions."""

import csv
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from atorch.data.export import export_csv, export_json
from atorch.data.models import TestSession, Reading


def make_session_with_readings() -> TestSession:
    """Create a test session with sample readings."""
    start_time = datetime(2024, 1, 15, 10, 0, 0)
    session = TestSession(
        name="Test Battery Discharge",
        battery_name="Panasonic NCR18650B",
        start_time=start_time,
        end_time=start_time + timedelta(hours=2, minutes=30),
        test_type="discharge",
        notes="Test notes here",
    )
    session.id = 1

    # Add some readings
    for i in range(5):
        reading = Reading(
            timestamp=start_time + timedelta(seconds=i * 60),
            voltage=4.2 - (i * 0.1),
            current=0.5,
            power=2.1 - (i * 0.05),
            energy_wh=0.035 * i,
            capacity_mah=8.33 * i,
            temperature_c=30 + i,
            ext_temperature_c=25,
            runtime_seconds=i * 60,
        )
        session.readings.append(reading)

    return session


class TestExportCSV:
    """Tests for CSV export function."""

    def test_export_creates_file(self, tmp_path):
        """Test that export creates a CSV file."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.csv"

        export_csv(session, output_path)

        assert output_path.exists()

    def test_export_with_string_path(self, tmp_path):
        """Test export works with string path."""
        session = make_session_with_readings()
        output_path = str(tmp_path / "test_export.csv")

        export_csv(session, output_path)

        assert Path(output_path).exists()

    def test_export_contains_header_comments(self, tmp_path):
        """Test that export includes metadata as comments."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.csv"

        export_csv(session, output_path)

        content = output_path.read_text()
        assert "# Test: Test Battery Discharge" in content
        assert "# Battery: Panasonic NCR18650B" in content
        assert "# Type: discharge" in content
        assert "# Notes: Test notes here" in content

    def test_export_contains_column_headers(self, tmp_path):
        """Test that export includes column headers."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.csv"

        export_csv(session, output_path)

        content = output_path.read_text()
        assert "timestamp" in content
        assert "runtime_s" in content
        assert "voltage_V" in content
        assert "current_A" in content
        assert "power_W" in content
        assert "energy_Wh" in content
        assert "capacity_mAh" in content
        assert "temp_C" in content
        assert "ext_temp_C" in content

    def test_export_contains_readings(self, tmp_path):
        """Test that export includes all readings."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.csv"

        export_csv(session, output_path)

        # Read back and count data rows (excluding comments and header)
        with open(output_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("#")]

        # Should have header + 5 data rows
        assert len(lines) == 6

    def test_export_reading_values(self, tmp_path):
        """Test that exported values are correct."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.csv"

        export_csv(session, output_path)

        # Parse CSV and check values
        with open(output_path) as f:
            # Skip comments
            lines = [l for l in f.readlines() if not l.startswith("#")]

        reader = csv.DictReader(lines)
        rows = list(reader)

        # Check first reading
        assert rows[0]["voltage_V"] == "4.200"
        assert rows[0]["current_A"] == "0.5000"
        assert rows[0]["runtime_s"] == "0.0"

        # Check last reading
        assert rows[4]["voltage_V"] == "3.800"
        assert rows[4]["runtime_s"] == "240.0"

    def test_export_runtime_calculated_from_timestamps(self, tmp_path):
        """Test that runtime is calculated from timestamps, not stored value."""
        session = make_session_with_readings()
        # Modify a reading's stored runtime to be different from timestamp delta
        session.readings[2].runtime_seconds = 999

        output_path = tmp_path / "test_export.csv"
        export_csv(session, output_path)

        with open(output_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("#")]

        reader = csv.DictReader(lines)
        rows = list(reader)

        # Runtime should be calculated from timestamp (120s), not stored value (999)
        assert rows[2]["runtime_s"] == "120.0"

    def test_export_empty_session(self, tmp_path):
        """Test exporting a session with no readings."""
        session = TestSession(
            name="Empty Test",
            start_time=datetime.now(),
            test_type="manual",
        )
        output_path = tmp_path / "empty.csv"

        export_csv(session, output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "# Test: Empty Test" in content

    def test_export_without_end_time(self, tmp_path):
        """Test exporting session without end_time."""
        session = make_session_with_readings()
        session.end_time = None
        output_path = tmp_path / "no_end.csv"

        export_csv(session, output_path)

        content = output_path.read_text()
        assert "# End:" not in content


class TestExportJSON:
    """Tests for JSON export function."""

    def test_export_creates_file(self, tmp_path):
        """Test that export creates a JSON file."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        assert output_path.exists()

    def test_export_valid_json(self, tmp_path):
        """Test that exported file is valid JSON."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert isinstance(data, dict)

    def test_export_contains_metadata(self, tmp_path):
        """Test that export includes session metadata."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert data["name"] == "Test Battery Discharge"
        assert data["battery_name"] == "Panasonic NCR18650B"
        assert data["test_type"] == "discharge"
        assert data["notes"] == "Test notes here"

    def test_export_contains_timestamps(self, tmp_path):
        """Test that export includes ISO format timestamps."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert "2024-01-15T10:00:00" in data["start_time"]
        assert "2024-01-15T12:30:00" in data["end_time"]

    def test_export_contains_readings(self, tmp_path):
        """Test that export includes all readings."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert len(data["readings"]) == 5

    def test_export_reading_structure(self, tmp_path):
        """Test that readings have correct structure."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        reading = data["readings"][0]
        assert "timestamp" in reading
        assert "runtime_seconds" in reading
        assert "voltage" in reading
        assert "current" in reading
        assert "power" in reading
        assert "energy_wh" in reading
        assert "capacity_mah" in reading
        assert "temperature_c" in reading
        assert "ext_temperature_c" in reading

    def test_export_reading_values(self, tmp_path):
        """Test that reading values are correct."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        first_reading = data["readings"][0]
        assert first_reading["voltage"] == 4.2
        assert first_reading["current"] == 0.5
        assert first_reading["runtime_seconds"] == 0.0

        last_reading = data["readings"][4]
        assert last_reading["voltage"] == pytest.approx(3.8)
        assert last_reading["runtime_seconds"] == 240.0

    def test_export_runtime_calculated_from_timestamps(self, tmp_path):
        """Test that runtime is calculated from timestamps."""
        session = make_session_with_readings()
        session.readings[2].runtime_seconds = 999

        output_path = tmp_path / "test_export.json"
        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        # Should be 120s from timestamp, not 999
        assert data["readings"][2]["runtime_seconds"] == 120.0

    def test_export_empty_session(self, tmp_path):
        """Test exporting session with no readings."""
        session = TestSession(
            name="Empty Test",
            start_time=datetime.now(),
            test_type="manual",
        )
        output_path = tmp_path / "empty.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert data["name"] == "Empty Test"
        assert data["readings"] == []

    def test_export_without_end_time(self, tmp_path):
        """Test exporting session without end_time."""
        session = make_session_with_readings()
        session.end_time = None
        output_path = tmp_path / "no_end.json"

        export_json(session, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert data["end_time"] is None

    def test_export_is_indented(self, tmp_path):
        """Test that JSON output is human-readable (indented)."""
        session = make_session_with_readings()
        output_path = tmp_path / "test_export.json"

        export_json(session, output_path)

        content = output_path.read_text()
        # Indented JSON has newlines
        assert "\n" in content
        # And spaces for indentation
        assert "  " in content
