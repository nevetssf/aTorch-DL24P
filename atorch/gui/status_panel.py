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
    QCheckBox,
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
    show_points_toggled = Signal(bool)
    clear_requested = Signal()
    save_requested = Signal(str)  # Passes battery name

    def __init__(self):
        super().__init__()

        self._create_ui()

        # Initialize disconnected state (grey out controls)
        self.set_connected(False)

    def _create_ui(self) -> None:
        """Create the status panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main readings
        self.readings_group = QGroupBox("Live Readings")
        readings_layout = QGridLayout(self.readings_group)
        readings_layout.setSpacing(8)

        row = 0

        # Voltage
        self.voltage_row_label = QLabel("Voltage:")
        readings_layout.addWidget(self.voltage_row_label, row, 0)
        self.voltage_label = StatusLabel()
        self.voltage_label.setStyleSheet("color: #FFC107;")  # Amber
        readings_layout.addWidget(self.voltage_label, row, 1)
        self.voltage_unit_label = UnitLabel("V")
        readings_layout.addWidget(self.voltage_unit_label, row, 2)
        row += 1

        # Current
        self.current_row_label = QLabel("Current:")
        readings_layout.addWidget(self.current_row_label, row, 0)
        self.current_label = StatusLabel()
        self.current_label.setStyleSheet("color: #29B6F6;")  # Light blue
        readings_layout.addWidget(self.current_label, row, 1)
        self.current_unit_label = UnitLabel("A")
        readings_layout.addWidget(self.current_unit_label, row, 2)
        row += 1

        # Power
        self.power_row_label = QLabel("Power:")
        readings_layout.addWidget(self.power_row_label, row, 0)
        self.power_label = StatusLabel()
        self.power_label.setStyleSheet("color: #EF5350;")  # Red
        readings_layout.addWidget(self.power_label, row, 1)
        self.power_unit_label = UnitLabel("W")
        readings_layout.addWidget(self.power_unit_label, row, 2)
        row += 1

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line, row, 0, 1, 3)
        row += 1

        # Capacity
        self.capacity_row_label = QLabel("Capacity:")
        readings_layout.addWidget(self.capacity_row_label, row, 0)
        self.capacity_label = StatusLabel()
        self.capacity_label.setStyleSheet("color: #AB47BC;")  # Purple
        readings_layout.addWidget(self.capacity_label, row, 1)
        self.capacity_unit_label = UnitLabel("mAh")
        readings_layout.addWidget(self.capacity_unit_label, row, 2)
        row += 1

        # Energy
        self.energy_row_label = QLabel("Energy:")
        readings_layout.addWidget(self.energy_row_label, row, 0)
        self.energy_label = StatusLabel()
        self.energy_label.setStyleSheet("color: #FF7043;")  # Deep orange
        readings_layout.addWidget(self.energy_label, row, 1)
        self.energy_unit_label = UnitLabel("Wh")
        readings_layout.addWidget(self.energy_unit_label, row, 2)
        row += 1

        # Clear button for capacity/energy
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        readings_layout.addWidget(self.clear_btn, row, 0, 1, 3)
        row += 1

        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line2, row, 0, 1, 3)
        row += 1

        # MOSFET Temperature
        self.temp_row_label = QLabel("MOSFET:")
        readings_layout.addWidget(self.temp_row_label, row, 0)
        self.temp_label = StatusLabel()
        self.temp_label.setStyleSheet("color: #26A69A;")  # Teal
        readings_layout.addWidget(self.temp_label, row, 1)
        self.temp_unit_label = UnitLabel("°C")
        readings_layout.addWidget(self.temp_unit_label, row, 2)
        row += 1

        # External Temperature
        self.ext_temp_row_label = QLabel("External:")
        readings_layout.addWidget(self.ext_temp_row_label, row, 0)
        self.ext_temp_label = StatusLabel()
        self.ext_temp_label.setStyleSheet("color: #9CCC65;")  # Light green
        readings_layout.addWidget(self.ext_temp_label, row, 1)
        self.ext_temp_unit_label = UnitLabel("°C")
        readings_layout.addWidget(self.ext_temp_unit_label, row, 2)
        row += 1

        # Fan Speed
        self.fan_row_label = QLabel("Fan:")
        readings_layout.addWidget(self.fan_row_label, row, 0)
        self.fan_label = StatusLabel()
        readings_layout.addWidget(self.fan_label, row, 1)
        self.fan_unit_label = UnitLabel("RPM")
        readings_layout.addWidget(self.fan_unit_label, row, 2)
        row += 1

        # Separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setFrameShadow(QFrame.Sunken)
        readings_layout.addWidget(line3, row, 0, 1, 3)
        row += 1

        # Status (ON/OFF)
        self.status_row_label = QLabel("Status:")
        readings_layout.addWidget(self.status_row_label, row, 0)
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

        layout.addWidget(self.readings_group)

        # Data Logging group
        self.log_group = QGroupBox("Data Logging")
        log_layout = QVBoxLayout(self.log_group)

        # Logging toggle switch
        logging_layout = QHBoxLayout()

        self.log_label_off = QLabel("OFF")
        logging_layout.addWidget(self.log_label_off)

        self.log_switch = ToggleSwitch()
        self.log_switch.setEnabled(False)
        self.log_switch.toggled.connect(self._on_logging_toggled)
        logging_layout.addWidget(self.log_switch)

        self.log_label_on = QLabel("ON")
        logging_layout.addWidget(self.log_label_on)

        self.show_points_checkbox = QCheckBox("Points")
        self.show_points_checkbox.setChecked(False)
        self.show_points_checkbox.setToolTip("Show point markers on plot")
        self.show_points_checkbox.setEnabled(False)
        self.show_points_checkbox.toggled.connect(self._on_show_points_toggled)
        logging_layout.addWidget(self.show_points_checkbox)

        log_layout.addLayout(logging_layout)

        # Filename prefix input
        name_layout = QHBoxLayout()
        self.battery_label = QLabel("Prefix:")
        name_layout.addWidget(self.battery_label)
        self.battery_name_edit = QLineEdit()
        self.battery_name_edit.setText("battery")
        self.battery_name_edit.setEnabled(False)
        name_layout.addWidget(self.battery_name_edit)
        log_layout.addLayout(name_layout)

        # Save and Clear buttons
        buttons_layout = QHBoxLayout()
        self.save_btn = QPushButton("Export")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(self.save_btn)

        self.clear_log_btn = QPushButton("Clear")
        self.clear_log_btn.setEnabled(False)
        self.clear_log_btn.clicked.connect(self._on_clear_clicked)
        buttons_layout.addWidget(self.clear_log_btn)
        log_layout.addLayout(buttons_layout)

        # Total logged display (time and points)
        totals_layout = QHBoxLayout()
        self.logged_time_label = QLabel("Total Logged:")
        totals_layout.addWidget(self.logged_time_label)
        totals_layout.addStretch()
        self.logging_time_label = StatusLabel("0h 0m 0s")
        totals_layout.addWidget(self.logging_time_label)
        self.points_label = QLabel("(0 pts)")
        totals_layout.addWidget(self.points_label)
        log_layout.addLayout(totals_layout)

        layout.addWidget(self.log_group)

        # Spacer
        layout.addStretch()

    def set_connected(self, connected: bool) -> None:
        """Update UI for connection state."""
        # Grey out group titles when disconnected
        if connected:
            self.readings_group.setStyleSheet("")
            self.log_group.setStyleSheet("")
        else:
            self.readings_group.setStyleSheet("QGroupBox { color: gray; }")
            self.log_group.setStyleSheet("QGroupBox { color: gray; }")

        # Live readings labels
        self.voltage_row_label.setEnabled(connected)
        self.voltage_label.setEnabled(connected)
        self.voltage_unit_label.setEnabled(connected)
        self.current_row_label.setEnabled(connected)
        self.current_label.setEnabled(connected)
        self.current_unit_label.setEnabled(connected)
        self.power_row_label.setEnabled(connected)
        self.power_label.setEnabled(connected)
        self.power_unit_label.setEnabled(connected)
        self.capacity_row_label.setEnabled(connected)
        self.capacity_label.setEnabled(connected)
        self.capacity_unit_label.setEnabled(connected)
        self.energy_row_label.setEnabled(connected)
        self.energy_label.setEnabled(connected)
        self.energy_unit_label.setEnabled(connected)
        self.temp_row_label.setEnabled(connected)
        self.temp_label.setEnabled(connected)
        self.temp_unit_label.setEnabled(connected)
        self.ext_temp_row_label.setEnabled(connected)
        self.ext_temp_label.setEnabled(connected)
        self.ext_temp_unit_label.setEnabled(connected)
        self.fan_row_label.setEnabled(connected)
        self.fan_label.setEnabled(connected)
        self.fan_unit_label.setEnabled(connected)
        self.status_row_label.setEnabled(connected)
        self.load_status_label.setEnabled(connected)

        # Logging controls
        self.log_switch.setEnabled(connected)
        self.log_label_off.setEnabled(connected)
        self.log_label_on.setEnabled(connected)

        # Battery name
        self.battery_label.setEnabled(connected)
        self.battery_name_edit.setEnabled(connected)

        # Show points checkbox
        self.show_points_checkbox.setEnabled(connected)

        # Buttons
        self.clear_btn.setEnabled(connected)
        self.save_btn.setEnabled(connected)
        # Clear log button only enabled when connected and not logging
        self.clear_log_btn.setEnabled(connected and not self.log_switch.isChecked())

        # Logged time and points
        self.logged_time_label.setEnabled(connected)
        self.logging_time_label.setEnabled(connected)
        self.points_label.setEnabled(connected)

        if not connected:
            self.log_switch.setChecked(False)
            self._update_logging_labels(False)
            self.clear()  # Reset values to "---"

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
        # Clear button only enabled when not logging
        self.clear_log_btn.setEnabled(not checked)
        self.logging_toggled.emit(checked)

    @Slot()
    def _on_clear_clicked(self) -> None:
        """Handle clear button click."""
        self.clear_requested.emit()

    @Slot(bool)
    def _on_show_points_toggled(self, checked: bool) -> None:
        """Handle show points checkbox toggle."""
        self.show_points_toggled.emit(checked)

    def set_points_count(self, count: int) -> None:
        """Set the logged points count display."""
        self.points_label.setText(f"({count} pts)")

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

        self.temp_label.setText(f"{status.temperature_c:.1f}")
        self.ext_temp_label.setText(f"{status.ext_temperature_c:.1f}")

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
        self.logging_time_label.setText(f"{h}h {m}m {s}s")

    def clear_logging_time(self) -> None:
        """Reset the logging time display."""
        self.logging_time_label.setText("0h 0m 0s")

    def clear(self) -> None:
        """Clear all status displays."""
        self.voltage_label.setText("---")
        self.current_label.setText("---")
        self.power_label.setText("---")
        self.capacity_label.setText("---")
        self.energy_label.setText("---")
        self.temp_label.setText("---")
        self.ext_temp_label.setText("---")
        self.logging_time_label.setText("0h 0m 0s")
        self.load_status_label.setText("OFF")
        self.load_status_label.setStyleSheet("color: #888888;")
        self.warning_label.setText("")
        self.ureg_label.setText("")
        self.fan_label.setText("---")
