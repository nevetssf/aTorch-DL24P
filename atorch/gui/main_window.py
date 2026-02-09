"""Main application window."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMenuBar,
    QMenu,
    QStatusBar,
    QMessageBox,
    QFileDialog,
    QTabWidget,
    QLabel,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent

from ..protocol.device import Device, USBHIDDevice, DeviceError
from ..protocol.atorch_protocol import DeviceStatus
from .control_panel import ConnectionType
from ..data.database import Database
from ..data.models import TestSession, Reading
from ..data.export import export_csv, export_json, export_excel
from ..automation.test_runner import TestRunner, TestProgress
from ..alerts.notifier import Notifier
from ..alerts.conditions import (
    VoltageAlert,
    TemperatureAlert,
    TestCompleteAlert,
)

from .control_panel import ControlPanel
from .plot_panel import PlotPanel
from .status_panel import StatusPanel
from .automation_panel import AutomationPanel
from .history_panel import HistoryPanel
from .settings_dialog import SettingsDialog, DeviceSettingsDialog
from .debug_window import DebugWindow
from .placeholder_panel import BatteryChargerPanel, CableResistancePanel, ChargerPanel


class MainWindow(QMainWindow):
    """Main application window for DL24P control."""

    status_updated = Signal(DeviceStatus)
    connection_changed = Signal(bool)
    test_progress = Signal(TestProgress)
    debug_message = Signal(str, str, bytes)  # event_type, message, data
    error_occurred = Signal(str)  # error message

    DEBUG_LOG_FILE = "/Users/steve/Projects/atorch/debug.log"

    def __init__(self):
        super().__init__()

        self.setWindowTitle("aTorch DL24P Control")
        self.setMinimumSize(1200, 800)

        # Clear debug log file on startup
        with open(self.DEBUG_LOG_FILE, 'w') as f:
            f.write(f"=== Debug log started {datetime.now().isoformat()} ===\n")

        # Core components
        self.device = None  # Created on connect based on type
        self._serial_device = Device()  # Serial device instance
        self._hid_device = USBHIDDevice() if USBHIDDevice.is_available() else None
        self.database = Database()
        self.test_runner = None  # Created after device selection
        self.notifier = Notifier()

        # Debug window
        self.debug_window = DebugWindow(self)
        self.debug_message.connect(self._on_debug_message)
        self.debug_window.send_raw_command.connect(self._send_raw_command)

        # Current session for manual logging
        self._current_session: Optional[TestSession] = None
        self._last_completed_session: Optional[TestSession] = None  # Keep last session for export
        self._logging_enabled = False
        self._logging_start_time: Optional[datetime] = None  # Track when logging started
        self._accumulated_readings: list[Reading] = []  # Readings accumulated across sessions
        self._prev_load_on = False  # Track previous load state for cutoff detection

        # Setup
        self._setup_alerts()
        self._setup_callbacks()
        self._create_ui()
        self._create_menus()
        self._create_statusbar()

        # Update timer
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._on_timer)
        self._update_timer.start(100)  # 10 Hz UI updates

    def _setup_alerts(self) -> None:
        """Configure default alert conditions."""
        self.notifier.add_condition(TemperatureAlert(threshold=70))
        self.notifier.add_condition(TestCompleteAlert())

    def _setup_callbacks(self) -> None:
        """Setup device callbacks (called when device is created)."""
        # Callbacks are set when connecting to a device
        pass

    def _setup_device_callbacks(self, device) -> None:
        """Setup callbacks for a specific device."""
        device.set_status_callback(self._on_device_status)
        device.set_error_callback(self._on_device_error)
        device.set_debug_callback(self._on_device_debug)

    def _create_ui(self) -> None:
        """Create the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Main content splitter (horizontal)
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Controls (use serial device as placeholder, actual device set on connect)
        self.control_panel = ControlPanel(self._serial_device, None)
        self.control_panel.setMaximumWidth(300)
        splitter.addWidget(self.control_panel)

        # Center: Plots
        self.plot_panel = PlotPanel()
        splitter.addWidget(self.plot_panel)

        # Right panel: Status
        self.status_panel = StatusPanel()
        self.status_panel.setMaximumWidth(250)
        splitter.addWidget(self.status_panel)

        splitter.setSizes([250, 700, 250])
        from PySide6.QtWidgets import QSizePolicy
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(splitter, stretch=1)

        # Bottom section: Collapsible Test Automation with tabs
        from PySide6.QtWidgets import QToolButton, QFrame

        # Header with collapse toggle
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self.automation_toggle = QToolButton()
        self.automation_toggle.setArrowType(Qt.DownArrow)
        self.automation_toggle.setCheckable(True)
        self.automation_toggle.setChecked(True)
        self.automation_toggle.setStyleSheet("QToolButton { border: none; }")
        self.automation_toggle.clicked.connect(self._toggle_automation_panel)
        header_layout.addWidget(self.automation_toggle)

        automation_label = QLabel("Test Automation")
        automation_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(automation_label)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # Content frame for tabs
        self.automation_content = QFrame()
        automation_content_layout = QVBoxLayout(self.automation_content)
        automation_content_layout.setContentsMargins(0, 4, 0, 0)

        self.bottom_tabs = QTabWidget()

        self.automation_panel = AutomationPanel(None, self.database)  # test_runner set on connect
        self.bottom_tabs.addTab(self.automation_panel, "Battery Capacity")

        self.battery_charger_panel = BatteryChargerPanel()
        self.bottom_tabs.addTab(self.battery_charger_panel, "Battery Charger")

        self.cable_resistance_panel = CableResistancePanel()
        self.bottom_tabs.addTab(self.cable_resistance_panel, "Cable Resistance")

        self.charger_panel = ChargerPanel()
        self.bottom_tabs.addTab(self.charger_panel, "Charger")

        self.history_panel = HistoryPanel(self.database)
        self.history_panel.session_selected.connect(self._on_history_session_selected)
        self.bottom_tabs.addTab(self.history_panel, "History")

        # Connect automation panel signals
        self.automation_panel.start_test_requested.connect(self._on_automation_start)
        self.automation_panel.pause_test_requested.connect(self._on_automation_pause)
        self.automation_panel.resume_test_requested.connect(self._on_automation_resume)
        self.automation_panel.apply_settings_requested.connect(self._on_apply_settings)
        self.automation_panel.manual_save_requested.connect(self._on_manual_save)
        self.automation_panel.session_loaded.connect(self._on_session_loaded)
        self.automation_panel.export_csv_requested.connect(self._on_export_csv)

        automation_content_layout.addWidget(self.bottom_tabs)
        self.automation_content.setFixedHeight(380)
        self.automation_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        main_layout.addWidget(self.automation_content, stretch=0)

        # Connect signals
        self.status_updated.connect(self._update_ui_status)
        self.connection_changed.connect(self._update_ui_connection)
        self.test_progress.connect(self.automation_panel.update_progress)
        self.error_occurred.connect(self._show_error_message)

        # Connect control panel signals
        self.control_panel.connect_requested.connect(self._connect_device)
        self.control_panel.disconnect_requested.connect(self._disconnect_device)
        self.status_panel.logging_toggled.connect(self._toggle_logging)
        self.status_panel.show_points_toggled.connect(self._toggle_show_points)
        self.status_panel.clear_requested.connect(self._clear_data)
        self.status_panel.save_requested.connect(self._export_session_with_name)

    def _create_menus(self) -> None:
        """Create application menus."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        export_action = QAction("&Export Current Session...", self)
        export_action.triggered.connect(self._export_session)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        settings_action = QAction("&Settings...", self)
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Device menu
        device_menu = menubar.addMenu("&Device")

        self.connect_action = QAction("&Connect", self)
        self.connect_action.triggered.connect(self._connect_device)
        device_menu.addAction(self.connect_action)

        self.disconnect_action = QAction("&Disconnect", self)
        self.disconnect_action.setEnabled(False)  # Disabled when not connected
        self.disconnect_action.triggered.connect(self._disconnect_device)
        device_menu.addAction(self.disconnect_action)

        device_menu.addSeparator()

        self.reset_action = QAction("&Reset Counters", self)
        self.reset_action.setEnabled(False)  # Disabled when not connected
        self.reset_action.triggered.connect(self._reset_counters)
        device_menu.addAction(self.reset_action)

        device_menu.addSeparator()

        self.device_settings_action = QAction("S&ettings", self)
        self.device_settings_action.setMenuRole(QAction.NoRole)  # Prevent macOS from moving to app menu
        self.device_settings_action.setEnabled(False)  # Disabled when not connected
        self.device_settings_action.triggered.connect(self._show_device_settings)
        device_menu.addAction(self.device_settings_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        clear_plots_action = QAction("&Clear Plots", self)
        clear_plots_action.triggered.connect(self.plot_panel.clear_data)
        view_menu.addAction(clear_plots_action)

        view_menu.addSeparator()

        debug_action = QAction("&Debug Console", self)
        debug_action.triggered.connect(self._show_debug_window)
        view_menu.addAction(debug_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_statusbar(self) -> None:
        """Create status bar."""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Disconnected")

    @Slot()
    @Slot(str)
    def _connect_device(self, connection_type = None) -> None:
        """Connect to the DL24P device."""
        try:
            port = self.control_panel.selected_port
            if not port:
                QMessageBox.warning(self, "Connection Error", "No device selected")
                return

            # Determine which device to use based on connection type
            # Handle case where triggered signal passes bool instead of connection type
            if connection_type is None or isinstance(connection_type, bool):
                connection_type = self.control_panel.connection_type

            if connection_type == ConnectionType.USB_HID:
                if self._hid_device is None:
                    QMessageBox.warning(
                        self, "Connection Error",
                        "USB HID support not available. Install hidapi: pip install hidapi"
                    )
                    return
                self.device = self._hid_device
            else:
                self.device = self._serial_device

            # Setup callbacks for this device
            self._setup_device_callbacks(self.device)

            # Update control panel's device reference
            self.control_panel.device = self.device

            # Connect
            self.device.connect(port)

            # Create/update test runner with connected device
            self.test_runner = TestRunner(self.device, self.database)
            self.test_runner.set_progress_callback(self._on_test_progress)
            self.test_runner.set_complete_callback(self._on_test_complete)
            self.control_panel.test_runner = self.test_runner
            self.automation_panel.test_runner = self.test_runner

            self.connection_changed.emit(True)
            conn_type_str = "USB HID" if connection_type == ConnectionType.USB_HID else "Serial"
            self.statusbar.showMessage(f"Connected ({conn_type_str}): {self.device.port}")
        except DeviceError as e:
            QMessageBox.warning(self, "Connection Error", str(e))

    @Slot()
    def _disconnect_device(self) -> None:
        """Disconnect from the device."""
        # Turn off the load first
        if self.device and self.device.is_connected:
            self.device.turn_off()
            self.control_panel.power_switch.setChecked(False)
            self.control_panel._update_power_labels(False)

        # Stop logging if active
        if self._logging_enabled:
            self.status_panel.log_switch.setChecked(False)
            self._toggle_logging(False)

        # Stop the test (update automation panel UI)
        self.automation_panel._update_ui_stopped()

        # Disconnect
        if self.device:
            self.device.disconnect()
        self.connection_changed.emit(False)
        self.statusbar.showMessage("Disconnected")

    @Slot(bool)
    def _toggle_logging(self, enabled: bool) -> None:
        """Toggle manual data logging."""
        if enabled and not self._current_session:
            # Start new session
            self._logging_start_time = datetime.now()
            self._current_session = TestSession(
                name=f"Manual Log {self._logging_start_time.strftime('%Y-%m-%d %H:%M')}",
                start_time=self._logging_start_time,
                test_type="manual",
            )
            self.database.create_session(self._current_session)
            self._logging_enabled = True
            # Turn on the load when logging starts
            if self.device and self.device.is_connected:
                self.device.turn_on()
                self.control_panel.power_switch.setChecked(True)
            self.statusbar.showMessage("Logging started")
        elif not enabled and self._current_session:
            # End session
            self._current_session.end_time = datetime.now()
            self.database.update_session(self._current_session)
            num_readings = len(self._current_session.readings)
            self.statusbar.showMessage(
                f"Logged {num_readings} readings - click 'Save Data...' to export"
            )
            # Keep reference to last session for export
            self._last_completed_session = self._current_session
            self._current_session = None
            self._logging_enabled = False
            self._logging_start_time = None
            # Turn off the load when logging stops
            if self.device and self.device.is_connected:
                self.device.turn_off()
                self.control_panel.power_switch.setChecked(False)

    @Slot(bool)
    def _toggle_show_points(self, show: bool) -> None:
        """Toggle visibility of point markers on plot curves."""
        self.plot_panel.set_show_points(show)

    @Slot()
    def _clear_data(self) -> None:
        """Clear accumulated data - turns off load, resets device counters, and clears plots."""
        if self.device and self.device.is_connected:
            # Turn off the load
            self.device.turn_off()
            self.control_panel.power_switch.setChecked(False)
            # Reset device counters (mAh, Wh, time)
            self.device.reset_counters()
        # Clear plot data, logging time, points count, and accumulated readings
        self.plot_panel.clear_data()
        self.status_panel.clear_logging_time()
        self.status_panel.set_points_count(0)
        self._accumulated_readings.clear()
        self.statusbar.showMessage("Values cleared")

    @Slot()
    def _reset_counters(self) -> None:
        """Reset device counters."""
        if self.device and self.device.is_connected:
            self.device.reset_counters()
            self.statusbar.showMessage("Counters reset")

    @Slot()
    def _export_session(self) -> None:
        """Export current or selected session (from menu)."""
        self._export_session_with_name("")

    @Slot(str)
    def _export_session_with_name(self, battery_name: str = "") -> None:
        """Export current or selected session with optional battery name."""
        # Use accumulated readings if available (from Data Logging panel Save button)
        if self._accumulated_readings:
            # Create a session with all accumulated readings for export
            first_reading = self._accumulated_readings[0]
            session = TestSession(
                name=battery_name or "Accumulated Data",
                start_time=first_reading.timestamp,
                test_type="manual",
            )
            session.readings = self._accumulated_readings.copy()
        else:
            session = self._current_session
            if not session:
                # Try the last completed session (from a finished test)
                session = self._last_completed_session
            if not session:
                # Try to get selected from history
                session = self.history_panel.selected_session
        if not session:
            QMessageBox.information(
                self,
                "No Session",
                "No session to export. Start logging or select a session from history.",
            )
            return

        # Generate filename based on battery name and session start time
        if session.start_time:
            timestamp = session.start_time.strftime("%Y%m%d_%H%M%S")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if battery_name:
            default_name = f"{battery_name}_{timestamp}"
        else:
            default_name = f"discharge_{timestamp}"

        path, filter = QFileDialog.getSaveFileName(
            self,
            "Export Session",
            f"{default_name}.csv",
            "CSV (*.csv);;JSON (*.json);;Excel (*.xlsx)",
        )

        if not path:
            return

        try:
            if path.endswith(".json"):
                export_json(session, path)
            elif path.endswith(".xlsx"):
                export_excel(session, path)
            else:
                export_csv(session, path)
            self.statusbar.showMessage(f"Exported to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def _save_test_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save test data to JSON file.

        Saves test configuration, battery info, and all logged readings.

        Args:
            filename: Optional filename to use. If None, uses the filename from automation panel.

        Returns:
            Path to saved file, or None if save failed
        """
        # Get test configuration and battery info from automation panel
        test_config = self.automation_panel.get_test_config()
        battery_info = self.automation_panel.get_battery_info()

        # Use provided filename or get from automation panel
        if filename is None:
            filename = self.automation_panel.filename_edit.text().strip()
            if not filename:
                filename = self.automation_panel.generate_test_filename()
        # Ensure .json extension
        if not filename.endswith('.json'):
            filename += '.json'

        # Create output directory if needed
        output_dir = Path.home() / ".atorch" / "test_data"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # Build test data structure
        readings_data = []
        for reading in self._accumulated_readings:
            readings_data.append({
                "timestamp": reading.timestamp.isoformat(),
                "voltage": reading.voltage,
                "current": reading.current,
                "power": reading.power,
                "energy_wh": reading.energy_wh,
                "capacity_mah": reading.capacity_mah,
                "temperature_c": reading.temperature_c,
                "ext_temperature_c": reading.ext_temperature_c,
                "runtime_seconds": reading.runtime_seconds,
            })

        # Calculate summary statistics
        if readings_data:
            final_reading = readings_data[-1]
            first_reading = readings_data[0]
            summary = {
                "total_readings": len(readings_data),
                "start_time": first_reading["timestamp"],
                "end_time": final_reading["timestamp"],
                "final_voltage": final_reading["voltage"],
                "final_capacity_mah": final_reading["capacity_mah"],
                "final_energy_wh": final_reading["energy_wh"],
                "total_runtime_seconds": final_reading["runtime_seconds"],
            }
        else:
            summary = {
                "total_readings": 0,
            }

        test_data = {
            "test_config": test_config,
            "battery_info": battery_info,
            "summary": summary,
            "readings": readings_data,
        }

        try:
            with open(output_path, 'w') as f:
                json.dump(test_data, f, indent=2)
            return str(output_path)
        except Exception as e:
            self.statusbar.showMessage(f"Failed to save test data: {e}")
            return None

    @Slot()
    def _show_settings(self) -> None:
        """Show settings dialog."""
        dialog = SettingsDialog(self.notifier, self)
        dialog.exec()

    @Slot()
    def _show_device_settings(self) -> None:
        """Show device settings dialog."""
        dialog = DeviceSettingsDialog(self.device, self)
        dialog.exec()

    @Slot()
    def _show_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About aTorch DL24P Control",
            "aTorch DL24P Control & Logging Application\n\n"
            "Version 0.1.0\n\n"
            "Control your aTorch DL24P electronic load and log battery discharge data.",
        )

    @Slot(TestSession)
    def _on_history_session_selected(self, session: TestSession) -> None:
        """Handle session selection from history."""
        # Load readings if not already loaded
        if not session.readings:
            session.readings = self.database.get_readings(session.id)

        # Display on plot
        self.plot_panel.load_session(session)
        self.statusbar.showMessage(
            f"Loaded: {session.name} ({len(session.readings)} readings)"
        )

    @Slot(int, float, float, int)
    def _on_automation_start(self, discharge_type: int, value: float, voltage_cutoff: float, duration_s: int) -> None:
        """Handle test start request from automation panel.

        Args:
            discharge_type: 0=CC, 1=CP, 2=CR
            value: Current (A), Power (W), or Resistance (Ω) depending on type
            voltage_cutoff: Voltage cutoff in V
            duration_s: Duration in seconds (0 for no limit)
        """
        if discharge_type == 0 and value == 0 and voltage_cutoff == 0:
            # Stop request - save data and turn off logging
            if self._logging_enabled:
                num_readings = len(self._accumulated_readings)
                # Save test data to JSON if auto-save is enabled
                if self.automation_panel.autosave_checkbox.isChecked():
                    saved_path = self._save_test_json()
                    if saved_path:
                        self.statusbar.showMessage(
                            f"Test aborted: {num_readings} readings saved to {saved_path}"
                        )
                else:
                    self.statusbar.showMessage(
                        f"Test aborted: {num_readings} readings - click Save to export"
                    )
                self.status_panel.log_switch.setChecked(False)
                self._toggle_logging(False)
            return

        if not self.device or not self.device.is_connected:
            return

        # Clear data and previous session before starting new test
        self._clear_data()
        self._last_completed_session = None

        # Clear device counters (mAh, Wh, time)
        self.device.reset_counters()

        # Set mode and value based on discharge type
        mode_names = ["CC", "CP", "CR"]
        if discharge_type == 0:  # Constant Current
            self.control_panel.mode_btn_group.button(0).setChecked(True)  # CC button
            self.control_panel.current_spin.setValue(value)
            self.device.set_current(value)
            mode_str = f"{value}A"
        elif discharge_type == 1:  # Constant Power
            self.control_panel.mode_btn_group.button(1).setChecked(True)  # CP button
            self.control_panel.power_spin.setValue(value)
            self.device.set_power(value)
            mode_str = f"{value}W"
        elif discharge_type == 2:  # Constant Resistance
            self.control_panel.mode_btn_group.button(3).setChecked(True)  # CR button
            self.control_panel.resistance_spin.setValue(value)
            self.device.set_resistance(value)
            mode_str = f"{value}Ω"

        # Set voltage cutoff in control panel and device
        self.control_panel.cutoff_spin.setValue(voltage_cutoff)
        self.device.set_voltage_cutoff(voltage_cutoff)

        # Set duration if specified - convert to hours/minutes
        if duration_s > 0:
            hours = duration_s // 3600
            minutes = (duration_s % 3600) // 60
            self.control_panel.discharge_hours_spin.setValue(hours)
            self.control_panel.discharge_mins_spin.setValue(minutes)
            if hasattr(self.device, 'set_discharge_time'):
                self.device.set_discharge_time(hours, minutes)

        # Start logging (which also turns on the load)
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        self.statusbar.showMessage(f"Test started: {mode_names[discharge_type]} {mode_str}, cutoff {voltage_cutoff}V")

    @Slot()
    def _on_automation_pause(self) -> None:
        """Handle pause request from automation panel - stop logging and load, keep data."""
        # Stop logging (but don't clear data)
        if self._logging_enabled:
            self._current_session.end_time = datetime.now()
            self.database.update_session(self._current_session)
            self._current_session = None
            self._logging_enabled = False
            self._logging_start_time = None
            self.status_panel.log_switch.setChecked(False)

        # Turn off load
        if self.device and self.device.is_connected:
            self.device.turn_off()
            self.control_panel.power_switch.setChecked(False)

        self.statusbar.showMessage("Test paused - data preserved")

    @Slot()
    def _on_automation_resume(self) -> None:
        """Handle resume request from automation panel - restart logging and load."""
        # Start logging again (without clearing data)
        if not self._logging_enabled:
            self._logging_start_time = datetime.now()
            self._current_session = TestSession(
                name=f"Manual Log {self._logging_start_time.strftime('%Y-%m-%d %H:%M')}",
                start_time=self._logging_start_time,
                test_type="manual",
            )
            self.database.create_session(self._current_session)
            self._logging_enabled = True
            self.status_panel.log_switch.setChecked(True)

        # Turn on load
        if self.device and self.device.is_connected:
            self.device.turn_on()
            self.control_panel.power_switch.setChecked(True)

        self.statusbar.showMessage("Test resumed")

    @Slot(str)
    def _on_manual_save(self, filename: str) -> None:
        """Handle manual save request from automation panel.

        Args:
            filename: The filename to save as
        """
        if not self._accumulated_readings:
            self.statusbar.showMessage("No data to save")
            return

        saved_path = self._save_test_json(filename)
        if saved_path:
            self.statusbar.showMessage(f"Saved: {saved_path}")

    @Slot(list)
    def _on_session_loaded(self, readings: list) -> None:
        """Handle loaded session data from automation panel.

        Args:
            readings: List of reading dicts from loaded JSON file
        """
        # Clear existing data
        self.plot_panel.clear_data()
        self._accumulated_readings.clear()

        # Get start time from first reading to calculate relative times
        start_time = None
        if readings:
            try:
                start_time = datetime.fromisoformat(readings[0].get("timestamp", ""))
            except Exception:
                pass

        # Convert readings to Reading objects and populate accumulated_readings
        for reading_dict in readings:
            try:
                timestamp = datetime.fromisoformat(reading_dict.get("timestamp", ""))

                # Calculate runtime_seconds from timestamp relative to start
                if start_time:
                    runtime_seconds = (timestamp - start_time).total_seconds()
                else:
                    runtime_seconds = reading_dict.get("runtime_seconds", 0)

                reading = Reading(
                    timestamp=timestamp,
                    voltage=reading_dict.get("voltage", 0),
                    current=reading_dict.get("current", 0),
                    power=reading_dict.get("power", 0),
                    energy_wh=reading_dict.get("energy_wh", 0),
                    capacity_mah=reading_dict.get("capacity_mah", 0),
                    temperature_c=reading_dict.get("temperature_c", 0),
                    ext_temperature_c=reading_dict.get("ext_temperature_c", 0),
                    runtime_seconds=runtime_seconds,
                )
                self._accumulated_readings.append(reading)
            except Exception:
                continue  # Skip invalid readings

        # Load readings into plot panel for display
        if self._accumulated_readings:
            self.plot_panel.load_readings(self._accumulated_readings)
            self.status_panel.set_points_count(len(self._accumulated_readings))
            self.statusbar.showMessage(f"Loaded {len(self._accumulated_readings)} readings")

    @Slot()
    def _on_export_csv(self) -> None:
        """Handle Export CSV button - export accumulated readings to CSV file."""
        if not self._accumulated_readings:
            QMessageBox.warning(self, "Export Error", "No data to export.")
            return

        # Default to test_data directory
        default_dir = str(Path.home() / ".atorch" / "test_data")
        Path(default_dir).mkdir(parents=True, exist_ok=True)

        # Generate default filename from current JSON filename
        json_filename = self.automation_panel.filename_edit.text().strip()
        if json_filename.endswith('.json'):
            default_filename = json_filename[:-5] + '.csv'
        else:
            default_filename = json_filename + '.csv' if json_filename else 'export.csv'

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            str(Path(default_dir) / default_filename),
            "CSV Files (*.csv)"
        )

        if not file_path:
            return

        try:
            # Get battery info from automation panel
            battery_name = self.automation_panel.battery_name_edit.text()
            test_type = self.automation_panel.type_combo.currentText()

            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Write header with metadata as comments
                f.write(f"# Battery: {battery_name}\n")
                f.write(f"# Test Type: {test_type}\n")
                if self._accumulated_readings:
                    f.write(f"# Start: {self._accumulated_readings[0].timestamp.isoformat()}\n")
                    f.write(f"# End: {self._accumulated_readings[-1].timestamp.isoformat()}\n")
                f.write("#\n")

                # Write column headers
                writer.writerow([
                    "timestamp",
                    "runtime_s",
                    "voltage_V",
                    "current_A",
                    "power_W",
                    "energy_Wh",
                    "capacity_mAh",
                    "temp_C",
                    "ext_temp_C",
                ])

                # Write readings
                start_time = self._accumulated_readings[0].timestamp if self._accumulated_readings else None
                for reading in self._accumulated_readings:
                    # Calculate runtime from timestamps
                    if start_time and reading.timestamp:
                        runtime = (reading.timestamp - start_time).total_seconds()
                    else:
                        runtime = reading.runtime_seconds

                    writer.writerow([
                        reading.timestamp.isoformat(),
                        f"{runtime:.1f}",
                        f"{reading.voltage:.3f}",
                        f"{reading.current:.4f}",
                        f"{reading.power:.2f}",
                        f"{reading.energy_wh:.4f}",
                        f"{reading.capacity_mah:.1f}",
                        reading.temperature_c,
                        reading.ext_temperature_c,
                    ])

            self.statusbar.showMessage(f"Exported {len(self._accumulated_readings)} readings to {Path(file_path).name}")

        except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export CSV: {e}")

    @Slot(int, float, float, int)
    def _on_apply_settings(self, discharge_type: int, value: float, voltage_cutoff: float, duration_s: int) -> None:
        """Apply test configuration settings to the device without starting a test.

        Args:
            discharge_type: 0=CC, 1=CP, 2=CR
            value: Current (A), Power (W), or Resistance (Ω) depending on type
            voltage_cutoff: Voltage cutoff in V
            duration_s: Duration in seconds (0 for no limit)
        """
        if not self.device or not self.device.is_connected:
            self.statusbar.showMessage("Cannot apply settings: device not connected")
            return

        mode_names = ["CC", "CP", "CR"]

        # Set mode and value based on discharge type
        # GUI button IDs: 0=CC, 1=CP, 2=CV, 3=CR
        if discharge_type == 0:  # Constant Current
            self.control_panel.mode_btn_group.button(0).setChecked(True)
            self.control_panel.current_spin.setValue(value)
            self.device.set_mode(0, value)  # Set mode with value
            mode_str = f"{value}A"
        elif discharge_type == 1:  # Constant Power
            self.control_panel.mode_btn_group.button(1).setChecked(True)
            self.control_panel.power_spin.setValue(value)
            self.device.set_mode(1, value)  # Set mode with value
            mode_str = f"{value}W"
        elif discharge_type == 2:  # Constant Resistance
            self.control_panel.mode_btn_group.button(3).setChecked(True)
            self.control_panel.resistance_spin.setValue(value)
            self.device.set_mode(3, value)  # Set mode with value
            mode_str = f"{value}Ω"

        # Update mode controls in control panel
        self.control_panel._current_mode = discharge_type if discharge_type < 2 else 3
        self.control_panel._update_mode_controls()

        # Set voltage cutoff
        self.control_panel.cutoff_spin.setValue(voltage_cutoff)
        self.device.set_voltage_cutoff(voltage_cutoff)

        # Set duration (or clear if 0)
        if duration_s > 0:
            hours = duration_s // 3600
            minutes = (duration_s % 3600) // 60
            self.control_panel.discharge_hours_spin.setValue(hours)
            self.control_panel.discharge_mins_spin.setValue(minutes)
            if hasattr(self.device, 'set_discharge_time'):
                self.device.set_discharge_time(hours, minutes)
            time_str = f", time limit {hours}h {minutes}m"
        else:
            self.control_panel.discharge_hours_spin.setValue(0)
            self.control_panel.discharge_mins_spin.setValue(0)
            if hasattr(self.device, 'set_discharge_time'):
                self.device.set_discharge_time(0, 0)
            time_str = ""

        self.statusbar.showMessage(f"Applied: {mode_names[discharge_type]} {mode_str}, cutoff {voltage_cutoff}V{time_str}")

    def _on_device_status(self, status: DeviceStatus) -> None:
        """Handle device status update (called from device thread).

        IMPORTANT: This runs in a background thread - only emit signals here,
        do NOT access GUI elements or perform database operations directly.
        """
        # Emit signal to handle on main thread
        self.status_updated.emit(status)

    def _on_device_error(self, message: str) -> None:
        """Handle device error (called from device thread)."""
        # Emit signal to handle on main thread
        self.error_occurred.emit(message)

    @Slot(str)
    def _show_error_message(self, message: str) -> None:
        """Show error message in status bar (runs on main thread)."""
        self.statusbar.showMessage(f"Error: {message}")

    def _on_test_progress(self, progress: TestProgress) -> None:
        """Handle test progress update."""
        self.test_progress.emit(progress)

    def _on_test_complete(self, session: TestSession) -> None:
        """Handle test completion."""
        self.history_panel.refresh()
        self.statusbar.showMessage(
            f"Test complete: {session.final_capacity_mah:.0f}mAh / {session.final_energy_wh:.2f}Wh"
        )

    @Slot(DeviceStatus)
    def _update_ui_status(self, status: DeviceStatus) -> None:
        """Update UI with device status (runs on main thread via signal)."""
        # Log data first (before UI update) if enabled
        if self._logging_enabled and self._current_session:
            reading = Reading(
                timestamp=datetime.now(),
                voltage=status.voltage,
                current=status.current,
                power=status.power,
                energy_wh=status.energy_wh,
                capacity_mah=status.capacity_mah,
                temperature_c=status.temperature_c,
                ext_temperature_c=status.ext_temperature_c,
                runtime_seconds=status.runtime_seconds,
            )
            self.database.add_reading(self._current_session.id, reading)
            self._current_session.readings.append(reading)
            # Also accumulate for cross-session export
            self._accumulated_readings.append(reading)

        # Check alerts
        self.notifier.check(status)

        # Update test progress bar in automation panel
        if self._logging_enabled:
            elapsed = self.plot_panel.get_elapsed_time()
            self.automation_panel.update_test_progress(elapsed, status.capacity_mah)

        # Pulse communication indicator to show data received
        self.control_panel.pulse_comm_indicator()

        self.status_panel.update_status(status)

        # Detect if load turned off during logging (e.g., voltage cutoff)
        # Check this BEFORE adding data to prevent extra data points
        if self._logging_enabled and self._prev_load_on and not status.load_on:
            # Load turned off while logging - stop logging immediately
            num_readings = len(self._current_session.readings) if self._current_session else 0
            self._logging_enabled = False  # Stop immediately to prevent more data
            self.status_panel.log_switch.setChecked(False)
            # End the current session properly so next Start Test works
            if self._current_session:
                self._current_session.end_time = datetime.now()
                self.database.update_session(self._current_session)
                self._last_completed_session = self._current_session
                self._current_session = None
            self._logging_start_time = None
            # Also stop the automation test
            self.automation_panel._update_ui_stopped()
            # Save test data to JSON if auto-save is enabled
            if self.automation_panel.autosave_checkbox.isChecked():
                saved_path = self._save_test_json()
                if saved_path:
                    self.statusbar.showMessage(
                        f"Test complete: {num_readings} readings saved to {saved_path}"
                    )
                else:
                    self.statusbar.showMessage(
                        f"Test complete: {num_readings} readings - click Save to export"
                    )
            else:
                self.statusbar.showMessage(
                    f"Test complete: {num_readings} readings - click Save to export"
                )

        self._prev_load_on = status.load_on

        # Only add data to plot when logging is enabled
        if self._logging_enabled:
            self.plot_panel.add_data_point(status)

        # Update logged time and points count display
        elapsed = self.plot_panel.get_elapsed_time()
        if elapsed > 0:
            self.status_panel.set_logging_time(elapsed)
        points = self.plot_panel.get_points_count()
        self.status_panel.set_points_count(points)

        self.control_panel.update_status(status)

    @Slot(bool)
    def _update_ui_connection(self, connected: bool) -> None:
        """Update UI for connection state change."""
        self.control_panel.set_connected(connected)
        self.status_panel.set_connected(connected)
        self.automation_panel.set_connected(connected)

        # Update menu actions
        self.connect_action.setEnabled(not connected)
        self.disconnect_action.setEnabled(connected)
        self.reset_action.setEnabled(connected)
        self.device_settings_action.setEnabled(connected)

        if not connected:
            self.status_panel.clear()

    @Slot()
    def _toggle_automation_panel(self) -> None:
        """Toggle visibility of the Test Automation panel content."""
        is_visible = self.bottom_tabs.isVisible()
        panel_height = 380

        if is_visible:
            # Collapse: store current window height, hide tabs, shrink window
            self._expanded_window_height = self.height()
            self.bottom_tabs.setVisible(False)
            self.automation_content.setFixedHeight(0)
            self.automation_toggle.setArrowType(Qt.RightArrow)
            # Shrink window
            self.setFixedHeight(self.height() - panel_height)
            # Remove fixed height constraint to allow future resizing
            self.setMinimumHeight(200)
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        else:
            # Expand: restore tabs and window height
            self.automation_content.setFixedHeight(panel_height)
            self.bottom_tabs.setVisible(True)
            self.automation_toggle.setArrowType(Qt.DownArrow)
            # Restore window height
            target_height = getattr(self, '_expanded_window_height', self.height() + panel_height)
            self.setFixedHeight(target_height)
            # Remove fixed height constraint
            self.setMinimumHeight(400)
            self.setMaximumHeight(16777215)

    @Slot()
    def _on_timer(self) -> None:
        """Periodic UI update."""
        # Refresh port list occasionally
        pass

    @Slot()
    def _show_debug_window(self) -> None:
        """Show the debug console window."""
        self.debug_window.show()
        self.debug_window.raise_()

    def _on_device_debug(self, event_type: str, message: str, data: bytes) -> None:
        """Handle debug event from device (called from device thread)."""
        # Emit signal to handle in main thread
        self.debug_message.emit(event_type, message, data)

    @Slot(str, str, bytes)
    def _on_debug_message(self, event_type: str, message: str, data: bytes) -> None:
        """Handle debug message in main thread."""
        # Write to file if debug logging is enabled
        if hasattr(self, 'control_panel') and self.control_panel.debug_logging_enabled:
            try:
                with open(self.DEBUG_LOG_FILE, 'a') as f:
                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    f.write(f"[{timestamp}] {event_type}: {message}")
                    if data:
                        f.write(f" | data={data[:20].hex()}")
                    f.write("\n")
            except Exception:
                pass

        if event_type in ("SEND", "RECV"):
            self.debug_window.log(message, event_type)
            if data:
                self.debug_window.log_bytes(data, event_type)
        elif event_type == "PARSE":
            self.debug_window.log_parsed(message)
        elif event_type == "ERROR":
            self.debug_window.log_error(message)
        else:
            self.debug_window.log_info(message)

    @Slot(bytes)
    def _send_raw_command(self, data: bytes) -> None:
        """Send raw command bytes to device."""
        if self.device and self.device.is_connected:
            self.device.send_command(data)
        else:
            self.debug_window.log_error("Not connected to device")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close."""
        if self.test_runner and self.test_runner.is_running:
            reply = QMessageBox.question(
                self,
                "Test Running",
                "A test is currently running. Stop it and quit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.test_runner.stop()

        # End any manual logging session
        if self._current_session:
            self._current_session.end_time = datetime.now()
            self.database.update_session(self._current_session)

        if self.device:
            self.device.disconnect()
        self.database.close()
        event.accept()
