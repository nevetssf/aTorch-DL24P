"""SQLite database operations for test data storage."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from .models import TestSession, Reading


class Database:
    """SQLite database for storing test sessions and readings."""

    def __init__(self, path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            path: Path to database file. If None, uses default location.
        """
        if path is None:
            # Default to user data directory
            data_dir = Path.home() / ".atorch"
            data_dir.mkdir(exist_ok=True)
            path = data_dir / "tests.db"

        self.path = path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        cursor = self._conn.cursor()

        # Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                battery_name TEXT,
                battery_capacity_mah REAL,
                notes TEXT,
                test_type TEXT,
                settings TEXT
            )
        """)

        # Create readings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                voltage REAL NOT NULL,
                current REAL NOT NULL,
                power REAL NOT NULL,
                energy_wh REAL NOT NULL,
                capacity_mah REAL NOT NULL,
                temperature_c INTEGER NOT NULL,
                ext_temperature_c INTEGER,
                fan_speed_rpm INTEGER DEFAULT 0,
                load_r_ohm REAL,
                battery_r_ohm REAL,
                runtime_seconds INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        """)

        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_session
            ON readings (session_id)
        """)

        self._conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def create_session(self, session: TestSession) -> int:
        """Create a new test session.

        Args:
            session: TestSession to create

        Returns:
            ID of created session
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions
            (name, start_time, end_time, battery_name, battery_capacity_mah,
             notes, test_type, settings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.name,
                session.start_time.isoformat(),
                session.end_time.isoformat() if session.end_time else None,
                session.battery_name,
                session.battery_capacity_mah,
                session.notes,
                session.test_type,
                session.settings_json(),
            ),
        )
        self._conn.commit()
        session.id = cursor.lastrowid
        return session.id

    def update_session(self, session: TestSession) -> None:
        """Update an existing session.

        Args:
            session: TestSession with updated fields
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE sessions SET
                name = ?,
                end_time = ?,
                battery_name = ?,
                battery_capacity_mah = ?,
                notes = ?,
                test_type = ?,
                settings = ?
            WHERE id = ?
            """,
            (
                session.name,
                session.end_time.isoformat() if session.end_time else None,
                session.battery_name,
                session.battery_capacity_mah,
                session.notes,
                session.test_type,
                session.settings_json(),
                session.id,
            ),
        )
        self._conn.commit()

    def add_reading(self, session_id: int, reading: Reading, commit: bool = False) -> int:
        """Add a reading to a session.

        Args:
            session_id: ID of the session
            reading: Reading to add
            commit: Whether to commit immediately (default False for performance)

        Returns:
            ID of created reading
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO readings
            (session_id, timestamp, voltage, current, power, energy_wh,
             capacity_mah, temperature_c, ext_temperature_c, fan_speed_rpm,
             load_r_ohm, battery_r_ohm, runtime_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                reading.timestamp.isoformat(),
                reading.voltage_v,       # Map new attribute to old column name
                reading.current_a,       # Map new attribute to old column name
                reading.power_w,         # Map new attribute to old column name
                reading.energy_wh,
                reading.capacity_mah,
                reading.mosfet_temp_c,   # Map new attribute to old column name
                reading.ext_temp_c,      # Map new attribute to old column name
                reading.fan_speed_rpm,
                reading.load_r_ohm,
                reading.battery_r_ohm,
                reading.runtime_s,       # Map new attribute to old column name
            ),
        )
        if commit:
            self._conn.commit()
        reading.id = cursor.lastrowid
        reading.session_id = session_id
        return reading.id

    def commit(self) -> None:
        """Commit pending database changes."""
        if self._conn:
            self._conn.commit()

    def add_readings_batch(self, session_id: int, readings: list[Reading]) -> None:
        """Add multiple readings in a batch.

        Args:
            session_id: ID of the session
            readings: List of readings to add
        """
        cursor = self._conn.cursor()
        cursor.executemany(
            """
            INSERT INTO readings
            (session_id, timestamp, voltage, current, power, energy_wh,
             capacity_mah, temperature_c, ext_temperature_c, fan_speed_rpm,
             load_r_ohm, battery_r_ohm, runtime_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    r.timestamp.isoformat(),
                    r.voltage_v,       # Map new attribute to old column name
                    r.current_a,       # Map new attribute to old column name
                    r.power_w,         # Map new attribute to old column name
                    r.energy_wh,
                    r.capacity_mah,
                    r.mosfet_temp_c,   # Map new attribute to old column name
                    r.ext_temp_c,      # Map new attribute to old column name
                    r.fan_speed_rpm,
                    r.load_r_ohm,
                    r.battery_r_ohm,
                    r.runtime_s,       # Map new attribute to old column name
                )
                for r in readings
            ],
        )
        self._conn.commit()

    def get_session(self, session_id: int, include_readings: bool = True) -> Optional[TestSession]:
        """Get a session by ID.

        Args:
            session_id: ID of the session
            include_readings: Whether to load readings

        Returns:
            TestSession if found, None otherwise
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()

        if not row:
            return None

        session = self._row_to_session(row)

        if include_readings:
            session.readings = self.get_readings(session_id)

        return session

    def get_readings(self, session_id: int) -> list[Reading]:
        """Get all readings for a session.

        Args:
            session_id: ID of the session

        Returns:
            List of readings ordered by timestamp
        """
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM readings WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )

        readings = []
        for row in cursor.fetchall():
            readings.append(
                Reading(
                    id=row["id"],
                    session_id=row["session_id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    voltage_v=row["voltage"],        # Map old column to new attribute
                    current_a=row["current"],        # Map old column to new attribute
                    power_w=row["power"],            # Map old column to new attribute
                    energy_wh=row["energy_wh"],
                    capacity_mah=row["capacity_mah"],
                    mosfet_temp_c=row["temperature_c"],  # Map old column to new attribute
                    ext_temp_c=row["ext_temperature_c"] or 0,  # Map old column to new attribute
                    fan_speed_rpm=row["fan_speed_rpm"] if "fan_speed_rpm" in row.keys() else 0,
                    load_r_ohm=row["load_r_ohm"] if "load_r_ohm" in row.keys() else None,
                    battery_r_ohm=row["battery_r_ohm"] if "battery_r_ohm" in row.keys() else None,
                    runtime_s=row["runtime_seconds"], # Map old column to new attribute
                )
            )

        return readings

    def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
        battery_name: Optional[str] = None,
    ) -> list[TestSession]:
        """List test sessions.

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            battery_name: Filter by battery name

        Returns:
            List of sessions (without readings)
        """
        cursor = self._conn.cursor()

        if battery_name:
            cursor.execute(
                """
                SELECT * FROM sessions
                WHERE battery_name = ?
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
                """,
                (battery_name, limit, offset),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM sessions
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        return [self._row_to_session(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: int) -> bool:
        """Delete a session and its readings.

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted, False if not found
        """
        cursor = self._conn.cursor()

        # Delete readings first
        cursor.execute("DELETE FROM readings WHERE session_id = ?", (session_id,))

        # Delete session
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        self._conn.commit()
        return cursor.rowcount > 0

    def get_battery_names(self) -> list[str]:
        """Get list of unique battery names.

        Returns:
            List of battery names
        """
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT battery_name FROM sessions
            WHERE battery_name != ''
            ORDER BY battery_name
            """
        )
        return [row[0] for row in cursor.fetchall()]

    def _row_to_session(self, row: sqlite3.Row) -> TestSession:
        """Convert a database row to a TestSession."""
        return TestSession(
            id=row["id"],
            name=row["name"],
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
            battery_name=row["battery_name"] or "",
            battery_capacity_mah=row["battery_capacity_mah"],
            notes=row["notes"] or "",
            test_type=row["test_type"] or "discharge",
            settings=TestSession.from_settings_json(row["settings"]),
        )
