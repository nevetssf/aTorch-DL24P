"""Tests for database operations."""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from atorch.data.database import Database
from atorch.data.models import TestSession, Reading


def make_reading(**kwargs) -> Reading:
    """Create a Reading with sensible defaults, overriding with kwargs."""
    defaults = {
        "timestamp": datetime.now(),
        "voltage_v": 12.5,
        "current_a": 0.5,
        "power_w": 6.25,
        "energy_wh": 1.0,
        "capacity_mah": 100,
        "mosfet_temp_c": 30,
        "ext_temp_c": 25,
        "runtime_s": 60,
    }
    defaults.update(kwargs)
    return Reading(**defaults)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = Database(db_path)
    yield db

    db.close()
    db_path.unlink()


class TestDatabase:
    """Tests for Database class."""

    def test_create_session(self, temp_db):
        """Test creating a session."""
        session = TestSession(
            name="Test Session",
            start_time=datetime.now(),
            battery_name="Test Battery",
            test_type="discharge",
        )

        session_id = temp_db.create_session(session)

        assert session_id > 0
        assert session.id == session_id

    def test_get_session(self, temp_db):
        """Test retrieving a session."""
        session = TestSession(
            name="Test Session",
            start_time=datetime.now(),
            battery_name="Test Battery",
            notes="Test notes",
            test_type="discharge",
        )
        temp_db.create_session(session)

        retrieved = temp_db.get_session(session.id)

        assert retrieved is not None
        assert retrieved.name == session.name
        assert retrieved.battery_name == session.battery_name
        assert retrieved.notes == session.notes

    def test_update_session(self, temp_db):
        """Test updating a session."""
        session = TestSession(
            name="Original Name",
            start_time=datetime.now(),
        )
        temp_db.create_session(session)

        session.name = "Updated Name"
        session.end_time = datetime.now()
        temp_db.update_session(session)

        retrieved = temp_db.get_session(session.id)
        assert retrieved.name == "Updated Name"
        assert retrieved.end_time is not None

    def test_add_reading(self, temp_db):
        """Test adding readings to a session."""
        session = TestSession(
            name="Test Session",
            start_time=datetime.now(),
        )
        temp_db.create_session(session)

        reading = make_reading()

        reading_id = temp_db.add_reading(session.id, reading)

        assert reading_id > 0
        assert reading.id == reading_id

    def test_get_readings(self, temp_db):
        """Test retrieving readings."""
        session = TestSession(
            name="Test Session",
            start_time=datetime.now(),
        )
        temp_db.create_session(session)

        # Add multiple readings
        for i in range(5):
            reading = make_reading(
                voltage_v=12.5 - i * 0.1,
                energy_wh=i * 0.1,
                capacity_mah=i * 10,
                runtime_s=i * 60,
            )
            temp_db.add_reading(session.id, reading)

        readings = temp_db.get_readings(session.id)

        assert len(readings) == 5
        assert readings[0].voltage_v == 12.5
        assert readings[4].voltage_v == pytest.approx(12.1)

    def test_add_readings_batch(self, temp_db):
        """Test batch adding readings."""
        session = TestSession(
            name="Test Session",
            start_time=datetime.now(),
        )
        temp_db.create_session(session)

        readings = []
        for i in range(100):
            readings.append(make_reading(
                energy_wh=i * 0.01,
                capacity_mah=i,
                runtime_s=i,
            ))

        temp_db.add_readings_batch(session.id, readings)

        retrieved = temp_db.get_readings(session.id)
        assert len(retrieved) == 100

    def test_list_sessions(self, temp_db):
        """Test listing sessions."""
        # Create multiple sessions
        for i in range(5):
            session = TestSession(
                name=f"Session {i}",
                start_time=datetime.now(),
                battery_name="Battery A" if i % 2 == 0 else "Battery B",
            )
            temp_db.create_session(session)

        # List all
        sessions = temp_db.list_sessions()
        assert len(sessions) == 5

        # Filter by battery
        sessions_a = temp_db.list_sessions(battery_name="Battery A")
        assert len(sessions_a) == 3

    def test_delete_session(self, temp_db):
        """Test deleting a session."""
        session = TestSession(
            name="To Delete",
            start_time=datetime.now(),
        )
        temp_db.create_session(session)

        # Add some readings
        for i in range(3):
            reading = make_reading(
                voltage_v=12.0,
                power_w=6.0,
                energy_wh=0.1,
                capacity_mah=10,
                runtime_s=i,
            )
            temp_db.add_reading(session.id, reading)

        # Delete
        result = temp_db.delete_session(session.id)
        assert result is True

        # Verify deleted
        retrieved = temp_db.get_session(session.id)
        assert retrieved is None

        # Verify readings also deleted
        readings = temp_db.get_readings(session.id)
        assert len(readings) == 0

    def test_get_battery_names(self, temp_db):
        """Test getting unique battery names."""
        batteries = ["Battery A", "Battery B", "Battery A", "Battery C"]

        for i, battery in enumerate(batteries):
            session = TestSession(
                name=f"Session {i}",
                start_time=datetime.now(),
                battery_name=battery,
            )
            temp_db.create_session(session)

        names = temp_db.get_battery_names()

        assert len(names) == 3
        assert "Battery A" in names
        assert "Battery B" in names
        assert "Battery C" in names


class TestModels:
    """Tests for data models."""

    def test_session_duration(self):
        """Test session duration calculation."""
        start = datetime(2024, 1, 1, 10, 0, 0)
        end = datetime(2024, 1, 1, 11, 30, 45)

        session = TestSession(
            name="Test",
            start_time=start,
            end_time=end,
        )

        # 1h 30m 45s = 5445s
        assert session.duration_seconds == 5445

    def test_session_stats(self):
        """Test session statistics."""
        session = TestSession(
            name="Test",
            start_time=datetime.now(),
        )

        # Add readings
        for i in range(10):
            session.readings.append(make_reading(
                voltage_v=12.0 - i * 0.2,
                power_w=6.0,
                energy_wh=i * 0.1,
                capacity_mah=i * 50,
                mosfet_temp_c=30 + i,
                runtime_s=i * 60,
            ))

        assert session.final_capacity_mah == 450
        assert session.final_energy_wh == 0.9
        assert session.min_voltage == pytest.approx(10.2)
        assert session.max_temperature == 39
        assert session.average_voltage == pytest.approx(11.1)

    def test_reading_to_dict(self):
        """Test reading serialization."""
        reading = Reading(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            voltage_v=12.5,
            current_a=0.5,
            power_w=6.25,
            energy_wh=1.0,
            capacity_mah=100,
            mosfet_temp_c=30,
            ext_temp_c=25,
            runtime_s=3600,
        )

        d = reading.to_dict()

        assert d["voltage_v"] == 12.5
        assert d["current_a"] == 0.5
        assert d["runtime_s"] == 3600
        assert "2024-01-01" in d["timestamp"]

    def test_session_to_dict(self):
        """Test session serialization."""
        session = TestSession(
            name="Test Session",
            start_time=datetime(2024, 1, 1, 10, 0, 0),
            battery_name="Test Battery",
            test_type="discharge",
            settings={"current_a": 0.5},
        )

        d = session.to_dict()

        assert d["name"] == "Test Session"
        assert d["battery_name"] == "Test Battery"
        assert d["settings"]["current_a"] == 0.5
