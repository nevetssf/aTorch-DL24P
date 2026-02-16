"""Tests for alert conditions."""

import pytest
from atorch.alerts.conditions import (
    AlertResult,
    VoltageAlert,
    TemperatureAlert,
    TestCompleteAlert,
    OvercurrentAlert,
    OvervoltageAlert,
    CapacityAlert,
)
from atorch.protocol.atorch_protocol import DeviceStatus


def make_status(**kwargs) -> DeviceStatus:
    """Create a DeviceStatus with sensible defaults, overriding with kwargs."""
    defaults = {
        "voltage_v": 12.0,
        "current_a": 0.5,
        "power_w": 6.0,
        "energy_wh": 1.0,
        "capacity_mah": 100,
        "mosfet_temp_c": 30,
        "mosfet_temp_f": 86,
        "ext_temp_c": 25,
        "ext_temp_f": 77,
        "hours": 0,
        "minutes": 10,
        "seconds": 0,
        "load_on": True,
        "ureg": False,
        "overcurrent": False,
        "overvoltage": False,
        "overtemperature": False,
        "fan_speed_rpm": 2000,
    }
    defaults.update(kwargs)
    return DeviceStatus(**defaults)


class TestAlertResult:
    """Tests for AlertResult dataclass."""

    def test_creation(self):
        """Test creating an AlertResult."""
        result = AlertResult(triggered=True, message="Test alert", severity="warning")
        assert result.triggered is True
        assert result.message == "Test alert"
        assert result.severity == "warning"

    def test_default_severity(self):
        """Test default severity is info."""
        result = AlertResult(triggered=True, message="Test")
        assert result.severity == "info"


class TestVoltageAlert:
    """Tests for VoltageAlert."""

    def test_triggers_below_threshold(self):
        """Test alert triggers when voltage drops below threshold."""
        alert = VoltageAlert(threshold=3.0)
        status = make_status(voltage_v=2.9)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True
        assert "2.90V" in result.message
        assert result.severity == "warning"

    def test_does_not_trigger_above_threshold(self):
        """Test alert does not trigger when voltage is above threshold."""
        alert = VoltageAlert(threshold=3.0)
        status = make_status(voltage_v=3.5)

        result = alert.check(status)

        assert result is None

    def test_triggers_at_threshold(self):
        """Test alert triggers when voltage equals threshold."""
        alert = VoltageAlert(threshold=3.0)
        status = make_status(voltage_v=3.0)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True

    def test_only_triggers_once(self):
        """Test alert only triggers once until reset."""
        alert = VoltageAlert(threshold=3.0)
        status = make_status(voltage_v=2.9)

        result1 = alert.check(status)
        result2 = alert.check(status)

        assert result1 is not None
        assert result2 is None  # Should not trigger again

    def test_hysteresis_reset(self):
        """Test alert resets when voltage rises above threshold + hysteresis."""
        alert = VoltageAlert(threshold=3.0, hysteresis=0.1)

        # Trigger the alert
        alert.check(make_status(voltage_v=2.9))

        # Still below threshold + hysteresis, should not reset
        alert.check(make_status(voltage_v=3.05))

        # Above threshold + hysteresis, should reset
        alert.check(make_status(voltage_v=3.15))

        # Should trigger again
        result = alert.check(make_status(voltage_v=2.9))
        assert result is not None

    def test_manual_reset(self):
        """Test manual reset allows re-triggering."""
        alert = VoltageAlert(threshold=3.0)

        alert.check(make_status(voltage_v=2.9))
        alert.reset()

        result = alert.check(make_status(voltage_v=2.9))
        assert result is not None


class TestTemperatureAlert:
    """Tests for TemperatureAlert."""

    def test_triggers_above_threshold(self):
        """Test alert triggers when temperature exceeds threshold."""
        alert = TemperatureAlert(threshold=50)
        status = make_status(mosfet_temp_c=55)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True
        assert "55°C" in result.message
        assert result.severity == "error"

    def test_does_not_trigger_below_threshold(self):
        """Test alert does not trigger below threshold."""
        alert = TemperatureAlert(threshold=50)
        status = make_status(mosfet_temp_c=45)

        result = alert.check(status)

        assert result is None

    def test_triggers_at_threshold(self):
        """Test alert triggers at exactly threshold."""
        alert = TemperatureAlert(threshold=50)
        status = make_status(mosfet_temp_c=50)

        result = alert.check(status)

        assert result is not None

    def test_uses_external_probe(self):
        """Test alert can use external temperature probe."""
        alert = TemperatureAlert(threshold=40, use_external=True)
        status = make_status(mosfet_temp_c=35, ext_temp_c=45)

        result = alert.check(status)

        assert result is not None
        assert "External" in result.message
        assert "45°C" in result.message

    def test_internal_probe_default(self):
        """Test alert uses internal probe by default."""
        alert = TemperatureAlert(threshold=40)
        status = make_status(mosfet_temp_c=45, ext_temp_c=35)

        result = alert.check(status)

        assert result is not None
        assert "Internal" in result.message

    def test_hysteresis_reset(self):
        """Test alert resets when temp drops 5°C below threshold."""
        alert = TemperatureAlert(threshold=50)

        # Trigger
        alert.check(make_status(mosfet_temp_c=55))

        # Still within 5°C, should not reset
        alert.check(make_status(mosfet_temp_c=46))

        # Now below threshold - 5, should reset
        alert.check(make_status(mosfet_temp_c=44))

        # Should trigger again
        result = alert.check(make_status(mosfet_temp_c=52))
        assert result is not None


class TestTestCompleteAlert:
    """Tests for TestCompleteAlert."""

    def test_triggers_when_load_turns_off(self):
        """Test alert triggers when load turns off after being on."""
        alert = TestCompleteAlert()
        alert.set_logging_active(True)

        # Load is on
        alert.check(make_status(load_on=True, capacity_mah=500, energy_wh=2.5))

        # Load turns off
        result = alert.check(make_status(load_on=False, capacity_mah=500, energy_wh=2.5))

        assert result is not None
        assert result.triggered is True
        assert "500mAh" in result.message
        assert "2.50Wh" in result.message
        assert result.severity == "info"

    def test_does_not_trigger_if_never_on(self):
        """Test alert does not trigger if load was never on."""
        alert = TestCompleteAlert()

        result = alert.check(make_status(load_on=False))

        assert result is None

    def test_only_triggers_once(self):
        """Test alert only triggers once per test completion."""
        alert = TestCompleteAlert()
        alert.set_logging_active(True)

        alert.check(make_status(load_on=True))
        result1 = alert.check(make_status(load_on=False))
        result2 = alert.check(make_status(load_on=False))

        assert result1 is not None
        assert result2 is None

    def test_reset_allows_retrigger(self):
        """Test reset allows alert to trigger again."""
        alert = TestCompleteAlert()
        alert.set_logging_active(True)

        alert.check(make_status(load_on=True))
        alert.check(make_status(load_on=False))
        alert.reset()

        alert.check(make_status(load_on=True))
        result = alert.check(make_status(load_on=False))

        assert result is not None

    def test_new_test_resets_automatically(self):
        """Test starting a new test resets the alert."""
        alert = TestCompleteAlert()
        alert.set_logging_active(True)

        # First test
        alert.check(make_status(load_on=True))
        alert.check(make_status(load_on=False))

        # Second test - load turns on again
        alert.check(make_status(load_on=True))
        result = alert.check(make_status(load_on=False))

        assert result is not None


class TestOvercurrentAlert:
    """Tests for OvercurrentAlert."""

    def test_triggers_on_overcurrent(self):
        """Test alert triggers when overcurrent flag is set."""
        alert = OvercurrentAlert()
        status = make_status(overcurrent=True)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True
        assert "Overcurrent" in result.message
        assert result.severity == "error"

    def test_does_not_trigger_without_overcurrent(self):
        """Test alert does not trigger without overcurrent."""
        alert = OvercurrentAlert()
        status = make_status(overcurrent=False)

        result = alert.check(status)

        assert result is None

    def test_only_triggers_once(self):
        """Test alert only triggers once until cleared."""
        alert = OvercurrentAlert()

        result1 = alert.check(make_status(overcurrent=True))
        result2 = alert.check(make_status(overcurrent=True))

        assert result1 is not None
        assert result2 is None

    def test_resets_when_cleared(self):
        """Test alert resets when overcurrent clears."""
        alert = OvercurrentAlert()

        alert.check(make_status(overcurrent=True))
        alert.check(make_status(overcurrent=False))

        result = alert.check(make_status(overcurrent=True))
        assert result is not None


class TestOvervoltageAlert:
    """Tests for OvervoltageAlert."""

    def test_triggers_on_overvoltage(self):
        """Test alert triggers when overvoltage flag is set."""
        alert = OvervoltageAlert()
        status = make_status(overvoltage=True)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True
        assert "Overvoltage" in result.message
        assert result.severity == "error"

    def test_does_not_trigger_without_overvoltage(self):
        """Test alert does not trigger without overvoltage."""
        alert = OvervoltageAlert()
        status = make_status(overvoltage=False)

        result = alert.check(status)

        assert result is None


class TestCapacityAlert:
    """Tests for CapacityAlert."""

    def test_triggers_at_target(self):
        """Test alert triggers when capacity reaches target."""
        alert = CapacityAlert(target_mah=1000)
        status = make_status(capacity_mah=1000)

        result = alert.check(status)

        assert result is not None
        assert result.triggered is True
        assert "1000mAh" in result.message
        assert result.severity == "info"

    def test_triggers_above_target(self):
        """Test alert triggers when capacity exceeds target."""
        alert = CapacityAlert(target_mah=1000)
        status = make_status(capacity_mah=1100)

        result = alert.check(status)

        assert result is not None

    def test_does_not_trigger_below_target(self):
        """Test alert does not trigger below target."""
        alert = CapacityAlert(target_mah=1000)
        status = make_status(capacity_mah=900)

        result = alert.check(status)

        assert result is None

    def test_only_triggers_once(self):
        """Test alert only triggers once."""
        alert = CapacityAlert(target_mah=1000)

        result1 = alert.check(make_status(capacity_mah=1000))
        result2 = alert.check(make_status(capacity_mah=1100))

        assert result1 is not None
        assert result2 is None

    def test_reset_allows_retrigger(self):
        """Test reset allows re-triggering."""
        alert = CapacityAlert(target_mah=1000)

        alert.check(make_status(capacity_mah=1000))
        alert.reset()

        result = alert.check(make_status(capacity_mah=1000))
        assert result is not None
