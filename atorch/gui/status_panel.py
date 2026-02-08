"""Live readings status panel."""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ..protocol.atorch_protocol import DeviceStatus


class StatusLabel(QLabel):
    """Large status display label."""

    def __init__(self, text: str = "---"):
        super().__init__(text)
        self.setAlignment(Qt.AlignRight)

        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.setFont(font)


class UnitLabel(QLabel):
    """Unit label for status values."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setAlignment(Qt.AlignLeft | Qt.AlignBottom)


class StatusPanel(QWidget):
    """Panel displaying live device readings."""

    def __init__(self):
        super().__init__()

        self._create_ui()

    def _create_ui(self) -> None:
        """Create the status panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main readings
        readings_group = QGroupBox("Live Readings")
        readings_layout = QGridLayout(readings_group)
        readings_layout.setSpacing(8)

        row = 0

        # Voltage
        readings_layout.addWidget(QLabel("Voltage:"), row, 0)
        self.voltage_label = StatusLabel()
        readings_layout.addWidget(self.voltage_label, row, 1)
        readings_layout.addWidget(UnitLabel("V"), row, 2)
        row += 1

        # Current
        readings_layout.addWidget(QLabel("Current:"), row, 0)
        self.current_label = StatusLabel()
        readings_layout.addWidget(self.current_label, row, 1)
        readings_layout.addWidget(UnitLabel("A"), row, 2)
        row += 1

        # Power
        readings_layout.addWidget(QLabel("Power:"), row, 0)
        self.power_label = StatusLabel()
        readings_layout.addWidget(self.power_label, row, 1)
        readings_layout.addWidget(UnitLabel("W"), row, 2)
        row += 1

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line, row, 0, 1, 3)
        row += 1

        # Capacity
        readings_layout.addWidget(QLabel("Capacity:"), row, 0)
        self.capacity_label = StatusLabel()
        readings_layout.addWidget(self.capacity_label, row, 1)
        readings_layout.addWidget(UnitLabel("mAh"), row, 2)
        row += 1

        # Energy
        readings_layout.addWidget(QLabel("Energy:"), row, 0)
        self.energy_label = StatusLabel()
        readings_layout.addWidget(self.energy_label, row, 1)
        readings_layout.addWidget(UnitLabel("Wh"), row, 2)
        row += 1

        layout.addWidget(readings_group)

        # Temperature group
        temp_group = QGroupBox("Temperature")
        temp_layout = QGridLayout(temp_group)

        temp_layout.addWidget(QLabel("MOSFET:"), 0, 0)
        self.temp_label = StatusLabel()
        temp_layout.addWidget(self.temp_label, 0, 1)
        temp_layout.addWidget(UnitLabel("°C"), 0, 2)

        temp_layout.addWidget(QLabel("External:"), 1, 0)
        self.ext_temp_label = StatusLabel()
        temp_layout.addWidget(self.ext_temp_label, 1, 1)
        temp_layout.addWidget(UnitLabel("°C"), 1, 2)

        layout.addWidget(temp_group)

        # Time group
        time_group = QGroupBox("Time")
        time_layout = QGridLayout(time_group)

        time_layout.addWidget(QLabel("Logging:"), 0, 0)
        self.logging_time_label = StatusLabel("00:00:00")
        time_layout.addWidget(self.logging_time_label, 0, 1)

        time_layout.addWidget(QLabel("Device:"), 1, 0)
        self.device_time_label = StatusLabel("00:00:00")
        time_layout.addWidget(self.device_time_label, 1, 1)

        layout.addWidget(time_group)

        # Status group
        status_group = QGroupBox("Status")
        status_layout = QGridLayout(status_group)

        self.load_status_label = QLabel("OFF")
        self.load_status_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.load_status_label.setFont(font)
        status_layout.addWidget(self.load_status_label, 0, 0)

        self.warning_label = QLabel("")
        self.warning_label.setAlignment(Qt.AlignCenter)
        self.warning_label.setStyleSheet("color: red;")
        status_layout.addWidget(self.warning_label, 1, 0)

        layout.addWidget(status_group)

        # Fan RPM (optional display)
        fan_group = QGroupBox("Fan")
        fan_layout = QGridLayout(fan_group)

        fan_layout.addWidget(QLabel("Speed:"), 0, 0)
        self.fan_label = StatusLabel()
        fan_layout.addWidget(self.fan_label, 0, 1)
        fan_layout.addWidget(UnitLabel("RPM"), 0, 2)

        layout.addWidget(fan_group)

        # Spacer
        layout.addStretch()

    def update_status(self, status: DeviceStatus) -> None:
        """Update display with device status."""
        self.voltage_label.setText(f"{status.voltage:.2f}")
        self.current_label.setText(f"{status.current:.3f}")
        self.power_label.setText(f"{status.power:.2f}")

        self.capacity_label.setText(f"{status.capacity_mah:.0f}")
        self.energy_label.setText(f"{status.energy_wh:.3f}")

        self.temp_label.setText(f"{status.temperature_c}")
        self.ext_temp_label.setText(f"{status.ext_temperature_c}")

        # Format device time as MM:SS (total minutes:seconds since load was on)
        total_seconds = status.hours * 3600 + status.minutes * 60 + status.seconds
        total_minutes = total_seconds // 60
        remaining_seconds = total_seconds % 60
        self.device_time_label.setText(f"{total_minutes}:{remaining_seconds:02d}")

        # Load status
        if status.load_on:
            self.load_status_label.setText("ON")
            self.load_status_label.setStyleSheet("color: #00FF00;")
        else:
            self.load_status_label.setText("OFF")
            self.load_status_label.setStyleSheet("color: #888888;")

        # Warnings
        warnings = []
        if status.overcurrent:
            warnings.append("OC")
        if status.overvoltage:
            warnings.append("OV")
        if status.overtemperature:
            warnings.append("OT")

        if warnings:
            self.warning_label.setText(" ".join(warnings))
        else:
            self.warning_label.setText("")

        # Fan
        self.fan_label.setText(f"{status.fan_rpm}")

    def set_logging_time(self, seconds: float) -> None:
        """Set the logging time display.

        Args:
            seconds: Elapsed seconds since logging started
        """
        total_seconds = int(seconds)
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        self.logging_time_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def clear_logging_time(self) -> None:
        """Reset the logging time display."""
        self.logging_time_label.setText("00:00:00")

    def clear(self) -> None:
        """Clear all status displays."""
        self.voltage_label.setText("---")
        self.current_label.setText("---")
        self.power_label.setText("---")
        self.capacity_label.setText("---")
        self.energy_label.setText("---")
        self.temp_label.setText("---")
        self.ext_temp_label.setText("---")
        self.logging_time_label.setText("00:00:00")
        self.device_time_label.setText("00:00:00")
        self.load_status_label.setText("OFF")
        self.load_status_label.setStyleSheet("color: #888888;")
        self.warning_label.setText("")
        self.fan_label.setText("---")
