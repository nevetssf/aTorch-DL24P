"""Test profile definitions for automated testing."""

from dataclasses import dataclass, field
from typing import Optional
import json
from pathlib import Path


@dataclass
class TestProfile:
    """Base class for test profiles."""
    name: str
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.__class__.__name__,
            "name": self.name,
            "description": self.description,
        }

    def save(self, path: Path) -> None:
        """Save profile to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "TestProfile":
        """Load profile from JSON file."""
        with open(path) as f:
            data = json.load(f)

        profile_type = data.get("type", "DischargeProfile")

        if profile_type == "DischargeProfile":
            return DischargeProfile.from_dict(data)
        elif profile_type == "CycleProfile":
            return CycleProfile.from_dict(data)
        elif profile_type == "TimedProfile":
            return TimedProfile.from_dict(data)
        elif profile_type == "SteppedProfile":
            return SteppedProfile.from_dict(data)
        else:
            raise ValueError(f"Unknown profile type: {profile_type}")


@dataclass
class DischargeProfile(TestProfile):
    """Profile for discharge tests until voltage cutoff."""
    current_a: float = 0.5  # Discharge current in amps
    voltage_cutoff: float = 3.0  # Stop when voltage drops below this
    max_duration_s: Optional[int] = None  # Optional maximum duration

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "current_a": self.current_a,
            "voltage_cutoff": self.voltage_cutoff,
            "max_duration_s": self.max_duration_s,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DischargeProfile":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            current_a=data.get("current_a", 0.5),
            voltage_cutoff=data.get("voltage_cutoff", 3.0),
            max_duration_s=data.get("max_duration_s"),
        )


@dataclass
class CycleProfile(TestProfile):
    """Profile for repeated discharge cycles."""
    current_a: float = 0.5
    voltage_cutoff: float = 3.0
    num_cycles: int = 1
    rest_between_cycles_s: int = 60  # Rest time between cycles

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "current_a": self.current_a,
            "voltage_cutoff": self.voltage_cutoff,
            "num_cycles": self.num_cycles,
            "rest_between_cycles_s": self.rest_between_cycles_s,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CycleProfile":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            current_a=data.get("current_a", 0.5),
            voltage_cutoff=data.get("voltage_cutoff", 3.0),
            num_cycles=data.get("num_cycles", 1),
            rest_between_cycles_s=data.get("rest_between_cycles_s", 60),
        )


@dataclass
class TimedProfile(TestProfile):
    """Profile for fixed-duration tests."""
    current_a: float = 0.5
    duration_s: int = 3600  # Test duration in seconds
    voltage_cutoff: Optional[float] = None  # Optional safety cutoff

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "current_a": self.current_a,
            "duration_s": self.duration_s,
            "voltage_cutoff": self.voltage_cutoff,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TimedProfile":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            current_a=data.get("current_a", 0.5),
            duration_s=data.get("duration_s", 3600),
            voltage_cutoff=data.get("voltage_cutoff"),
        )


@dataclass
class SteppedProfile(TestProfile):
    """Profile for stepped current tests (internal resistance estimation)."""
    steps: list[dict] = field(default_factory=list)  # List of {current_a, duration_s}
    voltage_cutoff: Optional[float] = None
    rest_between_steps_s: int = 10

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({
            "steps": self.steps,
            "voltage_cutoff": self.voltage_cutoff,
            "rest_between_steps_s": self.rest_between_steps_s,
        })
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SteppedProfile":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            steps=data.get("steps", []),
            voltage_cutoff=data.get("voltage_cutoff"),
            rest_between_steps_s=data.get("rest_between_steps_s", 10),
        )

    @classmethod
    def create_ir_test(cls, currents: list[float], duration_per_step: int = 30) -> "SteppedProfile":
        """Create a profile for internal resistance estimation.

        Args:
            currents: List of current values to test
            duration_per_step: How long to hold each current level

        Returns:
            SteppedProfile configured for IR testing
        """
        steps = [{"current_a": c, "duration_s": duration_per_step} for c in currents]
        return cls(
            name="IR Test",
            description="Internal resistance estimation",
            steps=steps,
            rest_between_steps_s=5,
        )
