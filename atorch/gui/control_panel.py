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
from PySide6.QtCore import Qt, Signal, Slot, QSize, Property, QPropertyAnimation, QEasingCurve, QTimer
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

    def __init__(self, device: Device, test_runner: TestRunner):
        super().__init__()

        self.device = device
        self.test_runner = test_runner
        self._connected = False
        self._connection_type = ConnectionType.SERIAL_ALL

        # Current setting sync state
        self._current_user_editing = False  # True when user is editing the spinbox
        self._current_edit_timer = QTimer()  # Timer to resume sync after editing
        self._current_edit_timer.setSingleShot(True)
        self._current_edit_timer.timeout.connect(self._on_current_edit_timeout)
        self._last_load_on = False  # Track load state changes

        # Voltage cutoff setting sync state
        self._cutoff_user_editing = False
        self._cutoff_edit_timer = QTimer()
        self._cutoff_edit_timer.setSingleShot(True)
        self._cutoff_edit_timer.timeout.connect(self._on_cutoff_edit_timeout)

        # Time limit setting sync state
        self._time_limit_user_editing = False
        self._time_limit_edit_timer = QTimer()
        self._time_limit_edit_timer.setSingleShot(True)
        self._time_limit_edit_timer.timeout.connect(self._on_time_limit_edit_timeout)

        # Power setting sync state (for CP mode)
        self._power_user_editing = False
        self._power_edit_timer = QTimer()
        self._power_edit_timer.setSingleShot(True)
        self._power_edit_timer.timeout.connect(self._on_power_edit_timeout)

        # Voltage setting sync state (for CV mode)
        self._voltage_user_editing = False
        self._voltage_edit_timer = QTimer()
        self._voltage_edit_timer.setSingleShot(True)
        self._voltage_edit_timer.timeout.connect(self._on_voltage_edit_timeout)

        # Resistance setting sync state (for CR mode)
        self._resistance_user_editing = False
        self._resistance_edit_timer = QTimer()
        self._resistance_edit_timer.setSingleShot(True)
        self._resistance_edit_timer.timeout.connect(self._on_resistance_edit_timeout)

        # Current mode (0=CC, 1=CP, 2=CV, 3=CR)
        self._current_mode = 0

        self._create_ui()
        self._refresh_ports()

        # Initialize disconnected state (grey out controls)
        self.set_connected(False)

    def _create_ui(self) -> None:
        """Create the control panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Connection group
        conn_group = QGroupBox("Connection")
        conn_layout = QVBoxLayout(conn_group)

        # Connection type selection (USB HID / Bluetooth)
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Type"))

        self.usb_hid_radio = QRadioButton("USB HID")
        self.usb_hid_radio.setToolTip("USB HID (direct USB connection)")
        type_layout.addWidget(self.usb_hid_radio)

        self.bt_radio = QRadioButton("Bluetooth")
        self.bt_radio.setToolTip("Bluetooth not supported (protocol unknown)")
        self.bt_radio.setEnabled(False)  # Disabled until protocol is reverse-engineered
        type_layout.addWidget(self.bt_radio)

        type_layout.addStretch()
        conn_layout.addLayout(type_layout)

        # Port selection
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self.port_combo.setToolTip("Select USB port for DL24P device")
        port_layout.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setMaximumWidth(30)
        self.refresh_btn.setToolTip("Refresh port list")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        port_layout.addWidget(self.refresh_btn)
        conn_layout.addLayout(port_layout)

        # Debug logging checkbox
        self.debug_log_checkbox = QCheckBox("Debug Log")
        self.debug_log_checkbox.setChecked(True)  # On by default
        self.debug_log_checkbox.setToolTip("Log debug output to debug.log")
        conn_layout.addWidget(self.debug_log_checkbox)

        # Connect and Disconnect buttons
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setToolTip("Connect to the selected DL24P device")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        btn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)  # Disabled when not connected
        self.disconnect_btn.setToolTip("Disconnect from the device")
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_layout.addWidget(self.disconnect_btn)

        # Communication indicator
        self.comm_indicator = QLabel("●")
        self.comm_indicator.setStyleSheet("color: #555555; font-size: 16px;")
        self.comm_indicator.setToolTip("Communication status")
        self.comm_indicator.setFixedWidth(20)
        btn_layout.addWidget(self.comm_indicator)

        # Timer to fade indicator back to grey
        self._comm_fade_timer = QTimer()
        self._comm_fade_timer.setSingleShot(True)
        self._comm_fade_timer.timeout.connect(self._fade_comm_indicator)

        conn_layout.addLayout(btn_layout)

        layout.addWidget(conn_group)

        # Load Control group
        self.control_group = QGroupBox("Load Control")
        control_layout = QVBoxLayout(self.control_group)

        # Mode selection (CC, CP, CV, CR)
        mode_layout = QHBoxLayout()
        self.mode_btn_group = QButtonGroup(self)
        self.mode_btn_group.setExclusive(True)

        self.cc_btn = QPushButton("CC")
        self.cc_btn.setCheckable(True)
        self.cc_btn.setChecked(True)  # Default to CC mode
        self.cc_btn.setToolTip("Constant Current mode - maintains steady current draw")
        self.cc_btn.setEnabled(False)
        self.mode_btn_group.addButton(self.cc_btn, 0)
        mode_layout.addWidget(self.cc_btn)

        self.cp_btn = QPushButton("CP")
        self.cp_btn.setCheckable(True)
        self.cp_btn.setToolTip("Constant Power mode - maintains steady power consumption")
        self.cp_btn.setEnabled(False)
        self.mode_btn_group.addButton(self.cp_btn, 1)
        mode_layout.addWidget(self.cp_btn)

        self.cv_btn = QPushButton("CV")
        self.cv_btn.setCheckable(True)
        self.cv_btn.setToolTip("Constant Voltage mode - maintains steady voltage")
        self.cv_btn.setEnabled(False)
        self.mode_btn_group.addButton(self.cv_btn, 2)
        mode_layout.addWidget(self.cv_btn)

        self.cr_btn = QPushButton("CR")
        self.cr_btn.setCheckable(True)
        self.cr_btn.setToolTip("Constant Resistance mode - simulates fixed resistance load")
        self.cr_btn.setEnabled(False)
        self.mode_btn_group.addButton(self.cr_btn, 3)
        mode_layout.addWidget(self.cr_btn)

        self.mode_btn_group.idClicked.connect(self._on_mode_changed)
        control_layout.addLayout(mode_layout)

        # On/Off toggle switch
        power_layout = QHBoxLayout()
        self.load_label = QLabel("Load")
        power_layout.addWidget(self.load_label)
        power_layout.addStretch()

        self.power_label_off = QLabel("OFF")
        self.power_label_off.setStyleSheet("font-weight: bold; color: #666;")
        power_layout.addWidget(self.power_label_off)

        self.power_switch = ToggleSwitch()
        self.power_switch.setEnabled(False)
        self.power_switch.setToolTip("Turn electronic load ON/OFF - activates current draw")
        self.power_switch.toggled.connect(self._on_power_toggled)
        power_layout.addWidget(self.power_switch)

        self.power_label_on = QLabel("ON")
        self.power_label_on.setStyleSheet("font-weight: bold; color: #666;")
        power_layout.addWidget(self.power_label_on)

        power_layout.addStretch()
        control_layout.addLayout(power_layout)

        # Separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        control_layout.addWidget(line1)

        # Current setting
        current_layout = QHBoxLayout()
        self.current_label = QLabel("Current (A)")
        current_layout.addWidget(self.current_label)
        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0.0, 24.0)
        self.current_spin.setDecimals(3)
        self.current_spin.setSingleStep(0.1)
        self.current_spin.setValue(0.5)
        self.current_spin.setEnabled(False)
        self.current_spin.setToolTip("Set target current for CC mode (0-24A)")
        self.current_spin.valueChanged.connect(self._on_current_value_changed)
        current_layout.addWidget(self.current_spin)

        self.set_current_btn = QPushButton("Set")
        self.set_current_btn.setMaximumWidth(50)
        self.set_current_btn.setEnabled(False)
        self.set_current_btn.setToolTip("Apply current setting to device")
        self.set_current_btn.clicked.connect(self._on_set_current)
        current_layout.addWidget(self.set_current_btn)
        control_layout.addLayout(current_layout)

        # Quick current presets for low-current testing
        preset_layout = QHBoxLayout()
        for current in [0.1, 0.2, 0.5, 1.0]:
            btn = QPushButton(f"{current}A")
            btn.setMaximumWidth(50)
            btn.setToolTip(f"Quick set to {current}A")
            btn.clicked.connect(lambda checked, c=current: self._set_current_preset(c))
            preset_layout.addWidget(btn)
        self.preset_btns = preset_layout
        control_layout.addLayout(preset_layout)

        # Power setting (for CP mode)
        power_layout = QHBoxLayout()
        self.power_label = QLabel("Power (W)")
        power_layout.addWidget(self.power_label)
        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(0.0, 200.0)  # DL24P max is ~180W
        self.power_spin.setDecimals(1)
        self.power_spin.setSingleStep(1.0)
        self.power_spin.setValue(5.0)
        self.power_spin.setEnabled(False)
        self.power_spin.setToolTip("Set target power for CP mode (0-200W)")
        self.power_spin.valueChanged.connect(self._on_power_value_changed)
        power_layout.addWidget(self.power_spin)

        self.set_power_btn = QPushButton("Set")
        self.set_power_btn.setMaximumWidth(50)
        self.set_power_btn.setEnabled(False)
        self.set_power_btn.setToolTip("Apply power setting to device")
        self.set_power_btn.clicked.connect(self._on_set_power)
        power_layout.addWidget(self.set_power_btn)
        control_layout.addLayout(power_layout)

        # Voltage setting (for CV mode)
        voltage_layout = QHBoxLayout()
        self.voltage_label = QLabel("Voltage (V)")
        voltage_layout.addWidget(self.voltage_label)
        self.voltage_spin = QDoubleSpinBox()
        self.voltage_spin.setRange(0.0, 200.0)
        self.voltage_spin.setDecimals(2)
        self.voltage_spin.setSingleStep(0.1)
        self.voltage_spin.setValue(5.0)
        self.voltage_spin.setEnabled(False)
        self.voltage_spin.setToolTip("Set target voltage for CV mode (0-200V)")
        self.voltage_spin.valueChanged.connect(self._on_voltage_value_changed)
        voltage_layout.addWidget(self.voltage_spin)

        self.set_voltage_btn = QPushButton("Set")
        self.set_voltage_btn.setMaximumWidth(50)
        self.set_voltage_btn.setEnabled(False)
        self.set_voltage_btn.setToolTip("Apply voltage setting to device")
        self.set_voltage_btn.clicked.connect(self._on_set_voltage)
        voltage_layout.addWidget(self.set_voltage_btn)
        control_layout.addLayout(voltage_layout)

        # Resistance setting (for CR mode)
        resistance_layout = QHBoxLayout()
        self.resistance_label = QLabel("Resistance (Ω)")
        resistance_layout.addWidget(self.resistance_label)
        self.resistance_spin = QDoubleSpinBox()
        self.resistance_spin.setRange(0.1, 9999.0)
        self.resistance_spin.setDecimals(1)
        self.resistance_spin.setSingleStep(1.0)
        self.resistance_spin.setValue(10.0)
        self.resistance_spin.setEnabled(False)
        self.resistance_spin.setToolTip("Set target resistance for CR mode (0.1-9999Ω)")
        self.resistance_spin.valueChanged.connect(self._on_resistance_value_changed)
        resistance_layout.addWidget(self.resistance_spin)

        self.set_resistance_btn = QPushButton("Set")
        self.set_resistance_btn.setMaximumWidth(50)
        self.set_resistance_btn.setEnabled(False)
        self.set_resistance_btn.setToolTip("Apply resistance setting to device")
        self.set_resistance_btn.clicked.connect(self._on_set_resistance)
        resistance_layout.addWidget(self.set_resistance_btn)
        control_layout.addLayout(resistance_layout)

        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        control_layout.addWidget(line2)

        # Voltage cutoff
        cutoff_layout = QHBoxLayout()
        self.cutoff_label = QLabel("V Cutoff")
        cutoff_layout.addWidget(self.cutoff_label)
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 200.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(3.0)
        self.cutoff_spin.setEnabled(False)
        self.cutoff_spin.setToolTip("Voltage cutoff - load turns off when voltage drops below this value")
        self.cutoff_spin.valueChanged.connect(self._on_cutoff_value_changed)
        cutoff_layout.addWidget(self.cutoff_spin)

        self.set_cutoff_btn = QPushButton("Set")
        self.set_cutoff_btn.setMaximumWidth(50)
        self.set_cutoff_btn.setEnabled(False)
        self.set_cutoff_btn.setToolTip("Apply voltage cutoff setting to device")
        self.set_cutoff_btn.clicked.connect(self._on_set_cutoff)
        cutoff_layout.addWidget(self.set_cutoff_btn)
        control_layout.addLayout(cutoff_layout)

        # Separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setFrameShadow(QFrame.Sunken)
        control_layout.addWidget(line3)

        # Discharge time (hours and minutes)
        discharge_layout = QHBoxLayout()
        self.time_limit_label = QLabel("Time Limit")
        discharge_layout.addWidget(self.time_limit_label)

        self.discharge_hours_spin = QSpinBox()
        self.discharge_hours_spin.setRange(0, 99)
        self.discharge_hours_spin.setSingleStep(1)
        self.discharge_hours_spin.setValue(0)
        self.discharge_hours_spin.setSuffix("h")
        self.discharge_hours_spin.setToolTip("Time limit hours (0-99) - load turns off after this duration")
        self.discharge_hours_spin.setEnabled(False)
        self.discharge_hours_spin.setMaximumWidth(55)
        self.discharge_hours_spin.valueChanged.connect(self._on_time_limit_value_changed)
        discharge_layout.addWidget(self.discharge_hours_spin)

        self.discharge_mins_spin = QSpinBox()
        self.discharge_mins_spin.setRange(0, 59)
        self.discharge_mins_spin.setSingleStep(1)
        self.discharge_mins_spin.setValue(0)
        self.discharge_mins_spin.setSuffix("m")
        self.discharge_mins_spin.setToolTip("Time limit minutes (0-59) - load turns off after this duration")
        self.discharge_mins_spin.setEnabled(False)
        self.discharge_mins_spin.setMaximumWidth(55)
        self.discharge_mins_spin.valueChanged.connect(self._on_time_limit_value_changed)
        discharge_layout.addWidget(self.discharge_mins_spin)

        self.set_discharge_btn = QPushButton("Set")
        self.set_discharge_btn.setMaximumWidth(50)
        self.set_discharge_btn.setEnabled(False)
        self.set_discharge_btn.setToolTip("Apply time limit setting to device")
        self.set_discharge_btn.clicked.connect(self._on_set_discharge_time)
        discharge_layout.addWidget(self.set_discharge_btn)
        control_layout.addLayout(discharge_layout)

        layout.addWidget(self.control_group)

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

    @property
    def debug_logging_enabled(self) -> bool:
        """Check if debug logging is enabled."""
        return self.debug_log_checkbox.isChecked()

    def set_connected(self, connected: bool) -> None:
        """Update UI for connection state."""
        self._connected = connected

        self.port_combo.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        self.usb_hid_radio.setEnabled(not connected)
        # bt_radio stays disabled - Bluetooth protocol not yet supported
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)

        # Load Control group title
        if connected:
            self.control_group.setStyleSheet("")
        else:
            self.control_group.setStyleSheet("QGroupBox { color: gray; }")

        # Load on/off controls
        self.load_label.setEnabled(connected)
        self.power_switch.setEnabled(connected)
        self.power_label_off.setEnabled(connected)
        self.power_label_on.setEnabled(connected)

        # Mode buttons
        self.cc_btn.setEnabled(connected)
        self.cv_btn.setEnabled(connected)
        self.cp_btn.setEnabled(connected)
        self.cr_btn.setEnabled(connected)

        # Mode-specific controls will be enabled by _update_mode_controls()
        # Initialize all labels and controls to disabled, then enable based on current mode
        self.current_label.setEnabled(False)
        self.current_spin.setEnabled(False)
        self.set_current_btn.setEnabled(False)
        for i in range(self.preset_btns.count()):
            widget = self.preset_btns.itemAt(i).widget()
            if widget:
                widget.setEnabled(False)
        self.power_label.setEnabled(False)
        self.power_spin.setEnabled(False)
        self.set_power_btn.setEnabled(False)
        self.voltage_label.setEnabled(False)
        self.voltage_spin.setEnabled(False)
        self.set_voltage_btn.setEnabled(False)
        self.resistance_label.setEnabled(False)
        self.resistance_spin.setEnabled(False)
        self.set_resistance_btn.setEnabled(False)

        # Voltage cutoff
        is_usb_hid = self._connection_type == ConnectionType.USB_HID
        self.cutoff_label.setEnabled(connected)
        self.cutoff_spin.setEnabled(connected)
        self.set_cutoff_btn.setEnabled(connected)
        self.set_cutoff_btn.setToolTip("")

        # Discharge time (USB HID only)
        self.time_limit_label.setEnabled(connected and is_usb_hid)
        self.discharge_hours_spin.setEnabled(connected and is_usb_hid)
        self.discharge_mins_spin.setEnabled(connected and is_usb_hid)
        self.set_discharge_btn.setEnabled(connected and is_usb_hid)

        # Update mode-specific controls (enables current/power/voltage/resistance based on mode)
        if connected:
            self._update_mode_controls()

        if not connected:
            self.power_switch.setChecked(False)
            self._update_power_labels(False)
            # Reset to CC mode when disconnected
            self._current_mode = 0
            self.cc_btn.setChecked(True)
            # Reset communication indicator
            self.comm_indicator.setStyleSheet("color: #555555; font-size: 16px;")
            self._comm_fade_timer.stop()

    def pulse_comm_indicator(self) -> None:
        """Pulse the communication indicator green to show data received."""
        self.comm_indicator.setStyleSheet("color: #00FF00; font-size: 16px;")
        self._comm_fade_timer.start(500)  # Fade after 500ms

    def _fade_comm_indicator(self) -> None:
        """Fade the communication indicator back to grey."""
        self.comm_indicator.setStyleSheet("color: #555555; font-size: 16px;")

    def update_status(self, status: DeviceStatus) -> None:
        """Update UI with device status."""
        # Sync toggle switch with actual device load state
        if status.load_on != self.power_switch.isChecked():
            self.power_switch.setChecked(status.load_on)
            self._update_power_labels(status.load_on)

        # Detect load turning on - always sync values when this happens
        load_just_turned_on = status.load_on and not self._last_load_on

        # Sync mode from device
        # Device mode: 0=CC, 1=CV, 2=CR, 3=CP
        # GUI mode: 0=CC, 1=CP, 2=CV, 3=CR
        # Map device mode to the correct button
        if status.mode is not None:
            device_mode_to_button = {
                0: self.cc_btn,  # CC
                1: self.cv_btn,  # CV
                2: self.cr_btn,  # CR
                3: self.cp_btn,  # CP
            }
            btn = device_mode_to_button.get(status.mode)
            if btn and not btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
                # Update internal mode to match GUI button ID
                self._current_mode = self.mode_btn_group.id(btn)
                self._update_mode_controls()

        # Sync value for current mode from device
        # Device mode: 0=CC, 1=CV, 2=CR, 3=CP
        if status.value_set is not None and status.mode is not None:
            value = status.value_set
            device_mode = status.mode

            if device_mode == 0:  # CC mode - sync current
                if load_just_turned_on or not self._current_user_editing:
                    current_val = round(value, 3)
                    if abs(self.current_spin.value() - current_val) > 0.001:
                        self.current_spin.blockSignals(True)
                        self.current_spin.setValue(current_val)
                        self.current_spin.blockSignals(False)
            elif device_mode == 3:  # CP mode - sync power
                if load_just_turned_on or not self._power_user_editing:
                    power_val = round(value, 2)
                    if abs(self.power_spin.value() - power_val) > 0.01:
                        self.power_spin.blockSignals(True)
                        self.power_spin.setValue(power_val)
                        self.power_spin.blockSignals(False)
            elif device_mode == 1:  # CV mode - sync voltage
                if load_just_turned_on or not self._voltage_user_editing:
                    voltage_val = round(value, 2)
                    if abs(self.voltage_spin.value() - voltage_val) > 0.01:
                        self.voltage_spin.blockSignals(True)
                        self.voltage_spin.setValue(voltage_val)
                        self.voltage_spin.blockSignals(False)
            elif device_mode == 2:  # CR mode - sync resistance
                if load_just_turned_on or not self._resistance_user_editing:
                    resistance_val = round(value, 2)
                    if abs(self.resistance_spin.value() - resistance_val) > 0.01:
                        self.resistance_spin.blockSignals(True)
                        self.resistance_spin.setValue(resistance_val)
                        self.resistance_spin.blockSignals(False)

        # Track load state for next update
        self._last_load_on = status.load_on

        # Voltage cutoff setting sync (same logic as current)
        if status.voltage_cutoff is not None:
            # Sync if: load just turned on, OR user is not editing
            if load_just_turned_on or not self._cutoff_user_editing:
                cutoff_val = round(status.voltage_cutoff, 2)
                if abs(self.cutoff_spin.value() - cutoff_val) > 0.01:
                    self.cutoff_spin.blockSignals(True)
                    self.cutoff_spin.setValue(cutoff_val)
                    self.cutoff_spin.blockSignals(False)

        # Time limit setting sync - DISABLED for debugging
        # The values at offsets 49-50 may be incorrect, causing constant overwrites
        # TODO: Re-enable once correct offsets are found
        # if status.time_limit_hours is not None and status.time_limit_minutes is not None:
        #     if load_just_turned_on or not self._time_limit_user_editing:
        #         if self.discharge_hours_spin.value() != status.time_limit_hours:
        #             self.discharge_hours_spin.blockSignals(True)
        #             self.discharge_hours_spin.setValue(status.time_limit_hours)
        #             self.discharge_hours_spin.blockSignals(False)
        #         if self.discharge_mins_spin.value() != status.time_limit_minutes:
        #             self.discharge_mins_spin.blockSignals(True)
        #             self.discharge_mins_spin.setValue(status.time_limit_minutes)
        #             self.discharge_mins_spin.blockSignals(False)
        pass

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

        dl24_index = -1  # Track first port with "DL24" in name

        if self._connection_type == ConnectionType.USB_HID:
            # List USB HID devices
            if USBHIDDevice.is_available():
                devices = USBHIDDevice.list_devices()
                for dev in devices:
                    label = dev['product']
                    if dev.get('serial'):
                        label += f" ({dev['serial']})"
                    self.port_combo.addItem(label, dev['path'])

                    # Check for DL24 in product name (first match wins)
                    if dl24_index < 0 and "DL24" in label.upper():
                        dl24_index = self.port_combo.count() - 1

                if not devices:
                    self.port_combo.addItem("No USB HID devices found", "")

                # Auto-select: prefer DL24, otherwise first device
                if dl24_index >= 0:
                    self.port_combo.setCurrentIndex(dl24_index)
                elif self.port_combo.count() > 0:
                    self.port_combo.setCurrentIndex(0)
            else:
                self.port_combo.addItem("hidapi not installed", "")
        else:
            # List serial ports (Bluetooth)
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
                label = port
                if port in dl24p_ports:
                    label += " (DL24P?)"

                self.port_combo.addItem(label, port)

                # Check for DL24 in port name or description (first match wins)
                if dl24_index < 0 and ("DL24" in port.upper() or "DL24" in desc.upper()):
                    dl24_index = self.port_combo.count() - 1

            # Auto-select: prefer DL24, then DL24P USB ports, otherwise first
            if dl24_index >= 0:
                self.port_combo.setCurrentIndex(dl24_index)
            elif dl24p_ports:
                # Find first DL24P port in combo
                for i in range(self.port_combo.count()):
                    if self.port_combo.itemData(i) in dl24p_ports:
                        self.port_combo.setCurrentIndex(i)
                        break
            elif self.port_combo.count() > 0:
                self.port_combo.setCurrentIndex(0)

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

    @Slot()
    def _on_current_value_changed(self) -> None:
        """Handle user changing the current spinbox value."""
        # Mark as user editing and start/restart the timeout timer
        self._current_user_editing = True
        self._current_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_current_edit_timeout(self) -> None:
        """Resume current syncing after user stops editing."""
        self._current_user_editing = False

    @Slot()
    def _on_set_current(self) -> None:
        """Set the load current."""
        current = self.current_spin.value()
        self.device.set_current(current)
        # Stop editing mode - allow immediate sync of confirmed value
        self._current_user_editing = False
        self._current_edit_timer.stop()

    def _set_current_preset(self, current: float) -> None:
        """Set current from preset button."""
        self.current_spin.blockSignals(True)  # Don't trigger edit mode
        self.current_spin.setValue(current)
        self.current_spin.blockSignals(False)
        self.device.set_current(current)
        # Stop editing mode - allow immediate sync
        self._current_user_editing = False
        self._current_edit_timer.stop()

    @Slot()
    def _on_cutoff_value_changed(self) -> None:
        """Handle user changing the voltage cutoff spinbox value."""
        self._cutoff_user_editing = True
        self._cutoff_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_cutoff_edit_timeout(self) -> None:
        """Resume voltage cutoff syncing after user stops editing."""
        self._cutoff_user_editing = False

    @Slot()
    def _on_set_cutoff(self) -> None:
        """Set voltage cutoff."""
        voltage = self.cutoff_spin.value()
        self.device.set_voltage_cutoff(voltage)
        # Stop editing mode - allow immediate sync of confirmed value
        self._cutoff_user_editing = False
        self._cutoff_edit_timer.stop()

    @Slot()
    def _on_time_limit_value_changed(self) -> None:
        """Handle user changing the time limit spinbox values."""
        hours = self.discharge_hours_spin.value()
        minutes = self.discharge_mins_spin.value()
        self.device._debug("INFO", f"Time limit spinbox changed: {hours}h {minutes}m")
        self._time_limit_user_editing = True
        self._time_limit_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_time_limit_edit_timeout(self) -> None:
        """Resume time limit syncing after user stops editing."""
        self._time_limit_user_editing = False

    @Slot()
    def _on_set_discharge_time(self) -> None:
        """Set discharge time limit."""
        hours = self.discharge_hours_spin.value()
        minutes = self.discharge_mins_spin.value()
        self.device.set_discharge_time(hours, minutes)
        # Stop editing mode - allow immediate sync of confirmed value
        self._time_limit_user_editing = False
        self._time_limit_edit_timer.stop()

    @Slot(int)
    def _on_mode_changed(self, button_id: int) -> None:
        """Handle mode button change."""
        # GUI button IDs: 0=CC, 1=CP, 2=CV, 3=CR
        self._current_mode = button_id
        self._update_mode_controls()

        # Get the current value for the selected mode
        mode_values = {
            0: self.current_spin.value(),      # CC - current
            1: self.power_spin.value(),        # CP - power
            2: self.voltage_spin.value(),      # CV - voltage
            3: self.resistance_spin.value(),   # CR - resistance
        }
        value = mode_values.get(button_id)

        # Send mode change to device (device.set_mode handles the subcmd mapping)
        if hasattr(self.device, 'set_mode'):
            self.device.set_mode(button_id, value)

    def _update_mode_controls(self) -> None:
        """Enable/disable setting controls based on current mode."""
        if not self._connected:
            return

        mode = self._current_mode
        # CC=0: Current enabled
        # CP=1: Power enabled
        # CV=2: Voltage enabled
        # CR=3: Resistance enabled

        self.current_label.setEnabled(mode == 0)
        self.current_spin.setEnabled(mode == 0)
        self.set_current_btn.setEnabled(mode == 0)
        for i in range(self.preset_btns.count()):
            widget = self.preset_btns.itemAt(i).widget()
            if widget:
                widget.setEnabled(mode == 0)

        self.power_label.setEnabled(mode == 1)
        self.power_spin.setEnabled(mode == 1)
        self.set_power_btn.setEnabled(mode == 1)

        self.voltage_label.setEnabled(mode == 2)
        self.voltage_spin.setEnabled(mode == 2)
        self.set_voltage_btn.setEnabled(mode == 2)

        self.resistance_label.setEnabled(mode == 3)
        self.resistance_spin.setEnabled(mode == 3)
        self.set_resistance_btn.setEnabled(mode == 3)

    @Slot()
    def _on_power_value_changed(self) -> None:
        """Handle user changing the power spinbox value."""
        self._power_user_editing = True
        self._power_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_power_edit_timeout(self) -> None:
        """Resume power syncing after user stops editing."""
        self._power_user_editing = False

    @Slot()
    def _on_set_power(self) -> None:
        """Set the load power (CP mode)."""
        power = self.power_spin.value()
        if hasattr(self.device, 'set_power'):
            self.device.set_power(power)
        # Stop editing mode - allow immediate sync of confirmed value
        self._power_user_editing = False
        self._power_edit_timer.stop()

    @Slot()
    def _on_voltage_value_changed(self) -> None:
        """Handle user changing the voltage spinbox value."""
        self._voltage_user_editing = True
        self._voltage_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_voltage_edit_timeout(self) -> None:
        """Resume voltage syncing after user stops editing."""
        self._voltage_user_editing = False

    @Slot()
    def _on_set_voltage(self) -> None:
        """Set the load voltage (CV mode)."""
        voltage = self.voltage_spin.value()
        if hasattr(self.device, 'set_voltage'):
            self.device.set_voltage(voltage)
        # Stop editing mode - allow immediate sync of confirmed value
        self._voltage_user_editing = False
        self._voltage_edit_timer.stop()

    @Slot()
    def _on_resistance_value_changed(self) -> None:
        """Handle user changing the resistance spinbox value."""
        self._resistance_user_editing = True
        self._resistance_edit_timer.start(3000)  # 3 second timeout

    @Slot()
    def _on_resistance_edit_timeout(self) -> None:
        """Resume resistance syncing after user stops editing."""
        self._resistance_user_editing = False

    @Slot()
    def _on_set_resistance(self) -> None:
        """Set the load resistance (CR mode)."""
        resistance = self.resistance_spin.value()
        if hasattr(self.device, 'set_resistance'):
            self.device.set_resistance(resistance)
        # Stop editing mode - allow immediate sync of confirmed value
        self._resistance_user_editing = False
        self._resistance_edit_timer.stop()

