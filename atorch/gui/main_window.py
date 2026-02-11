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
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread
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
from .database_dialog import DatabaseDialog
from .battery_load_panel import BatteryLoadPanel
from .power_bank_panel import PowerBankPanel
from .charger_panel import ChargerPanel
from .battery_charger_panel import BatteryChargerPanel
from .placeholder_panel import CableResistancePanel


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

        # Background debug file writer to avoid blocking main thread
        import queue
        import threading
        self._debug_queue = queue.Queue(maxsize=1000)  # Drop messages if queue fills
        self._debug_writer_running = True
        self._debug_writer_thread = threading.Thread(target=self._debug_file_writer, daemon=True)
        self._debug_writer_thread.start()

        # Background database writer to avoid blocking main thread with commits
        self._db_queue = queue.Queue(maxsize=10000)  # Large queue for readings
        self._db_writer_running = True
        self._db_writer_thread = threading.Thread(target=self._database_writer, daemon=True)
        self._db_writer_thread.start()

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
        self._sample_interval = 1.0  # Sample interval in seconds (default 1s)
        self._last_log_time: Optional[float] = None  # Timestamp of last logged reading
        # Limit accumulated readings to last 48 hours at 1 Hz = 172,800 max
        # This prevents unbounded growth during long tests
        from collections import deque
        self._accumulated_readings: deque = deque(maxlen=172800)  # Bounded to 48 hours
        self._prev_load_on = False  # Track previous load state for cutoff detection
        self._last_autosave_time: Optional[datetime] = None  # Track last periodic auto-save
        self._autosave_interval = 30  # Auto-save every 30 seconds during test
        self._last_db_commit_time: Optional[datetime] = None  # Track last database commit
        self._db_commit_interval = 10  # Commit database every 10 seconds
        self._processing_status = False  # Flag to prevent signal queue buildup

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
        # Match plot capacity to accumulated_readings (48 hours at 1Hz)
        self.plot_panel = PlotPanel(max_points=172800)
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

        self.battery_load_panel = BatteryLoadPanel()
        self.bottom_tabs.addTab(self.battery_load_panel, "Battery Load")

        self.battery_charger_panel = BatteryChargerPanel()
        self.bottom_tabs.addTab(self.battery_charger_panel, "Battery Charger")

        self.cable_resistance_panel = CableResistancePanel()
        self.bottom_tabs.addTab(self.cable_resistance_panel, "Cable Resistance")

        self.charger_panel = ChargerPanel()
        self.bottom_tabs.addTab(self.charger_panel, "Wall Charger")

        self.power_bank_panel = PowerBankPanel(None, self.database)  # test_runner set on connect
        self.bottom_tabs.addTab(self.power_bank_panel, "Power Bank")

        self.history_panel = HistoryPanel(self.database)
        self.history_panel.json_file_selected.connect(self._on_history_json_selected)
        self.bottom_tabs.addTab(self.history_panel, "History")

        # Auto-refresh history panel when tab is activated
        self.bottom_tabs.currentChanged.connect(self._on_tab_changed)

        # Connect automation panel signals
        self.automation_panel.start_test_requested.connect(self._on_automation_start)
        self.automation_panel.pause_test_requested.connect(self._on_automation_pause)
        self.automation_panel.resume_test_requested.connect(self._on_automation_resume)
        self.automation_panel.apply_settings_requested.connect(self._on_apply_settings)
        self.automation_panel.manual_save_requested.connect(self._on_manual_save)
        self.automation_panel.session_loaded.connect(self._on_session_loaded)
        self.automation_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect battery load panel signals
        self.battery_load_panel.test_started.connect(self._on_battery_load_start)
        self.battery_load_panel.test_stopped.connect(self._on_battery_load_stop)
        self.battery_load_panel.manual_save_requested.connect(self._on_battery_load_save)
        self.battery_load_panel.session_loaded.connect(self._on_session_loaded)
        self.battery_load_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect charger panel signals
        self.charger_panel.test_started.connect(self._on_charger_start)
        self.charger_panel.test_stopped.connect(self._on_charger_stop)
        self.charger_panel.manual_save_requested.connect(self._on_charger_save)
        self.charger_panel.session_loaded.connect(self._on_session_loaded)
        self.charger_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect battery charger panel signals
        self.battery_charger_panel.test_started.connect(self._on_battery_charger_start)
        self.battery_charger_panel.test_stopped.connect(self._on_battery_charger_stop)
        self.battery_charger_panel.manual_save_requested.connect(self._on_battery_charger_save)
        self.battery_charger_panel.session_loaded.connect(self._on_session_loaded)
        self.battery_charger_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect power bank panel signals
        self.power_bank_panel.start_test_requested.connect(self._on_power_bank_start)
        self.power_bank_panel.apply_settings_requested.connect(self._on_apply_settings)
        self.power_bank_panel.manual_save_requested.connect(self._on_power_bank_save)
        self.power_bank_panel.session_loaded.connect(self._on_session_loaded)
        self.power_bank_panel.export_csv_requested.connect(self._on_export_csv)
        self.power_bank_panel.test_started.connect(lambda: None)  # Placeholder for future use
        self.power_bank_panel.test_stopped.connect(lambda: None)  # Placeholder for future use

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
        self.status_panel.sample_time_changed.connect(self._set_sample_interval)
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

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        database_action = QAction("&Database Management...", self)
        database_action.triggered.connect(self._show_database_dialog)
        tools_menu.addAction(database_action)

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
            self.power_bank_panel.test_runner = self.test_runner

            # Set device and plot references for test panels
            self.battery_load_panel.set_device_and_plot(self.device, self.plot_panel)
            self.charger_panel.set_device_and_plot(self.device, self.plot_panel)
            self.battery_charger_panel.set_device_and_plot(self.device, self.plot_panel)

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

        # Clear device references from test panels
        self.battery_load_panel.set_device_and_plot(None, None)
        self.charger_panel.set_device_and_plot(None, None)
        self.battery_charger_panel.set_device_and_plot(None, None)

        # Disconnect
        if self.device:
            self.device.disconnect()
        self.connection_changed.emit(False)
        self.statusbar.showMessage("Disconnected")

    def _try_auto_connect(self) -> bool:
        """Attempt to auto-connect if an aTorch device is detected in port list.

        Returns:
            True if connected (or already connected), False if connection failed
        """
        import sys
        sys.stderr.write("DEBUG: _try_auto_connect() called\n")
        sys.stderr.flush()

        # Already connected
        if self.device and self.device.is_connected:
            print("DEBUG: Already connected, returning True")
            return True

        # Check if a port is selected
        port = self.control_panel.selected_port
        print(f"DEBUG: Selected port: {port}")

        if not port:
            print("DEBUG: No port selected")
            QMessageBox.warning(
                self,
                "No Device Selected",
                "Please select a device from the port dropdown and click Connect before starting the test."
            )
            return False

        # Get the port display text to check for aTorch device
        port_text = self.control_panel.port_combo.currentText()
        port_text_upper = port_text.upper()
        print(f"DEBUG: Port text: '{port_text}'")
        print(f"DEBUG: Port text upper: '{port_text_upper}'")

        # Check if port looks like an aTorch device (DL24, or other aTorch models)
        is_atorch_device = any(keyword in port_text_upper for keyword in ["ATORCH", "DL24", "DL24P"])
        print(f"DEBUG: Is aTorch device: {is_atorch_device}")

        if not is_atorch_device:
            print("DEBUG: Not an aTorch device, showing warning")
            QMessageBox.warning(
                self,
                "Wrong Device Selected",
                "The selected device does not appear to be an aTorch device.\n\n"
                "Please select the correct aTorch device from the port dropdown and click Connect before starting the test."
            )
            return False

        # Try to connect
        try:
            # Print debug info to help troubleshoot
            print(f"DEBUG: Auto-connecting to device: {port_text}")
            print(f"DEBUG: Port: {port}")

            self._connect_device()

            # Check if connection succeeded
            if self.device and self.device.is_connected:
                print(f"DEBUG: Auto-connect succeeded!")
                self.statusbar.showMessage(f"Auto-connected to {port_text}")
                return True
            else:
                print(f"DEBUG: Auto-connect failed - device not connected")
                QMessageBox.warning(
                    self,
                    "Auto-Connect Failed",
                    f"Could not connect to device.\n\nPlease connect manually."
                )
                return False
        except Exception as e:
            print(f"DEBUG: Auto-connect exception: {e}")
            QMessageBox.warning(
                self,
                "Auto-Connect Failed",
                f"Could not connect to device:\n{e}\n\nPlease connect manually."
            )
            return False

    @Slot(int)
    def _set_sample_interval(self, seconds: int) -> None:
        """Set the sample interval for data logging."""
        self._sample_interval = float(seconds)
        self._last_log_time = None  # Reset to force immediate log on next update

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
            self._last_log_time = None  # Reset sample timer for new test
            self._last_autosave_time = None  # Reset autosave timer for new test
            self._last_db_commit_time = None  # Reset db commit timer for new test
            # Turn on the load when logging starts
            if self.device and self.device.is_connected:
                self.device.turn_on()
                self.control_panel.power_switch.setChecked(True)
            self.statusbar.showMessage("Logging started")
        elif not enabled and self._current_session:
            # End session - commit any pending data first
            self.database.commit()
            self._current_session.end_time = datetime.now()
            self.database.update_session(self._current_session)
            num_readings = len(self._accumulated_readings)
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

    def _save_test_json_background(self, test_config: dict, battery_info: dict,
                                      filename: str, readings: list) -> None:
        """Save test data to JSON in background thread (periodic auto-save).

        All data must be passed in - do NOT access Qt widgets from this method.

        Args:
            test_config: Test configuration dict (gathered on main thread)
            battery_info: Battery info dict (gathered on main thread)
            filename: Filename to save as (gathered on main thread)
            readings: Copy of readings list (gathered on main thread)
        """
        try:
            self._write_test_json(filename, test_config, battery_info, readings)
        except Exception:
            pass  # Silent fail for background auto-save

    def _write_test_json(self, filename: str, test_config: dict, battery_info: dict,
                         readings: list, test_panel_type: str = "battery_capacity") -> Optional[str]:
        """Write test data to JSON file (thread-safe, no GUI access).

        Args:
            filename: Filename to save as
            test_config: Test configuration dict
            battery_info: Battery info dict
            readings: List of Reading objects
            test_panel_type: Type of test panel (battery_capacity, battery_load, etc.)

        Returns:
            Path to saved file, or None if failed
        """
        # Ensure .json extension
        if not filename.endswith('.json'):
            filename += '.json'

        # Create output directory if needed
        output_dir = Path.home() / ".atorch" / "test_data"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # Build test data structure
        readings_data = []
        for reading in readings:
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
            summary = {"total_readings": 0}

        test_data = {
            "test_panel_type": test_panel_type,
            "test_config": test_config,
            "battery_info": battery_info,
            "summary": summary,
            "readings": readings_data,
        }

        try:
            with open(output_path, 'w') as f:
                json.dump(test_data, f, indent=2)
            return str(output_path)
        except Exception:
            return None

    def _save_test_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save test data to JSON file (main thread version).

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

        result = self._write_test_json(filename, test_config, battery_info,
                                       list(self._accumulated_readings))
        if result is None:
            self.statusbar.showMessage("Failed to save test data")
        return result

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
    def _show_database_dialog(self) -> None:
        """Show database management dialog."""
        dialog = DatabaseDialog(self.database, self)
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

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change - refresh history panel when it's activated.

        Args:
            index: The index of the newly activated tab
        """
        # Check if the History tab was activated (it's the last tab)
        if index == self.bottom_tabs.count() - 1:
            self.history_panel.refresh()

    @Slot(str, str)
    def _on_history_json_selected(self, file_path: str, test_panel_type: str) -> None:
        """Handle JSON file selection from history panel.

        Args:
            file_path: Path to the JSON file
            test_panel_type: Type of test panel (battery_capacity, battery_load, etc.)
        """
        # Map test panel types to tab indices
        panel_type_to_tab = {
            "battery_capacity": 0,
            "battery_load": 1,
            "battery_charger": 2,
            "cable_resistance": 3,
            "charger": 4,
            "power_bank": 5,
        }

        # Switch to the appropriate tab
        tab_index = panel_type_to_tab.get(test_panel_type, 0)
        self.bottom_tabs.setCurrentIndex(tab_index)

        # Only load data for battery_capacity, battery_load, battery_charger, charger, and power_bank types (others are placeholders)
        if test_panel_type not in ("battery_capacity", "battery_load", "battery_charger", "charger", "power_bank"):
            self.statusbar.showMessage(f"Selected {test_panel_type.replace('_', ' ').title()} test file (panel not yet implemented)")
            return

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load file: {e}")
            return

        # Handle battery_charger test type
        if test_panel_type == "battery_charger":
            self._load_battery_charger_history(file_path, data)
            return

        # Handle charger test type
        if test_panel_type == "charger":
            self._load_charger_history(file_path, data)
            return

        # Handle battery_load test type
        if test_panel_type == "battery_load":
            self._load_battery_load_history(file_path, data)
            return

        # Handle power_bank test type
        if test_panel_type == "power_bank":
            self._load_power_bank_history(file_path, data)
            return

        # Load test configuration into automation panel
        self.automation_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "discharge_type_index" in test_config:
                self.automation_panel.type_combo.setCurrentIndex(test_config["discharge_type_index"])
            elif "discharge_type" in test_config:
                type_map = {"CC": 0, "CP": 1, "CR": 2}
                self.automation_panel.type_combo.setCurrentIndex(type_map.get(test_config["discharge_type"], 0))
            if "value" in test_config:
                self.automation_panel.value_spin.setValue(test_config["value"])
            if "voltage_cutoff" in test_config:
                self.automation_panel.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.automation_panel.timed_checkbox.setChecked(test_config["timed"])
            if "duration_seconds" in test_config:
                self.automation_panel.duration_spin.setValue(test_config["duration_seconds"])

            # Load battery info
            battery_info = data.get("battery_info", {})
            if "name" in battery_info:
                self.automation_panel.battery_name_edit.setText(battery_info["name"])
            if "manufacturer" in battery_info:
                self.automation_panel.manufacturer_edit.setText(battery_info["manufacturer"])
            if "oem_equivalent" in battery_info:
                self.automation_panel.oem_equiv_edit.setText(battery_info["oem_equivalent"])
            if "serial_number" in battery_info:
                self.automation_panel.serial_number_edit.setText(battery_info["serial_number"])
            if "rated_voltage" in battery_info:
                self.automation_panel.rated_voltage_spin.setValue(battery_info["rated_voltage"])
            if "technology" in battery_info:
                tech_index = self.automation_panel.technology_combo.findText(battery_info["technology"])
                if tech_index >= 0:
                    self.automation_panel.technology_combo.setCurrentIndex(tech_index)
            if "nominal_capacity_mah" in battery_info:
                self.automation_panel.nominal_capacity_spin.setValue(battery_info["nominal_capacity_mah"])
            if "nominal_energy_wh" in battery_info:
                self.automation_panel.nominal_energy_spin.setValue(battery_info["nominal_energy_wh"])
            if "notes" in battery_info:
                self.automation_panel.notes_edit.setPlainText(battery_info["notes"])

            # Update filename
            self.automation_panel.filename_edit.setText(Path(file_path).name)

            # Set graph axes for battery capacity (Voltage vs Time)
            self.plot_panel.x_axis_combo.setCurrentText("Time")
            # Set Y axis to Voltage
            if "Y" in self.plot_panel._axis_dropdowns:
                self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self.plot_panel._axis_checkboxes["Y"].setChecked(True)

            # Load readings for display
            readings = data.get("readings", [])
            if readings:
                self._on_session_loaded(readings)
                # Update test summary with loaded data
                self.automation_panel._update_summary_from_readings(readings)

            self.statusbar.showMessage(f"Loaded Battery Capacity test: {Path(file_path).name}")

        finally:
            self.automation_panel._loading_settings = False

    def _load_battery_load_history(self, file_path: str, data: dict) -> None:
        """Load battery load test data from history.

        Args:
            file_path: Path to the JSON file
            data: Parsed JSON data
        """
        # Load test configuration into battery load panel
        self.battery_load_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "load_type" in test_config:
                self.battery_load_panel.load_type_combo.setCurrentText(test_config["load_type"])
            if "min" in test_config:
                self.battery_load_panel.min_spin.setValue(test_config["min"])
            if "max" in test_config:
                self.battery_load_panel.max_spin.setValue(test_config["max"])
            if "num_steps" in test_config:
                self.battery_load_panel.num_steps_spin.setValue(test_config["num_steps"])
            # Support both old "settle_time" and new "dwell_time" for backwards compatibility
            if "dwell_time" in test_config:
                self.battery_load_panel.dwell_time_spin.setValue(test_config["dwell_time"])
            elif "settle_time" in test_config:
                self.battery_load_panel.dwell_time_spin.setValue(test_config["settle_time"])
            if "voltage_cutoff" in test_config:
                self.battery_load_panel.v_cutoff_spin.setValue(test_config["voltage_cutoff"])

            # Load battery info
            battery_info = data.get("battery_info", {})
            if battery_info:
                self.battery_load_panel.battery_info_widget.set_battery_info(battery_info)

            # Update filename
            self.battery_load_panel.filename_edit.setText(Path(file_path).name)

            # Set graph axes based on load type
            load_type = test_config.get("load_type", "Current")
            x_axis_map = {
                "Current": "Current",
                "Power": "Power",
                "Resistance": "R Load",
            }
            x_axis = x_axis_map.get(load_type, "Current")
            self.plot_panel.x_axis_combo.setCurrentText(x_axis)

            # Enable Voltage on Y-axis for battery load tests
            if "Y" in self.plot_panel._axis_dropdowns:
                self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self.plot_panel._axis_checkboxes["Y"].setChecked(True)

            # Load readings for display
            readings = data.get("readings", [])
            if readings:
                self._on_session_loaded(readings)

            self.statusbar.showMessage(f"Loaded Battery Load test: {Path(file_path).name}")

        finally:
            self.battery_load_panel._loading_settings = False

    def _load_power_bank_history(self, file_path: str, data: dict) -> None:
        """Load power bank test data from history.

        Args:
            file_path: Path to the JSON file
            data: Parsed JSON data
        """
        # Load test configuration into power bank panel
        self.power_bank_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "output_voltage_index" in test_config:
                self.power_bank_panel.output_voltage_combo.setCurrentIndex(test_config["output_voltage_index"])
            if "current" in test_config:
                self.power_bank_panel.current_spin.setValue(test_config["current"])
            if "voltage_cutoff" in test_config:
                self.power_bank_panel.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.power_bank_panel.timed_checkbox.setChecked(test_config["timed"])
            if "duration_seconds" in test_config:
                self.power_bank_panel.duration_spin.setValue(test_config["duration_seconds"])
                self.power_bank_panel._sync_hours_minutes()

            # Load power bank info
            power_bank_info = data.get("power_bank_info", {})
            if "name" in power_bank_info:
                self.power_bank_panel.power_bank_name_edit.setText(power_bank_info["name"])
            if "manufacturer" in power_bank_info:
                self.power_bank_panel.manufacturer_edit.setText(power_bank_info["manufacturer"])
            if "model" in power_bank_info:
                self.power_bank_panel.model_edit.setText(power_bank_info["model"])
            if "serial_number" in power_bank_info:
                self.power_bank_panel.serial_number_edit.setText(power_bank_info["serial_number"])
            if "rated_capacity_mah" in power_bank_info:
                self.power_bank_panel.rated_capacity_spin.setValue(power_bank_info["rated_capacity_mah"])
            if "rated_energy_wh" in power_bank_info:
                self.power_bank_panel.rated_energy_spin.setValue(power_bank_info["rated_energy_wh"])
            if "max_output_current_a" in power_bank_info:
                self.power_bank_panel.max_output_current_spin.setValue(power_bank_info["max_output_current_a"])
            if "usb_ports" in power_bank_info:
                self.power_bank_panel.usb_ports_spin.setValue(power_bank_info["usb_ports"])
            if "usb_pd" in power_bank_info:
                self.power_bank_panel.usb_pd_checkbox.setChecked(power_bank_info["usb_pd"])
            if "quick_charge" in power_bank_info:
                self.power_bank_panel.quick_charge_checkbox.setChecked(power_bank_info["quick_charge"])
            if "notes" in power_bank_info:
                self.power_bank_panel.notes_edit.setPlainText(power_bank_info["notes"])

            # Update filename
            self.power_bank_panel.filename_edit.setText(Path(file_path).name)

            # Set graph axes for power bank tests (Time vs Voltage)
            self.plot_panel.x_axis_combo.setCurrentText("Time")
            if "Y" in self.plot_panel._axis_dropdowns:
                self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self.plot_panel._axis_checkboxes["Y"].setChecked(True)

            # Load readings for display
            readings = data.get("readings", [])
            if readings:
                self._on_session_loaded(readings)

            self.statusbar.showMessage(f"Loaded Power Bank test: {Path(file_path).name}")

        finally:
            self.power_bank_panel._loading_settings = False

    def _load_charger_history(self, file_path: str, data: dict) -> None:
        """Load charger test data from history.

        Args:
            file_path: Path to the JSON file
            data: Parsed JSON data
        """
        # Load test configuration into charger panel
        self.charger_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "load_type" in test_config:
                self.charger_panel.load_type_combo.setCurrentText(test_config["load_type"])
            if "min" in test_config:
                self.charger_panel.min_spin.setValue(test_config["min"])
            if "max" in test_config:
                self.charger_panel.max_spin.setValue(test_config["max"])
            if "num_steps" in test_config:
                self.charger_panel.num_steps_spin.setValue(test_config["num_steps"])
            if "dwell_time" in test_config:
                self.charger_panel.dwell_time_spin.setValue(test_config["dwell_time"])

            # Load charger info
            charger_info = data.get("charger_info", {})
            if "name" in charger_info:
                self.charger_panel.charger_name_edit.setText(charger_info["name"])
            if "manufacturer" in charger_info:
                self.charger_panel.manufacturer_edit.setText(charger_info["manufacturer"])
            if "model" in charger_info:
                self.charger_panel.model_edit.setText(charger_info["model"])
            if "rated_output_w" in charger_info:
                self.charger_panel.rated_output_spin.setValue(charger_info["rated_output_w"])
            if "rated_voltage_v" in charger_info:
                self.charger_panel.rated_voltage_spin.setValue(charger_info["rated_voltage_v"])
            if "rated_current_a" in charger_info:
                self.charger_panel.rated_current_spin.setValue(charger_info["rated_current_a"])
            if "usb_ports" in charger_info:
                self.charger_panel.usb_ports_edit.setText(charger_info["usb_ports"])
            if "usb_pd" in charger_info:
                self.charger_panel.usb_pd_checkbox.setChecked(charger_info["usb_pd"])
            if "gan" in charger_info:
                self.charger_panel.gan_checkbox.setChecked(charger_info["gan"])
            if "notes" in charger_info:
                self.charger_panel.notes_edit.setPlainText(charger_info["notes"])

            # Update filename
            self.charger_panel.filename_edit.setText(Path(file_path).name)

            # Set graph axes based on load type (similar to battery load)
            load_type = test_config.get("load_type", "Current")
            x_axis_map = {
                "Current": "Current",
                "Power": "Power",
                "Resistance": "R Load",
            }
            x_axis = x_axis_map.get(load_type, "Current")
            self.plot_panel.x_axis_combo.setCurrentText(x_axis)

            # Enable Voltage on Y-axis for charger tests
            if "Y" in self.plot_panel._axis_dropdowns:
                self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self.plot_panel._axis_checkboxes["Y"].setChecked(True)

            # Load readings for display
            readings = data.get("readings", [])
            if readings:
                self._on_session_loaded(readings)

            self.statusbar.showMessage(f"Loaded Charger test: {Path(file_path).name}")

        finally:
            self.charger_panel._loading_settings = False

    def _load_battery_charger_history(self, file_path: str, data: dict) -> None:
        """Load battery charger test data from history.

        Args:
            file_path: Path to the JSON file
            data: Parsed JSON data
        """
        # Load test configuration into battery charger panel
        self.battery_charger_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "chemistry" in test_config:
                self.battery_charger_panel.chemistry_combo.setCurrentText(test_config["chemistry"])
            if "min_voltage" in test_config:
                self.battery_charger_panel.min_voltage_spin.setValue(test_config["min_voltage"])
            if "max_voltage" in test_config:
                self.battery_charger_panel.max_voltage_spin.setValue(test_config["max_voltage"])
            if "num_steps" in test_config:
                self.battery_charger_panel.num_steps_spin.setValue(test_config["num_steps"])
            if "dwell_time" in test_config:
                self.battery_charger_panel.dwell_time_spin.setValue(test_config["dwell_time"])

            # Load charger info
            charger_info = data.get("charger_info", {})
            if "name" in charger_info:
                self.battery_charger_panel.charger_name_edit.setText(charger_info["name"])
            if "manufacturer" in charger_info:
                self.battery_charger_panel.manufacturer_edit.setText(charger_info["manufacturer"])
            if "model" in charger_info:
                self.battery_charger_panel.model_edit.setText(charger_info["model"])
            if "chemistry" in charger_info:
                self.battery_charger_panel.charger_chemistry_combo.setCurrentText(charger_info["chemistry"])
            if "rated_output_current_a" in charger_info:
                self.battery_charger_panel.rated_current_spin.setValue(charger_info["rated_output_current_a"])
            if "rated_voltage_v" in charger_info:
                self.battery_charger_panel.rated_voltage_spin.setValue(charger_info["rated_voltage_v"])
            if "number_of_cells" in charger_info:
                self.battery_charger_panel.num_cells_spin.setValue(charger_info["number_of_cells"])
            if "notes" in charger_info:
                self.battery_charger_panel.notes_edit.setPlainText(charger_info["notes"])

            # Update filename
            self.battery_charger_panel.filename_edit.setText(Path(file_path).name)

            # Set graph axes for battery charger tests (Voltage vs Current)
            self.plot_panel.x_axis_combo.setCurrentText("Voltage")
            if "Y" in self.plot_panel._axis_dropdowns:
                self.plot_panel._axis_dropdowns["Y"].setCurrentText("Current")
                self.plot_panel._axis_checkboxes["Y"].setChecked(True)

            # Load readings for display
            readings = data.get("readings", [])
            if readings:
                self._on_session_loaded(readings)

            self.statusbar.showMessage(f"Loaded Battery Charger test: {Path(file_path).name}")

        finally:
            self.battery_charger_panel._loading_settings = False

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

        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
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

        # Configure plot for Battery Capacity test: Time vs Voltage
        self.plot_panel.x_axis_combo.setCurrentText("Time")
        if "Y" in self.plot_panel._axis_dropdowns:
            self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
            self.plot_panel._axis_checkboxes["Y"].setChecked(True)

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
            self._last_autosave_time = None  # Reset autosave timer
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

    @Slot()
    def _on_battery_load_start(self) -> None:
        """Handle test start from battery load panel."""
        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
                return

        # Clear data and previous session before starting new test
        self._clear_data()
        self._last_completed_session = None

        # Clear device counters (mAh, Wh, time)
        self.device.reset_counters()

        # Start logging (which also turns on the load)
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        self.statusbar.showMessage("Battery Load test started")

    @Slot()
    def _on_battery_load_stop(self) -> None:
        """Handle test stop from battery load panel."""
        # Stop logging and save data if auto-save is enabled
        if self._logging_enabled:
            num_readings = len(self._accumulated_readings)
            # Save test data to JSON if auto-save is enabled
            if self.battery_load_panel.autosave_checkbox.isChecked():
                saved_path = self._save_battery_load_json()
                if saved_path:
                    self.statusbar.showMessage(
                        f"Battery Load test complete: {num_readings} readings saved to {saved_path}"
                    )
                    # Refresh history panel to show new file
                    self.history_panel.refresh()
                else:
                    self.statusbar.showMessage(
                        f"Battery Load test complete: {num_readings} readings - click Save to export"
                    )
            else:
                self.statusbar.showMessage(
                    f"Battery Load test complete: {num_readings} readings - click Save to export"
                )
            self.status_panel.log_switch.setChecked(False)
            self._toggle_logging(False)

    @Slot(str)
    def _on_battery_load_save(self, filename: str) -> None:
        """Handle manual save request from battery load panel.

        Args:
            filename: The filename to save as
        """
        if not self._accumulated_readings:
            self.statusbar.showMessage("No data to save")
            return

        saved_path = self._save_battery_load_json(filename)
        if saved_path:
            self.statusbar.showMessage(f"Saved: {saved_path}")
            # Refresh history panel to show new file
            self.history_panel.refresh()

    def _save_battery_load_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save battery load test data to JSON file.

        Args:
            filename: Optional filename to use. If None, uses the filename from battery load panel.

        Returns:
            Path to saved file, or None if save failed
        """
        # Get test configuration and battery info from battery load panel
        test_config = self.battery_load_panel.get_test_config()
        battery_info = self.battery_load_panel.get_battery_info()

        # Use provided filename or get from battery load panel
        if filename is None:
            filename = self.battery_load_panel.filename_edit.text().strip()
            if not filename:
                filename = self.battery_load_panel.generate_test_filename()

        result = self._write_test_json(filename, test_config, battery_info,
                                       list(self._accumulated_readings),
                                       test_panel_type="battery_load")
        if result is None:
            self.statusbar.showMessage("Failed to save test data")
        return result

    @Slot()
    def _on_charger_start(self) -> None:
        """Handle test start from charger panel."""
        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
                return

        # Clear data and previous session before starting new test
        self._clear_data()
        self._last_completed_session = None

        # Clear device counters (mAh, Wh, time)
        self.device.reset_counters()

        # Start logging (which also turns on the load)
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        self.statusbar.showMessage("Charger test started")

    @Slot()
    def _on_charger_stop(self) -> None:
        """Handle test stop from charger panel."""
        # Stop logging and save data if auto-save is enabled
        if self._logging_enabled:
            num_readings = len(self._accumulated_readings)
            # Save test data to JSON if auto-save is enabled
            if self.charger_panel.autosave_checkbox.isChecked():
                saved_path = self._save_charger_json()
                if saved_path:
                    self.statusbar.showMessage(
                        f"Charger test complete: {num_readings} readings saved to {saved_path}"
                    )
                    # Refresh history panel to show new file
                    self.history_panel.refresh()
                else:
                    self.statusbar.showMessage(
                        f"Charger test complete: {num_readings} readings - click Save to export"
                    )
            else:
                self.statusbar.showMessage(
                    f"Charger test complete: {num_readings} readings - click Save to export"
                )
            self.status_panel.log_switch.setChecked(False)
            self._toggle_logging(False)

    @Slot(str)
    def _on_charger_save(self, filename: str) -> None:
        """Handle manual save request from charger panel.

        Args:
            filename: The filename to save as
        """
        if not self._accumulated_readings:
            self.statusbar.showMessage("No data to save")
            return

        saved_path = self._save_charger_json(filename)
        if saved_path:
            self.statusbar.showMessage(f"Saved: {saved_path}")
            # Refresh history panel to show new file
            self.history_panel.refresh()

    def _save_charger_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save charger test data to JSON file.

        Args:
            filename: Optional filename to use. If None, uses the filename from charger panel.

        Returns:
            Path to saved file, or None if save failed
        """
        # Get test configuration and charger info from charger panel
        test_config = self.charger_panel.get_test_config()
        charger_info = self.charger_panel.get_charger_info()

        # Use provided filename or get from charger panel
        if filename is None:
            filename = self.charger_panel.filename_edit.text().strip()
            if not filename:
                filename = self.charger_panel.generate_test_filename()

        result = self._write_test_json(filename, test_config, charger_info,
                                       list(self._accumulated_readings),
                                       test_panel_type="charger")
        if result is None:
            self.statusbar.showMessage("Failed to save test data")
        return result

    @Slot()
    def _on_battery_charger_start(self) -> None:
        """Handle test start from battery charger panel."""
        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
                return

        # Clear data and previous session before starting new test
        self._clear_data()
        self._last_completed_session = None

        # Clear device counters (mAh, Wh, time)
        self.device.reset_counters()

        # Start logging (which also turns on the load)
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        self.statusbar.showMessage("Battery Charger test started")

    @Slot()
    def _on_battery_charger_stop(self) -> None:
        """Handle test stop from battery charger panel."""
        # Stop logging and save data if auto-save is enabled
        if self._logging_enabled:
            num_readings = len(self._accumulated_readings)
            # Save test data to JSON if auto-save is enabled
            if self.battery_charger_panel.autosave_checkbox.isChecked():
                saved_path = self._save_battery_charger_json()
                if saved_path:
                    self.statusbar.showMessage(
                        f"Battery Charger test complete: {num_readings} readings saved to {saved_path}"
                    )
                    # Refresh history panel to show new file
                    self.history_panel.refresh()
                else:
                    self.statusbar.showMessage(
                        f"Battery Charger test complete: {num_readings} readings - click Save to export"
                    )
            else:
                self.statusbar.showMessage(
                    f"Battery Charger test complete: {num_readings} readings - click Save to export"
                )
            self.status_panel.log_switch.setChecked(False)
            self._toggle_logging(False)

    @Slot(str)
    def _on_battery_charger_save(self, filename: str) -> None:
        """Handle manual save request from battery charger panel.

        Args:
            filename: The filename to save as
        """
        if not self._accumulated_readings:
            self.statusbar.showMessage("No data to save")
            return

        saved_path = self._save_battery_charger_json(filename)
        if saved_path:
            self.statusbar.showMessage(f"Saved: {saved_path}")
            # Refresh history panel to show new file
            self.history_panel.refresh()

    def _save_battery_charger_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save battery charger test data to JSON file.

        Args:
            filename: Optional filename to use. If None, uses the filename from battery charger panel.

        Returns:
            Path to saved file, or None if save failed
        """
        # Get test configuration and charger info from battery charger panel
        test_config = self.battery_charger_panel.get_test_config()
        charger_info = self.battery_charger_panel.get_charger_info()

        # Use provided filename or get from battery charger panel
        if filename is None:
            filename = self.battery_charger_panel.filename_edit.text().strip()
            if not filename:
                filename = self.battery_charger_panel.generate_test_filename()

        result = self._write_test_json(filename, test_config, charger_info,
                                       list(self._accumulated_readings),
                                       test_panel_type="battery_charger")
        if result is None:
            self.statusbar.showMessage("Failed to save test data")
        return result

    @Slot(int, float, float, int)
    def _on_power_bank_start(self, discharge_type: int, value: float, voltage_cutoff: float, duration_s: int) -> None:
        """Handle test start request from power bank panel.

        Args:
            discharge_type: Always 0 (CC mode for power banks)
            value: Current in A
            voltage_cutoff: Voltage cutoff in V
            duration_s: Duration in seconds (0 for no limit)
        """
        if discharge_type == 0 and value == 0 and voltage_cutoff == 0:
            # Stop request - save data and turn off logging
            if self._logging_enabled:
                num_readings = len(self._accumulated_readings)
                if self.power_bank_panel.autosave_checkbox.isChecked():
                    saved_path = self._save_power_bank_json()
                    if saved_path:
                        self.statusbar.showMessage(
                            f"Power Bank test aborted: {num_readings} readings saved to {saved_path}"
                        )
                else:
                    self.statusbar.showMessage(
                        f"Power Bank test aborted: {num_readings} readings - click Save to export"
                    )
                self.status_panel.log_switch.setChecked(False)
                self._toggle_logging(False)
            return

        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
                return

        # Clear data and previous session before starting new test
        self._clear_data()
        self._last_completed_session = None

        # Clear device counters (mAh, Wh, time)
        self.device.reset_counters()

        # Set CC mode and current
        self.control_panel.mode_btn_group.button(0).setChecked(True)  # CC button
        self.control_panel.current_spin.setValue(value)
        self.device.set_current(value)

        # Set voltage cutoff
        self.device.set_voltage_cutoff(voltage_cutoff)
        self.control_panel.cutoff_spin.setValue(voltage_cutoff)

        # Start logging (also turns on load)
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            self._toggle_logging(True)

        # Configure plot for time vs voltage
        self.plot_panel.x_axis_combo.setCurrentText("Time")
        self.plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
        self.plot_panel._axis_checkboxes["Y"].setChecked(True)

        output_voltage = self.power_bank_panel.output_voltage_combo.currentText().split()[0]
        self.statusbar.showMessage(f"Power Bank test started: {output_voltage} @ {value}A")

    @Slot(str)
    def _on_power_bank_save(self, filename: str) -> None:
        """Handle manual save request from power bank panel.

        Args:
            filename: The filename to save as
        """
        if not self._accumulated_readings:
            self.statusbar.showMessage("No data to save")
            return

        saved_path = self._save_power_bank_json(filename)
        if saved_path:
            self.statusbar.showMessage(f"Saved: {saved_path}")
            self.history_panel.refresh()

    def _save_power_bank_json(self, filename: Optional[str] = None) -> Optional[str]:
        """Save power bank test data to JSON file.

        Args:
            filename: Optional filename to use. If None, uses the filename from power bank panel.

        Returns:
            Path to saved file, or None if save failed
        """
        # Get test configuration and power bank info from power bank panel
        test_config = self.power_bank_panel.get_test_config()
        power_bank_info = self.power_bank_panel.get_power_bank_info()

        # Use provided filename or get from power bank panel
        if filename is None:
            filename = self.power_bank_panel.filename_edit.text().strip()
            if not filename:
                filename = self.power_bank_panel.generate_test_filename()

        result = self._write_test_json(filename, test_config, power_bank_info,
                                       list(self._accumulated_readings),
                                       test_panel_type="power_bank")
        if result is None:
            self.statusbar.showMessage("Failed to save test data")
        return result

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
        # Skip if still processing previous update (prevents signal queue buildup)
        if self._processing_status:
            return
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
        # Mark as processing to prevent signal queue buildup
        self._processing_status = True
        try:
            self._do_update_ui_status(status)
        finally:
            self._processing_status = False

    def _do_update_ui_status(self, status: DeviceStatus) -> None:
        """Internal method to update UI with device status."""
        # Log data first (before UI update) if enabled
        if self._logging_enabled and self._current_session:
            # Check if enough time has elapsed since last log
            import time
            current_time = time.time()
            should_log = False

            if self._last_log_time is None:
                # First reading - always log
                should_log = True
            elif (current_time - self._last_log_time) >= self._sample_interval:
                # Enough time has elapsed
                should_log = True

            if should_log:
                self._last_log_time = current_time

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
                # Queue reading for background database writer (non-blocking)
                try:
                    self._db_queue.put_nowait((self._current_session.id, reading))
                except:
                    pass  # Drop if queue full (very unlikely with 10k capacity)

                # Don't append to _current_session.readings - it's an unbounded list that causes GUI hang
                # All data is preserved in database and _accumulated_readings (bounded deque)
                self._accumulated_readings.append(reading)

        # Check alerts
        self.notifier.check(status)

        # Update test progress bar in automation panel
        if self._logging_enabled:
            elapsed = self.plot_panel.get_elapsed_time()
            self.automation_panel.update_test_progress(elapsed, status.capacity_mah,
                                                      status.voltage, status.energy_wh)

        # Pulse communication indicator to show data received
        self.control_panel.pulse_comm_indicator()

        self.status_panel.update_status(status)

        # Detect if load turned off during logging (e.g., voltage cutoff)
        # Check this BEFORE adding data to prevent extra data points
        if self._logging_enabled and self._prev_load_on and not status.load_on:
            # Load turned off while logging - stop logging immediately
            num_readings = len(self._accumulated_readings)
            self._logging_enabled = False  # Stop immediately to prevent more data
            self.status_panel.log_switch.setChecked(False)
            # End the current session properly so next Start Test works
            if self._current_session:
                self.database.commit()  # Commit any pending readings
                self._current_session.end_time = datetime.now()
                self.database.update_session(self._current_session)
                self._last_completed_session = self._current_session
                self._current_session = None
            self._logging_start_time = None

            # Check which panel has an active test and stop it
            # Stop the automation test if running
            self.automation_panel._update_ui_stopped()

            # Stop battery load test if running
            if self.battery_load_panel._test_running:
                # Stop the test timer and update UI directly (don't call _abort_test to avoid re-triggering logging stop)
                self.battery_load_panel._test_timer.stop()
                self.battery_load_panel.start_btn.setText("Start")
                self.battery_load_panel.status_label.setText("Test Aborted (Load Off)")
                self.battery_load_panel.progress_bar.setValue(100)
                self.battery_load_panel._test_running = False
                # Note: Don't emit test_stopped here since logging is already handled above

            # Save test data to JSON if auto-save is enabled (check both panels)
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
            elif self.battery_load_panel.autosave_checkbox.isChecked():
                saved_path = self._save_battery_load_json()
                if saved_path:
                    self.statusbar.showMessage(
                        f"Battery Load test complete: {num_readings} readings saved to {saved_path}"
                    )
                    # Refresh history panel to show new file
                    self.history_panel.refresh()
                else:
                    self.statusbar.showMessage(
                        f"Battery Load test complete: {num_readings} readings - click Save to export"
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
        self.battery_load_panel.set_connected(connected)
        self.charger_panel.set_connected(connected)
        self.battery_charger_panel.set_connected(connected)
        self.power_bank_panel.set_connected(connected)

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
    def _debug_file_writer(self) -> None:
        """Background thread that writes debug messages to file."""
        import queue
        while self._debug_writer_running:
            try:
                # Wait up to 1 second for a message
                log_line = self._debug_queue.get(timeout=1.0)
                if log_line is None:  # Shutdown signal
                    break
                # Write to file
                with open(self.DEBUG_LOG_FILE, 'a') as f:
                    f.write(log_line)
            except queue.Empty:
                continue
            except Exception:
                pass  # Silently ignore errors in background thread

    def _database_writer(self) -> None:
        """Background thread that writes readings to database."""
        import queue
        import time
        pending_readings = []
        last_commit_time = time.time()

        while self._db_writer_running:
            try:
                # Wait up to 1 second for a reading
                item = self._db_queue.get(timeout=1.0)
                if item is None:  # Shutdown signal
                    break

                session_id, reading = item
                # Add reading without commit
                self.database.add_reading(session_id, reading, commit=False)
                pending_readings.append(reading)

                # Commit every 10 seconds or 100 readings (whichever comes first)
                current_time = time.time()
                if (current_time - last_commit_time >= 10.0) or (len(pending_readings) >= 100):
                    self.database.commit()
                    pending_readings.clear()
                    last_commit_time = current_time

            except queue.Empty:
                # Timeout - commit any pending readings
                if pending_readings:
                    try:
                        self.database.commit()
                        pending_readings.clear()
                        last_commit_time = time.time()
                    except:
                        pass
                continue
            except Exception:
                pass  # Silently ignore errors in background thread

        # Final commit on shutdown
        if pending_readings:
            try:
                self.database.commit()
            except:
                pass

    def _on_debug_message(self, event_type: str, message: str, data: bytes) -> None:
        """Handle debug message in main thread."""
        # Queue to file if debug logging is enabled (written by background thread)
        if hasattr(self, 'control_panel') and self.control_panel.debug_logging_enabled:
            try:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                log_line = f"[{timestamp}] {event_type}: {message}"
                if data:
                    log_line += f" | data={data[:20].hex()}"
                log_line += "\n"
                # Non-blocking put - will drop if queue is full
                self._debug_queue.put_nowait(log_line)
            except:
                pass  # Drop message if queue is full

        # Only update debug window if it's visible (prevents 21,600+ GUI ops/hour when hidden)
        if not self.debug_window.isVisible():
            return

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

        # Stop background writer threads
        self._debug_writer_running = False
        self._db_writer_running = False
        try:
            self._debug_queue.put(None, timeout=1.0)  # Send shutdown signal
            self._db_queue.put(None, timeout=1.0)
            self._debug_writer_thread.join(timeout=2.0)  # Wait up to 2 seconds
            self._db_writer_thread.join(timeout=2.0)
        except:
            pass

        if self.device:
            self.device.disconnect()
        self.database.close()
        event.accept()
