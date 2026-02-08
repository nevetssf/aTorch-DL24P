"""Tests for test profiles."""

import pytest
import tempfile
from pathlib import Path

from atorch.automation.profiles import (
    TestProfile,
    DischargeProfile,
    CycleProfile,
    TimedProfile,
    SteppedProfile,
)


class TestDischargeProfile:
    """Tests for DischargeProfile."""

    def test_creation(self):
        """Test creating a discharge profile."""
        profile = DischargeProfile(
            name="Test Discharge",
            description="Test description",
            current_a=0.5,
            voltage_cutoff=3.0,
        )

        assert profile.name == "Test Discharge"
        assert profile.current_a == 0.5
        assert profile.voltage_cutoff == 3.0

    def test_to_dict(self):
        """Test serialization to dict."""
        profile = DischargeProfile(
            name="Test",
            current_a=1.0,
            voltage_cutoff=2.8,
            max_duration_s=3600,
        )

        d = profile.to_dict()

        assert d["type"] == "DischargeProfile"
        assert d["current_a"] == 1.0
        assert d["voltage_cutoff"] == 2.8
        assert d["max_duration_s"] == 3600

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "name": "Loaded Profile",
            "description": "Test",
            "current_a": 0.75,
            "voltage_cutoff": 3.2,
        }

        profile = DischargeProfile.from_dict(data)

        assert profile.name == "Loaded Profile"
        assert profile.current_a == 0.75
        assert profile.voltage_cutoff == 3.2

    def test_save_and_load(self):
        """Test saving and loading profile."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            profile = DischargeProfile(
                name="Save Test",
                current_a=0.5,
                voltage_cutoff=3.0,
            )
            profile.save(path)

            loaded = TestProfile.load(path)

            assert isinstance(loaded, DischargeProfile)
            assert loaded.name == "Save Test"
            assert loaded.current_a == 0.5
        finally:
            path.unlink()


class TestCycleProfile:
    """Tests for CycleProfile."""

    def test_creation(self):
        """Test creating a cycle profile."""
        profile = CycleProfile(
            name="Cycle Test",
            current_a=0.5,
            voltage_cutoff=3.0,
            num_cycles=3,
            rest_between_cycles_s=60,
        )

        assert profile.num_cycles == 3
        assert profile.rest_between_cycles_s == 60

    def test_serialization(self):
        """Test round-trip serialization."""
        profile = CycleProfile(
            name="Cycle",
            current_a=1.0,
            voltage_cutoff=2.8,
            num_cycles=5,
        )

        d = profile.to_dict()
        loaded = CycleProfile.from_dict(d)

        assert loaded.num_cycles == 5
        assert loaded.current_a == 1.0


class TestTimedProfile:
    """Tests for TimedProfile."""

    def test_creation(self):
        """Test creating a timed profile."""
        profile = TimedProfile(
            name="Timed Test",
            current_a=0.5,
            duration_s=7200,
        )

        assert profile.duration_s == 7200
        assert profile.voltage_cutoff is None

    def test_with_cutoff(self):
        """Test timed profile with voltage cutoff."""
        profile = TimedProfile(
            name="Timed with Cutoff",
            current_a=0.5,
            duration_s=3600,
            voltage_cutoff=3.0,
        )

        assert profile.voltage_cutoff == 3.0


class TestSteppedProfile:
    """Tests for SteppedProfile."""

    def test_creation(self):
        """Test creating a stepped profile."""
        profile = SteppedProfile(
            name="Stepped Test",
            steps=[
                {"current_a": 0.1, "duration_s": 30},
                {"current_a": 0.5, "duration_s": 30},
                {"current_a": 1.0, "duration_s": 30},
            ],
        )

        assert len(profile.steps) == 3
        assert profile.steps[0]["current_a"] == 0.1

    def test_create_ir_test(self):
        """Test IR test creation helper."""
        profile = SteppedProfile.create_ir_test(
            currents=[0.1, 0.2, 0.5, 1.0],
            duration_per_step=30,
        )

        assert profile.name == "IR Test"
        assert len(profile.steps) == 4
        assert profile.steps[0]["current_a"] == 0.1
        assert profile.steps[0]["duration_s"] == 30
        assert profile.steps[3]["current_a"] == 1.0

    def test_serialization(self):
        """Test round-trip serialization."""
        profile = SteppedProfile(
            name="Step Test",
            steps=[
                {"current_a": 0.1, "duration_s": 10},
                {"current_a": 0.2, "duration_s": 20},
            ],
            rest_between_steps_s=5,
        )

        d = profile.to_dict()
        loaded = SteppedProfile.from_dict(d)

        assert len(loaded.steps) == 2
        assert loaded.rest_between_steps_s == 5
