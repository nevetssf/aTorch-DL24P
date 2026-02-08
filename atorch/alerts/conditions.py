"""Alert condition definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..protocol.atorch_protocol import DeviceStatus


@dataclass
class AlertResult:
    """Result of checking an alert condition."""
    triggered: bool
    message: str
    severity: str = "info"  # info, warning, error


class AlertCondition(ABC):
    """Base class for alert conditions."""

    @abstractmethod
    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        """Check if the alert condition is met.

        Args:
            status: Current device status

        Returns:
            AlertResult if triggered, None otherwise
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the alert state."""
        pass


class VoltageAlert(AlertCondition):
    """Alert when voltage drops below threshold."""

    def __init__(self, threshold: float, hysteresis: float = 0.1):
        """Initialize voltage alert.

        Args:
            threshold: Voltage threshold in volts
            hysteresis: Voltage must rise above threshold + hysteresis to reset
        """
        self.threshold = threshold
        self.hysteresis = hysteresis
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        if not self._triggered and status.voltage <= self.threshold:
            self._triggered = True
            return AlertResult(
                triggered=True,
                message=f"Voltage dropped to {status.voltage:.2f}V (below {self.threshold}V)",
                severity="warning",
            )

        # Reset if voltage rises above threshold + hysteresis
        if self._triggered and status.voltage > self.threshold + self.hysteresis:
            self._triggered = False

        return None

    def reset(self) -> None:
        self._triggered = False


class TemperatureAlert(AlertCondition):
    """Alert when temperature exceeds threshold."""

    def __init__(self, threshold: int = 60, use_external: bool = False):
        """Initialize temperature alert.

        Args:
            threshold: Temperature threshold in Celsius
            use_external: Use external probe instead of internal
        """
        self.threshold = threshold
        self.use_external = use_external
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        temp = status.ext_temperature_c if self.use_external else status.temperature_c

        if not self._triggered and temp >= self.threshold:
            self._triggered = True
            source = "External" if self.use_external else "Internal"
            return AlertResult(
                triggered=True,
                message=f"{source} temperature reached {temp}°C (limit: {self.threshold}°C)",
                severity="error",
            )

        # Reset if temperature drops 5°C below threshold
        if self._triggered and temp < self.threshold - 5:
            self._triggered = False

        return None

    def reset(self) -> None:
        self._triggered = False


class TestCompleteAlert(AlertCondition):
    """Alert when test completes (load turns off)."""

    def __init__(self):
        self._was_on = False
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        if status.load_on:
            self._was_on = True
            self._triggered = False
            return None

        if self._was_on and not status.load_on and not self._triggered:
            self._triggered = True
            return AlertResult(
                triggered=True,
                message=f"Test complete: {status.capacity_mah:.0f}mAh / {status.energy_wh:.2f}Wh",
                severity="info",
            )

        return None

    def reset(self) -> None:
        self._was_on = False
        self._triggered = False


class OvercurrentAlert(AlertCondition):
    """Alert when overcurrent protection triggers."""

    def __init__(self):
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        if not self._triggered and status.overcurrent:
            self._triggered = True
            return AlertResult(
                triggered=True,
                message="Overcurrent protection triggered!",
                severity="error",
            )

        if self._triggered and not status.overcurrent:
            self._triggered = False

        return None

    def reset(self) -> None:
        self._triggered = False


class OvervoltageAlert(AlertCondition):
    """Alert when overvoltage protection triggers."""

    def __init__(self):
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        if not self._triggered and status.overvoltage:
            self._triggered = True
            return AlertResult(
                triggered=True,
                message="Overvoltage protection triggered!",
                severity="error",
            )

        if self._triggered and not status.overvoltage:
            self._triggered = False

        return None

    def reset(self) -> None:
        self._triggered = False


class CapacityAlert(AlertCondition):
    """Alert when capacity reaches a target."""

    def __init__(self, target_mah: float):
        """Initialize capacity alert.

        Args:
            target_mah: Target capacity in mAh
        """
        self.target_mah = target_mah
        self._triggered = False

    def check(self, status: DeviceStatus) -> Optional[AlertResult]:
        if not self._triggered and status.capacity_mah >= self.target_mah:
            self._triggered = True
            return AlertResult(
                triggered=True,
                message=f"Capacity reached {status.capacity_mah:.0f}mAh (target: {self.target_mah:.0f}mAh)",
                severity="info",
            )

        return None

    def reset(self) -> None:
        self._triggered = False
