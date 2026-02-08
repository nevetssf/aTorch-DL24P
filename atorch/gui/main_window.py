"""Main application window."""

from datetime import datetime
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
from .settings_dialog import SettingsDialog
from .debug_window import DebugWindow


class MainWindow(QMainWindow):
    """Main application window for DL24P control."""

    status_updated = Signal(DeviceStatus)
    connection_changed = Signal(bool)
    test_progress = Signal(TestProgress)
    debug_message = Signal(str, str, bytes)  # event_type, message, data

    def __init__(self):
        super().__init__()

        self.setWindowTitle("aTorch DL24P Control")
        self.setMinimumSize(1200, 800)

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
        self._logging_enabled = False
        self._logging_start_time: Optional[datetime] = None  # Track when logging started
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

        # Main content splitter
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
        main_layout.addWidget(splitter, stretch=3)

        # Bottom tabs: Automation and History
        bottom_tabs = QTabWidget()

        self.automation_panel = AutomationPanel(None, self.database)  # test_runner set on connect
        bottom_tabs.addTab(self.automation_panel, "Test Automation")

        self.history_panel = HistoryPanel(self.database)
        self.history_panel.session_selected.connect(self._on_history_session_selected)
        bottom_tabs.addTab(self.history_panel, "History")

        # Connect automation panel signals
        self.automation_panel.start_test_requested.connect(self._on_automation_start)
        self.automation_panel.pause_test_requested.connect(self._on_automation_pause)
        self.automation_panel.resume_test_requested.connect(self._on_automation_resume)

        bottom_tabs.setMaximumHeight(250)
        main_layout.addWidget(bottom_tabs, stretch=1)

        # Connect signals
        self.status_updated.connect(self._update_ui_status)
        self.connection_changed.connect(self._update_ui_connection)
        self.test_progress.connect(self.automation_panel.update_progress)

        # Connect control panel signals
        self.control_panel.connect_requested.connect(self._connect_device)
        self.control_panel.disconnect_requested.connect(self._disconnect_device)
        self.control_panel.logging_toggled.connect(self._toggle_logging)
        self.control_panel.clear_requested.connect(self._clear_data)
        self.control_panel.save_requested.connect(self._export_session_with_name)

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
            self.control_panel.log_switch.setChecked(False)
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
            self.statusbar.showMessage(
                f"Logged {len(self._current_session.readings)} readings"
            )
            self._current_session = None
            self._logging_enabled = False
            self._logging_start_time = None
            # Turn off the load when logging stops
            if self.device and self.device.is_connected:
                self.device.turn_off()
                self.control_panel.power_switch.setChecked(False)

    @Slot()
    def _clear_data(self) -> None:
        """Clear accumulated plot data and logging time."""
        self.plot_panel.clear_data()
        self.status_panel.clear_logging_time()
        self.statusbar.showMessage("Data cleared")

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
        session = self._current_session
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

    @Slot()
    def _show_settings(self) -> None:
        """Show settings dialog."""
        dialog = SettingsDialog(self.notifier, self)
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

    @Slot(float, float, int)
    def _on_automation_start(self, current_a: float, voltage_cutoff: float, duration_s: int) -> None:
        """Handle test start request from automation panel."""
        if current_a == 0 and voltage_cutoff == 0:
            # Stop request - turn off logging
            if self._logging_enabled:
                self.control_panel.log_switch.setChecked(False)
                self._toggle_logging(False)
            return

        if not self.device or not self.device.is_connected:
            return

        # Clear data before starting new test
        self._clear_data()

        # Set current in control panel and device
        self.control_panel.current_spin.setValue(current_a)
        self.device.set_current(current_a)

        # Set voltage cutoff in control panel and device
        self.control_panel.cutoff_spin.setValue(voltage_cutoff)
        self.device.set_voltage_cutoff(voltage_cutoff)

        # Set duration if specified (timed test) - convert seconds to hours/minutes
        if duration_s > 0:
            hours = duration_s // 3600
            minutes = (duration_s % 3600) // 60
            self.control_panel.discharge_hours_spin.setValue(hours)
            self.control_panel.discharge_mins_spin.setValue(minutes)
            if hasattr(self.device, 'set_discharge_time'):
                self.device.set_discharge_time(hours, minutes)

        # Start logging (which also turns on the load)
        if not self._logging_enabled:
            self.control_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        self.statusbar.showMessage(f"Test started: {current_a}A, cutoff {voltage_cutoff}V")

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
            self.control_panel.log_switch.setChecked(False)

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
            self.control_panel.log_switch.setChecked(True)

        # Turn on load
        if self.device and self.device.is_connected:
            self.device.turn_on()
            self.control_panel.power_switch.setChecked(True)

        self.statusbar.showMessage("Test resumed")

    def _on_device_status(self, status: DeviceStatus) -> None:
        """Handle device status update (called from device thread)."""
        self.status_updated.emit(status)

        # Check alerts
        self.notifier.check(status)

        # Log if enabled
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

    def _on_device_error(self, message: str) -> None:
        """Handle device error."""
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
        """Update UI with device status."""
        self.status_panel.update_status(status)

        # Detect if load turned off during logging (e.g., voltage cutoff)
        # Check this BEFORE adding data to prevent extra data points
        if self._logging_enabled and self._prev_load_on and not status.load_on:
            # Load turned off while logging - stop logging immediately
            self._logging_enabled = False  # Stop immediately to prevent more data
            self.control_panel.log_switch.setChecked(False)
            # Also stop the automation test
            self.automation_panel._update_ui_stopped()
            self.statusbar.showMessage("Test stopped: voltage cutoff reached")

        self._prev_load_on = status.load_on

        # Update logging time based on logged data (last reading - start time)
        if self._logging_enabled and self._current_session and self._current_session.readings:
            last_reading = self._current_session.readings[-1]
            elapsed = (last_reading.timestamp - self._current_session.start_time).total_seconds()
            self.status_panel.set_logging_time(elapsed)

        # Only add data to plot when logging is enabled
        if self._logging_enabled:
            self.plot_panel.add_data_point(status)

        self.control_panel.update_status(status)

    @Slot(bool)
    def _update_ui_connection(self, connected: bool) -> None:
        """Update UI for connection state change."""
        self.control_panel.set_connected(connected)

        # Update menu actions
        self.connect_action.setEnabled(not connected)
        self.disconnect_action.setEnabled(connected)
        self.reset_action.setEnabled(connected)

        if not connected:
            self.status_panel.clear()

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
