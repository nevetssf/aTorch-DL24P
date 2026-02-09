"""Live readings status panel."""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QFrame,
    QPushButton,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont

from ..protocol.atorch_protocol import DeviceStatus
from .control_panel import ToggleSwitch


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

    # Signals for logging controls
    logging_toggled = Signal(bool)
    clear_requested = Signal()
    save_requested = Signal(str)  # Passes battery name

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

        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line2, row, 0, 1, 3)
        row += 1

        # MOSFET Temperature
        readings_layout.addWidget(QLabel("MOSFET:"), row, 0)
        self.temp_label = StatusLabel()
        readings_layout.addWidget(self.temp_label, row, 1)
        readings_layout.addWidget(UnitLabel("°C"), row, 2)
        row += 1

        # External Temperature
        readings_layout.addWidget(QLabel("External:"), row, 0)
        self.ext_temp_label = StatusLabel()
        readings_layout.addWidget(self.ext_temp_label, row, 1)
        readings_layout.addWidget(UnitLabel("°C"), row, 2)
        row += 1

        # Fan Speed
        readings_layout.addWidget(QLabel("Fan:"), row, 0)
        self.fan_label = StatusLabel()
        readings_layout.addWidget(self.fan_label, row, 1)
        readings_layout.addWidget(UnitLabel("RPM"), row, 2)
        row += 1

        # Separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line3, row, 0, 1, 3)
        row += 1

        # Status (ON/OFF)
        readings_layout.addWidget(QLabel("Status:"), row, 0)
        self.load_status_label = QLabel("OFF")
        self.load_status_label.setAlignment(Qt.AlignRight)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.load_status_label.setFont(font)
        readings_layout.addWidget(self.load_status_label, row, 1)
        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color: red; font-weight: bold;")
        readings_layout.addWidget(self.warning_label, row, 2)
        row += 1

        # UREG indicator (no load present)
        readings_layout.addWidget(QLabel(""), row, 0)  # Empty label for alignment
        self.ureg_label = QLabel("")
        self.ureg_label.setAlignment(Qt.AlignRight)
        self.ureg_label.setStyleSheet("color: orange; font-weight: bold;")
        readings_layout.addWidget(self.ureg_label, row, 1)
        row += 1

        layout.addWidget(readings_group)

        # Data Logging group
        log_group = QGroupBox("Data Logging")
        log_layout = QVBoxLayout(log_group)

        # Logging toggle switch
        logging_layout = QHBoxLayout()
        logging_layout.addWidget(QLabel("Logging:"))
        logging_layout.addStretch()

        self.log_label_off = QLabel("OFF")
        logging_layout.addWidget(self.log_label_off)

        self.log_switch = ToggleSwitch()
        self.log_switch.setEnabled(False)
        self.log_switch.toggled.connect(self._on_logging_toggled)
        logging_layout.addWidget(self.log_switch)

        self.log_label_on = QLabel("ON")
        logging_layout.addWidget(self.log_label_on)
        log_layout.addLayout(logging_layout)

        # Battery name input
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Battery:"))
        self.battery_name_edit = QLineEdit()
        self.battery_name_edit.setPlaceholderText("Optional name")
        name_layout.addWidget(self.battery_name_edit)
        log_layout.addLayout(name_layout)

        # Save and Clear buttons row
        save_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Data...")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_clicked)
        save_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        save_layout.addWidget(self.clear_btn)
        log_layout.addLayout(save_layout)

        # Logging time display
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Logged Time:"))
        time_layout.addStretch()
        self.logging_time_label = StatusLabel("00:00:00")
        time_layout.addWidget(self.logging_time_label)
        log_layout.addLayout(time_layout)

        layout.addWidget(log_group)

        # Spacer
        layout.addStretch()

    def set_connected(self, connected: bool) -> None:
        """Update UI for connection state."""
        self.log_switch.setEnabled(connected)
        self.clear_btn.setEnabled(connected)
        self.save_btn.setEnabled(connected)

        if not connected:
            self.log_switch.setChecked(False)
            self._update_logging_labels(False)

    def _update_logging_labels(self, logging: bool) -> None:
        """Update the ON/OFF labels based on logging state."""
        if logging:
            self.log_label_on.setStyleSheet("color: #00FF00; font-weight: bold;")
            self.log_label_off.setStyleSheet("color: #888888;")
        else:
            self.log_label_on.setStyleSheet("color: #888888;")
            self.log_label_off.setStyleSheet("color: #888888;")

    @Slot(bool)
    def _on_logging_toggled(self, checked: bool) -> None:
        """Handle logging toggle switch."""
        self._update_logging_labels(checked)
        self.logging_toggled.emit(checked)

    @Slot()
    def _on_clear_clicked(self) -> None:
        """Handle clear button click."""
        self.clear_requested.emit()

    @Slot()
    def _on_save_clicked(self) -> None:
        """Handle save button click."""
        battery_name = self.battery_name_edit.text().strip()
        self.save_requested.emit(battery_name)

    def update_status(self, status: DeviceStatus) -> None:
        """Update display with device status."""
        self.voltage_label.setText(f"{status.voltage:.2f}")
        self.current_label.setText(f"{status.current:.3f}")
        self.power_label.setText(f"{status.power:.2f}")

        self.capacity_label.setText(f"{status.capacity_mah:.0f}")
        self.energy_label.setText(f"{status.energy_wh:.3f}")

        self.temp_label.setText(f"{status.temperature_c}")
        self.ext_temp_label.setText(f"{status.ext_temperature_c}")

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

        # UREG indicator (no load present)
        if status.ureg:
            self.ureg_label.setText("UREG")
        else:
            self.ureg_label.setText("")

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
        self.load_status_label.setText("OFF")
        self.load_status_label.setStyleSheet("color: #888888;")
        self.warning_label.setText("")
        self.ureg_label.setText("")
        self.fan_label.setText("---")
