"""Data models for test sessions and readings."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json


@dataclass
class Reading:
    """A single data point from the device."""
    timestamp: datetime
    voltage: float
    current: float
    power: float
    energy_wh: float
    capacity_mah: float
    temperature_c: int
    ext_temperature_c: int
    runtime_seconds: int
    id: Optional[int] = None
    session_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "voltage": self.voltage,
            "current": self.current,
            "power": self.power,
            "energy_wh": self.energy_wh,
            "capacity_mah": self.capacity_mah,
            "temperature_c": self.temperature_c,
            "ext_temperature_c": self.ext_temperature_c,
            "runtime_seconds": self.runtime_seconds,
        }


@dataclass
class TestSession:
    """A test session containing multiple readings."""
    name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    battery_name: str = ""
    battery_capacity_mah: Optional[float] = None
    notes: str = ""
    test_type: str = "discharge"  # discharge, cycle, timed, stepped
    settings: dict = field(default_factory=dict)
    readings: list[Reading] = field(default_factory=list)
    id: Optional[int] = None

    @property
    def duration_seconds(self) -> int:
        """Get session duration in seconds."""
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        elif self.readings:
            return self.readings[-1].runtime_seconds
        return 0

    @property
    def final_capacity_mah(self) -> float:
        """Get final capacity in mAh."""
        if self.readings:
            return self.readings[-1].capacity_mah
        return 0.0

    @property
    def final_energy_wh(self) -> float:
        """Get final energy in Wh."""
        if self.readings:
            return self.readings[-1].energy_wh
        return 0.0

    @property
    def average_voltage(self) -> float:
        """Calculate average voltage during test."""
        if not self.readings:
            return 0.0
        return sum(r.voltage for r in self.readings) / len(self.readings)

    @property
    def min_voltage(self) -> float:
        """Get minimum voltage during test."""
        if not self.readings:
            return 0.0
        return min(r.voltage for r in self.readings)

    @property
    def max_temperature(self) -> int:
        """Get maximum temperature during test."""
        if not self.readings:
            return 0
        return max(r.temperature_c for r in self.readings)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "battery_name": self.battery_name,
            "battery_capacity_mah": self.battery_capacity_mah,
            "notes": self.notes,
            "test_type": self.test_type,
            "settings": self.settings,
            "duration_seconds": self.duration_seconds,
            "final_capacity_mah": self.final_capacity_mah,
            "final_energy_wh": self.final_energy_wh,
            "average_voltage": self.average_voltage,
            "readings": [r.to_dict() for r in self.readings],
        }

    def settings_json(self) -> str:
        """Get settings as JSON string."""
        return json.dumps(self.settings)

    @classmethod
    def from_settings_json(cls, json_str: str) -> dict:
        """Parse settings from JSON string."""
        try:
            return json.loads(json_str) if json_str else {}
        except json.JSONDecodeError:
            return {}
