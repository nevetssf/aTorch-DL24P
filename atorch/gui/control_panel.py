"""Device control panel widget."""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QFrame,
    QButtonGroup,
    QRadioButton,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QBrush


class ToggleSwitch(QWidget):
    """A toggle switch widget."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self._enabled = True
        self._handle_position = 0.0

        self.setFixedSize(60, 28)
        self.setCursor(Qt.PointingHandCursor)

        # Animation for smooth toggle
        self._animation = QPropertyAnimation(self, b"handle_position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.InOutQuad)

    def get_handle_position(self):
        return self._handle_position

    def set_handle_position(self, pos):
        self._handle_position = pos
        self.update()

    handle_position = Property(float, get_handle_position, set_handle_position)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if self._checked != checked:
            self._checked = checked
            self._animation.setStartValue(self._handle_position)
            self._animation.setEndValue(1.0 if checked else 0.0)
            self._animation.start()

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.update()

    def isEnabled(self) -> bool:
        return self._enabled

    def mousePressEvent(self, event):
        if self._enabled and event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._animation.setStartValue(self._handle_position)
            self._animation.setEndValue(1.0 if self._checked else 0.0)
            self._animation.start()
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Colors based on state
        if not self._enabled:
            track_color = QColor(180, 180, 180)
            handle_color = QColor(220, 220, 220)
        elif self._checked:
            track_color = QColor(76, 175, 80)  # Green
            handle_color = QColor(255, 255, 255)
        else:
            track_color = QColor(158, 158, 158)  # Gray
            handle_color = QColor(255, 255, 255)

        # Draw track
        track_height = 20
        track_y = (h - track_height) // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(0, track_y, w, track_height, track_height // 2, track_height // 2)

        # Draw handle
        handle_diameter = 24
        handle_y = (h - handle_diameter) // 2
        handle_x = int(self._handle_position * (w - handle_diameter))

        painter.setBrush(QBrush(handle_color))
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawEllipse(handle_x, handle_y, handle_diameter, handle_diameter)

        painter.end()

from ..protocol.device import Device, USBHIDDevice, PortType
from ..protocol.atorch_protocol import DeviceStatus
from ..automation.test_runner import TestRunner


class ConnectionType:
    """Connection type constants."""
    SERIAL_USB = "serial_usb"
    SERIAL_BT = "serial_bt"
    SERIAL_ALL = "serial_all"
    USB_HID = "usb_hid"


class ControlPanel(QWidget):
    """Panel for device connection and control."""

    connect_requested = Signal(str)  # connection_type
    disconnect_requested = Signal()
    logging_toggled = Signal(bool)
    clear_requested = Signal()  # Request to clear accumulated data
    save_requested = Signal(str)  # Request to save/export data, passes battery name

    def __init__(self, device: Device, test_runner: TestRunner):
        super().__init__()

        self.device = device
        self.test_runner = test_runner
        self._connected = False
        self._connection_type = ConnectionType.SERIAL_ALL

        self._create_ui()
        self._refresh_ports()

    def _create_ui(self) -> None:
        """Create the control panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Connection group
        conn_group = QGroupBox("Connection")
        conn_layout = QVBoxLayout(conn_group)

        # Connection type selection (USB HID / Bluetooth)
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Type:"))

        self.usb_hid_radio = QRadioButton("USB HID")
        self.usb_hid_radio.setToolTip("USB HID (direct USB connection)")
        type_layout.addWidget(self.usb_hid_radio)

        self.bt_radio = QRadioButton("Bluetooth")
        self.bt_radio.setToolTip("Bluetooth SPP")
        type_layout.addWidget(self.bt_radio)

        type_layout.addStretch()
        conn_layout.addLayout(type_layout)

        # Port selection
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        port_layout.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setMaximumWidth(30)
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(self.refresh_btn)
        conn_layout.addLayout(port_layout)

        # Connect and Disconnect buttons
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        btn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)  # Disabled when not connected
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_layout.addWidget(self.disconnect_btn)
        conn_layout.addLayout(btn_layout)

        layout.addWidget(conn_group)

        # Load Control group
        control_group = QGroupBox("Load Control")
        control_layout = QVBoxLayout(control_group)

        # On/Off toggle switch
        power_layout = QHBoxLayout()
        power_layout.addWidget(QLabel("Load:"))
        power_layout.addStretch()

        self.power_label_off = QLabel("OFF")
        self.power_label_off.setStyleSheet("font-weight: bold; color: #666;")
        power_layout.addWidget(self.power_label_off)

        self.power_switch = ToggleSwitch()
        self.power_switch.setEnabled(False)
        self.power_switch.toggled.connect(self._on_power_toggled)
        power_layout.addWidget(self.power_switch)

        self.power_label_on = QLabel("ON")
        self.power_label_on.setStyleSheet("font-weight: bold; color: #666;")
        power_layout.addWidget(self.power_label_on)

        power_layout.addStretch()
        control_layout.addLayout(power_layout)

        # Current setting
        current_layout = QHBoxLayout()
        current_layout.addWidget(QLabel("Current (A):"))
        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0.0, 24.0)
        self.current_spin.setDecimals(3)
        self.current_spin.setSingleStep(0.1)
        self.current_spin.setValue(0.5)
        self.current_spin.setEnabled(False)
        current_layout.addWidget(self.current_spin)

        self.set_current_btn = QPushButton("Set")
        self.set_current_btn.setMaximumWidth(50)
        self.set_current_btn.setEnabled(False)
        self.set_current_btn.clicked.connect(self._on_set_current)
        current_layout.addWidget(self.set_current_btn)
        control_layout.addLayout(current_layout)

        # Quick current presets for low-current testing
        preset_layout = QHBoxLayout()
        for current in [0.1, 0.2, 0.5, 1.0]:
            btn = QPushButton(f"{current}A")
            btn.setMaximumWidth(50)
            btn.clicked.connect(lambda checked, c=current: self._set_current_preset(c))
            preset_layout.addWidget(btn)
        self.preset_btns = preset_layout
        control_layout.addLayout(preset_layout)

        # Voltage cutoff
        cutoff_layout = QHBoxLayout()
        cutoff_layout.addWidget(QLabel("V Cutoff:"))
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 200.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(3.0)
        self.cutoff_spin.setEnabled(False)
        cutoff_layout.addWidget(self.cutoff_spin)

        self.set_cutoff_btn = QPushButton("Set")
        self.set_cutoff_btn.setMaximumWidth(50)
        self.set_cutoff_btn.setEnabled(False)
        self.set_cutoff_btn.clicked.connect(self._on_set_cutoff)
        cutoff_layout.addWidget(self.set_cutoff_btn)
        control_layout.addLayout(cutoff_layout)

        # Discharge time (hours and minutes)
        discharge_layout = QHBoxLayout()
        discharge_layout.addWidget(QLabel("Time Limit:"))

        self.discharge_hours_spin = QSpinBox()
        self.discharge_hours_spin.setRange(0, 99)
        self.discharge_hours_spin.setSingleStep(1)
        self.discharge_hours_spin.setValue(0)
        self.discharge_hours_spin.setSuffix("h")
        self.discharge_hours_spin.setToolTip("Hours (0-99)")
        self.discharge_hours_spin.setEnabled(False)
        self.discharge_hours_spin.setMaximumWidth(60)
        discharge_layout.addWidget(self.discharge_hours_spin)

        self.discharge_mins_spin = QSpinBox()
        self.discharge_mins_spin.setRange(0, 59)
        self.discharge_mins_spin.setSingleStep(1)
        self.discharge_mins_spin.setValue(0)
        self.discharge_mins_spin.setSuffix("m")
        self.discharge_mins_spin.setToolTip("Minutes (0-59)")
        self.discharge_mins_spin.setEnabled(False)
        self.discharge_mins_spin.setMaximumWidth(60)
        discharge_layout.addWidget(self.discharge_mins_spin)

        self.set_discharge_btn = QPushButton("Set")
        self.set_discharge_btn.setMaximumWidth(50)
        self.set_discharge_btn.setEnabled(False)
        self.set_discharge_btn.clicked.connect(self._on_set_discharge_time)
        discharge_layout.addWidget(self.set_discharge_btn)
        control_layout.addLayout(discharge_layout)

        # Reset counters
        self.reset_btn = QPushButton("Reset Counters")
        self.reset_btn.setToolTip(
            "Turns OFF the load and resets counters.\n"
            "Note: Counter reset may not work over USB HID.\n"
            "Use device buttons if counters don't reset."
        )
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self._on_reset)
        control_layout.addWidget(self.reset_btn)

        layout.addWidget(control_group)

        # Display group (USB HID only)
        display_group = QGroupBox("Display")
        display_layout = QVBoxLayout(display_group)

        # Brightness slider
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(QLabel("Brightness:"))

        from PySide6.QtWidgets import QSlider
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(1, 9)  # 1-9 range (from USB capture)
        self.brightness_slider.setValue(5)  # Default middle
        self.brightness_slider.setEnabled(False)
        self.brightness_slider.setToolTip("Adjust device screen brightness (USB HID only)\nRelease slider to apply.")
        # Only send on release, not while dragging
        self.brightness_slider.valueChanged.connect(self._on_brightness_label_update)
        self.brightness_slider.sliderReleased.connect(self._on_brightness_apply)
        brightness_layout.addWidget(self.brightness_slider)

        self.brightness_label = QLabel("5")
        self.brightness_label.setMinimumWidth(25)
        brightness_layout.addWidget(self.brightness_label)

        display_layout.addLayout(brightness_layout)
        layout.addWidget(display_group)

        # Logging group
        log_group = QGroupBox("Data Logging")
        log_layout = QVBoxLayout(log_group)

        # Logging toggle switch
        logging_layout = QHBoxLayout()
        logging_layout.addWidget(QLabel("Logging:"))
        logging_layout.addStretch()

        self.log_label_off = QLabel("OFF")
        self.log_label_off.setStyleSheet("font-weight: bold; color: #666;")
        logging_layout.addWidget(self.log_label_off)

        self.log_switch = ToggleSwitch()
        self.log_switch.setEnabled(False)
        self.log_switch.toggled.connect(self._on_logging_toggled)
        logging_layout.addWidget(self.log_switch)

        self.log_label_on = QLabel("ON")
        self.log_label_on.setStyleSheet("font-weight: bold; color: #666;")
        logging_layout.addWidget(self.log_label_on)

        logging_layout.addStretch()
        log_layout.addLayout(logging_layout)

        # Battery name row
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Battery Name:"))
        self.battery_name_edit = QLineEdit()
        self.battery_name_edit.setPlaceholderText("Optional")
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

        layout.addWidget(log_group)

        # Spacer
        layout.addStretch()

        # Connect radio button signals (after all widgets created)
        self.usb_hid_radio.toggled.connect(self._on_type_changed)
        self.bt_radio.toggled.connect(self._on_type_changed)

        # Set default selection (triggers refresh)
        self.usb_hid_radio.setChecked(True)

    @property
    def selected_port(self) -> Optional[str]:
        """Get currently selected port."""
        if self.port_combo.currentIndex() >= 0:
            return self.port_combo.currentData()
        return None

    def set_connected(self, connected: bool) -> None:
        """Update UI for connection state."""
        self._connected = connected

        self.port_combo.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        self.usb_hid_radio.setEnabled(not connected)
        self.bt_radio.setEnabled(not connected)
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)

        self.power_switch.setEnabled(connected)
        self.current_spin.setEnabled(connected)
        self.set_current_btn.setEnabled(connected)

        # Voltage cutoff now works for USB HID (sub-command 0x29)
        is_usb_hid = self._connection_type == ConnectionType.USB_HID
        self.cutoff_spin.setEnabled(connected)
        self.set_cutoff_btn.setEnabled(connected)
        self.set_cutoff_btn.setToolTip("")

        # Discharge time (USB HID only)
        self.discharge_hours_spin.setEnabled(connected and is_usb_hid)
        self.discharge_mins_spin.setEnabled(connected and is_usb_hid)
        self.set_discharge_btn.setEnabled(connected and is_usb_hid)

        # Brightness slider only for USB HID
        self.brightness_slider.setEnabled(connected and is_usb_hid)

        self.reset_btn.setEnabled(connected)
        self.log_switch.setEnabled(connected)
        self.clear_btn.setEnabled(connected)
        self.save_btn.setEnabled(connected)

        # Enable/disable preset buttons
        for i in range(self.preset_btns.count()):
            widget = self.preset_btns.itemAt(i).widget()
            if widget:
                widget.setEnabled(connected)

        if not connected:
            self.power_switch.setChecked(False)
            self._update_power_labels(False)
            self.log_switch.setChecked(False)
            self._update_logging_labels(False)

    def update_status(self, status: DeviceStatus) -> None:
        """Update UI with device status."""
        # Sync toggle switch with actual device load state
        if status.load_on != self.power_switch.isChecked():
            self.power_switch.setChecked(status.load_on)
            self._update_power_labels(status.load_on)

    def _on_type_changed(self) -> None:
        """Handle connection type radio button change."""
        if self.usb_hid_radio.isChecked():
            self._connection_type = ConnectionType.USB_HID
        elif self.bt_radio.isChecked():
            self._connection_type = ConnectionType.SERIAL_BT
        else:
            self._connection_type = ConnectionType.USB_HID
        self._refresh_ports()

    def _refresh_ports(self) -> None:
        """Refresh the list of available ports/devices."""
        self.port_combo.clear()

        if self._connection_type == ConnectionType.USB_HID:
            # List USB HID devices
            if USBHIDDevice.is_available():
                devices = USBHIDDevice.list_devices()
                for dev in devices:
                    label = f"[USB HID] {dev['product']}"
                    if dev.get('serial'):
                        label += f" ({dev['serial']})"
                    self.port_combo.addItem(label, dev['path'])
                    # Auto-select first device
                    if self.port_combo.count() == 1:
                        self.port_combo.setCurrentIndex(0)
                if not devices:
                    self.port_combo.addItem("No USB HID devices found", "")
            else:
                self.port_combo.addItem("hidapi not installed", "")
        else:
            # List serial ports
            port_type = None
            if self._connection_type == ConnectionType.SERIAL_USB:
                port_type = PortType.USB
            elif self._connection_type == ConnectionType.SERIAL_BT:
                port_type = PortType.BLUETOOTH
            # else: show all

            # Get ports filtered by type
            ports = Device.list_ports(port_type)

            # Get likely DL24P ports (USB only)
            dl24p_ports = set(Device.find_dl24p_ports())

            for port, desc, ptype in ports:
                # Build label with port type indicator
                type_str = ""
                if ptype == PortType.USB:
                    type_str = "[Serial USB] "
                elif ptype == PortType.BLUETOOTH:
                    type_str = "[BT] "

                label = f"{type_str}{port}"
                if port in dl24p_ports:
                    label += " (DL24P?)"

                self.port_combo.addItem(label, port)

                # Select likely DL24P port
                if port in dl24p_ports:
                    self.port_combo.setCurrentIndex(self.port_combo.count() - 1)

    @property
    def connection_type(self) -> str:
        """Get current connection type."""
        return self._connection_type

    @Slot()
    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        self.connect_requested.emit(self._connection_type)

    def _on_disconnect_clicked(self) -> None:
        """Handle disconnect button click."""
        self.disconnect_requested.emit()

    def _update_power_labels(self, is_on: bool) -> None:
        """Update power label styling based on state."""
        if is_on:
            self.power_label_on.setStyleSheet("font-weight: bold; color: #4CAF50;")
            self.power_label_off.setStyleSheet("font-weight: bold; color: #666;")
        else:
            self.power_label_on.setStyleSheet("font-weight: bold; color: #666;")
            self.power_label_off.setStyleSheet("font-weight: bold; color: #666;")

    @Slot(bool)
    def _on_power_toggled(self, checked: bool) -> None:
        """Handle power toggle switch."""
        if checked:
            self.device.turn_on()
        else:
            self.device.turn_off()
        self._update_power_labels(checked)

    def _update_logging_labels(self, is_on: bool) -> None:
        """Update logging label styling based on state."""
        if is_on:
            self.log_label_on.setStyleSheet("font-weight: bold; color: #4CAF50;")
            self.log_label_off.setStyleSheet("font-weight: bold; color: #666;")
        else:
            self.log_label_on.setStyleSheet("font-weight: bold; color: #666;")
            self.log_label_off.setStyleSheet("font-weight: bold; color: #666;")

    @Slot(bool)
    def _on_logging_toggled(self, checked: bool) -> None:
        """Handle logging toggle switch."""
        self._update_logging_labels(checked)
        # Save button stays enabled (to save accumulated data), clear button always enabled when connected
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

    @Slot()
    def _on_set_current(self) -> None:
        """Set the load current."""
        current = self.current_spin.value()
        self.device.set_current(current)

    def _set_current_preset(self, current: float) -> None:
        """Set current from preset button."""
        self.current_spin.setValue(current)
        self.device.set_current(current)

    @Slot()
    def _on_set_cutoff(self) -> None:
        """Set voltage cutoff."""
        voltage = self.cutoff_spin.value()
        self.device.set_voltage_cutoff(voltage)

    @Slot()
    def _on_set_discharge_time(self) -> None:
        """Set discharge time limit."""
        hours = self.discharge_hours_spin.value()
        minutes = self.discharge_mins_spin.value()
        self.device.set_discharge_time(hours, minutes)

    @Slot()
    def _on_reset(self) -> None:
        """Reset counters - turns off load first, then resets."""
        # Turn off the load
        self.device.turn_off()

        # Update GUI toggle to OFF
        self.power_switch.setChecked(False)
        self._update_power_labels(False)

        # Reset the counters
        self.device.reset_counters()

    @Slot(int)
    def _on_brightness_label_update(self, value: int) -> None:
        """Update brightness label while dragging (don't send command yet)."""
        self.brightness_label.setText(str(value))

    @Slot()
    def _on_brightness_apply(self) -> None:
        """Apply brightness when slider is released."""
        value = self.brightness_slider.value()
        # Only send if we have a USB HID device with set_brightness method
        if hasattr(self.device, 'set_brightness'):
            self.device.set_brightness(value)

