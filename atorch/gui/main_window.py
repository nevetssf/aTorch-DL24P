"""Main application window."""

import csv
import json
import subprocess
import sys
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
    QDialog,
    QTextBrowser,
    QPushButton,
    QSystemTrayIcon,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread
from PySide6.QtGui import QAction, QCloseEvent, QIcon

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
from .battery_capacity_panel import BatteryCapacityPanel
from .history_panel import HistoryPanel
from .settings_dialog import SettingsDialog, DeviceSettingsDialog
from .debug_window import DebugWindow
from .database_dialog import DatabaseDialog
from .battery_load_panel import BatteryLoadPanel
from .power_bank_panel import PowerBankPanel
from .charger_panel import ChargerPanel
from .battery_charger_panel import BatteryChargerPanel


class MainWindow(QMainWindow):
    """Main application window for DL24P control."""

    status_updated = Signal(DeviceStatus)
    connection_changed = Signal(bool)
    test_progress = Signal(TestProgress)
    debug_message = Signal(str, str, bytes)  # event_type, message, data
    error_occurred = Signal(str)  # error message
    prepare_needed = Signal()  # device needs USB prepare (no response detected)

    DEBUG_LOG_FILE = "/Users/steve/Projects/atorch/debug.log"

    def __init__(self):
        super().__init__()

        self.setWindowTitle("DL24/P Test Bench")
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
        self._test_viewer_process = None  # Track Test Viewer process
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
        self._start_delay_timer: Optional[QTimer] = None  # Timer for start delay countdown
        self._sample_interval = 1.0  # Sample interval in seconds (default 1s)
        self._last_log_time: Optional[float] = None  # Timestamp of last logged reading
        # Limit accumulated readings to last 48 hours at 1 Hz = 172,800 max
        # This prevents unbounded growth during long tests
        from collections import deque
        self._accumulated_readings: deque = deque(maxlen=172800)  # Bounded to 48 hours
        self._prev_load_on = False  # Track previous load state for cutoff detection
        self._load_off_count = 0  # Consecutive polls with load off during logging
        self._load_off_abort_threshold = 3  # Abort after N consecutive load-off polls
        self._last_autosave_time: Optional[datetime] = None  # Track last periodic auto-save
        self._autosave_interval = 30  # Auto-save every 30 seconds during test
        self._last_db_commit_time: Optional[datetime] = None  # Track last database commit
        self._db_commit_interval = 10  # Commit database every 10 seconds
        self._processing_status = False  # Flag to prevent signal queue buildup
        self._awaiting_first_status = False  # True after connect, cleared on first response

        # Setup
        self._setup_alerts()
        self._setup_callbacks()
        self._create_ui()
        self._create_menus()
        self._create_system_tray()
        self._create_statusbar()

        # Load and apply tooltip preference
        tooltips_enabled = self._load_tooltip_preference()
        self.tooltips_action.setChecked(tooltips_enabled)
        if not tooltips_enabled:
            self._set_tooltips_enabled(False)

        # Sync battery info on startup to ensure both panels start with same data
        # Use whichever panel's session file was modified most recently
        self._sync_battery_info_on_startup()

        # Update timer
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._on_timer)
        self._update_timer.start(100)  # 10 Hz UI updates

    def _setup_alerts(self) -> None:
        """Configure default alert conditions."""
        self.notifier.add_condition(TemperatureAlert(threshold=70))
        self.notifier.add_condition(TestCompleteAlert())

    def _update_test_complete_alert_state(self, logging_active: bool) -> None:
        """Update the TestCompleteAlert with the current logging state.

        Args:
            logging_active: True if test/logging is active, False otherwise
        """
        alert = self.notifier.get_condition(TestCompleteAlert)
        if alert and hasattr(alert, 'set_logging_active'):
            alert.set_logging_active(logging_active)

    def _disable_controls_during_test(self) -> None:
        """Disable UI controls that shouldn't be changed during a test."""
        # Disable mode selection buttons
        self.control_panel.cc_btn.setEnabled(False)
        self.control_panel.cp_btn.setEnabled(False)
        self.control_panel.cv_btn.setEnabled(False)
        self.control_panel.cr_btn.setEnabled(False)

        # Disable parameter spinboxes
        self.control_panel.current_spin.setEnabled(False)
        self.control_panel.power_spin.setEnabled(False)
        self.control_panel.voltage_spin.setEnabled(False)
        self.control_panel.resistance_spin.setEnabled(False)
        self.control_panel.cutoff_spin.setEnabled(False)
        self.control_panel.discharge_hours_spin.setEnabled(False)
        self.control_panel.discharge_mins_spin.setEnabled(False)

        # Disable Set buttons
        self.control_panel.set_current_btn.setEnabled(False)
        self.control_panel.set_power_btn.setEnabled(False)
        self.control_panel.set_voltage_btn.setEnabled(False)
        self.control_panel.set_resistance_btn.setEnabled(False)
        self.control_panel.set_cutoff_btn.setEnabled(False)
        self.control_panel.set_discharge_btn.setEnabled(False)

        # Disable preset current buttons (0.1A, 0.2A, 0.5A, 1.0A)
        for i in range(self.control_panel.preset_btns.count()):
            widget = self.control_panel.preset_btns.itemAt(i).widget()
            if widget:
                widget.setEnabled(False)

        # Disable data logging controls (except the load switch is handled by status panel)
        self.status_panel.log_switch.setEnabled(False)
        self.status_panel.sample_time_combo.setEnabled(False)
        self.status_panel.battery_name_edit.setEnabled(False)

        # Disable all test panel tabs except the current one
        current_tab = self.bottom_tabs.currentIndex()
        for i in range(self.bottom_tabs.count()):
            if i != current_tab:
                self.bottom_tabs.setTabEnabled(i, False)

        # Disable input fields on the active test panel
        current_widget = self.bottom_tabs.currentWidget()
        if hasattr(current_widget, 'set_inputs_enabled'):
            current_widget.set_inputs_enabled(False)

    def _enable_controls_after_test(self) -> None:
        """Re-enable UI controls after a test completes."""
        # Re-enable mode selection buttons (if connected)
        if self.device and self.device.is_connected:
            self.control_panel.cc_btn.setEnabled(True)
            self.control_panel.cp_btn.setEnabled(True)
            self.control_panel.cv_btn.setEnabled(True)
            self.control_panel.cr_btn.setEnabled(True)

            # Re-enable parameter spinboxes
            self.control_panel.current_spin.setEnabled(True)
            self.control_panel.power_spin.setEnabled(True)
            self.control_panel.voltage_spin.setEnabled(True)
            self.control_panel.resistance_spin.setEnabled(True)
            self.control_panel.cutoff_spin.setEnabled(True)
            self.control_panel.discharge_hours_spin.setEnabled(True)
            self.control_panel.discharge_mins_spin.setEnabled(True)

            # Re-enable Set buttons
            self.control_panel.set_current_btn.setEnabled(True)
            self.control_panel.set_power_btn.setEnabled(True)
            self.control_panel.set_voltage_btn.setEnabled(True)
            self.control_panel.set_resistance_btn.setEnabled(True)
            self.control_panel.set_cutoff_btn.setEnabled(True)
            self.control_panel.set_discharge_btn.setEnabled(True)

            # Re-enable preset current buttons (0.1A, 0.2A, 0.5A, 1.0A)
            for i in range(self.control_panel.preset_btns.count()):
                widget = self.control_panel.preset_btns.itemAt(i).widget()
                if widget:
                    widget.setEnabled(True)

            # Re-enable data logging controls
            self.status_panel.log_switch.setEnabled(True)
            self.status_panel.sample_time_combo.setEnabled(True)
            self.status_panel.battery_name_edit.setEnabled(True)

        # Re-enable test panel tabs (except WIP tabs which stay disabled)
        for i in range(self.bottom_tabs.count()):
            if i not in self._wip_tab_indices:
                self.bottom_tabs.setTabEnabled(i, True)

        # Re-enable input fields on all test panels
        for panel in [self.battery_capacity_panel, self.battery_load_panel,
                      self.battery_charger_panel,
                      self.charger_panel, self.power_bank_panel]:
            if hasattr(panel, 'set_inputs_enabled'):
                panel.set_inputs_enabled(True)

    def _setup_callbacks(self) -> None:
        """Setup device callbacks (called when device is created)."""
        # Callbacks are set when connecting to a device
        pass

    def _setup_device_callbacks(self, device) -> None:
        """Setup callbacks for a specific device."""
        device.set_status_callback(self._on_device_status)
        device.set_error_callback(self._on_device_error)
        device.set_debug_callback(self._on_device_debug)
        if hasattr(device, 'set_prepare_callback'):
            device.set_prepare_callback(self._on_prepare_needed)

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

        self.battery_capacity_toggle = QToolButton()
        self.battery_capacity_toggle.setArrowType(Qt.DownArrow)
        self.battery_capacity_toggle.setCheckable(True)
        self.battery_capacity_toggle.setChecked(True)
        self.battery_capacity_toggle.setStyleSheet("QToolButton { border: none; }")
        self.battery_capacity_toggle.clicked.connect(self._toggle_battery_capacity_panel)
        header_layout.addWidget(self.battery_capacity_toggle)

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

        self.battery_capacity_panel = BatteryCapacityPanel(None, self.database)  # test_runner set on connect
        cap_idx = self.bottom_tabs.addTab(self.battery_capacity_panel, "Battery Capacity")
        self.bottom_tabs.setTabToolTip(cap_idx, "Discharge test to measure battery capacity (mAh/Wh)")

        self.battery_load_panel = BatteryLoadPanel()
        load_idx = self.bottom_tabs.addTab(self.battery_load_panel, "Battery Load")
        self.bottom_tabs.setTabToolTip(load_idx, "Sweep current/power/resistance to characterize battery load response")

        self.battery_charger_panel = BatteryChargerPanel()
        charger_idx = self.bottom_tabs.addTab(self.battery_charger_panel, "Battery Charger")
        self.bottom_tabs.setTabToolTip(charger_idx, "Monitor and log battery charging sessions")

        self.charger_panel = ChargerPanel()
        wall_idx = self.bottom_tabs.addTab(self.charger_panel, "Wall Charger")
        self.bottom_tabs.setTabEnabled(wall_idx, False)
        self.bottom_tabs.setTabToolTip(wall_idx, "Under development")

        self.power_bank_panel = PowerBankPanel(None, self.database)  # test_runner set on connect
        powerbank_idx = self.bottom_tabs.addTab(self.power_bank_panel, "Power Bank")
        self.bottom_tabs.setTabEnabled(powerbank_idx, False)
        self.bottom_tabs.setTabToolTip(powerbank_idx, "Under development")

        # Track WIP tabs so they stay disabled at all times
        self._wip_tab_indices = {wall_idx, powerbank_idx}

        self.history_panel = HistoryPanel(self.database)
        self.history_panel.json_file_selected.connect(self._on_history_json_selected)
        history_idx = self.bottom_tabs.addTab(self.history_panel, "History")
        self.bottom_tabs.setTabToolTip(history_idx, "Browse and load saved test results")

        # Auto-refresh history panel when tab is activated
        self.bottom_tabs.currentChanged.connect(self._on_tab_changed)

        # Connect automation panel signals
        self.battery_capacity_panel.start_test_requested.connect(self._on_automation_start)
        self.battery_capacity_panel.pause_test_requested.connect(self._on_automation_pause)
        self.battery_capacity_panel.resume_test_requested.connect(self._on_automation_resume)
        self.battery_capacity_panel.apply_settings_requested.connect(self._on_apply_settings)
        self.battery_capacity_panel.manual_save_requested.connect(self._on_manual_save)
        self.battery_capacity_panel.session_loaded.connect(self._on_session_loaded)
        self.battery_capacity_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect battery load panel signals
        self.battery_load_panel.test_started.connect(self._on_battery_load_start)
        self.battery_load_panel.test_stopped.connect(self._on_battery_load_stop)
        self.battery_load_panel.manual_save_requested.connect(self._on_battery_load_save)
        self.battery_load_panel.session_loaded.connect(self._on_session_loaded)
        self.battery_load_panel.export_csv_requested.connect(self._on_export_csv)

        # Synchronize battery info between Battery Capacity and Battery Load panels
        # Both panels now use BatteryInfoWidget, so just sync the widgets
        self.battery_capacity_panel.battery_info_widget.settings_changed.connect(self._sync_battery_info_to_load)
        self.battery_load_panel.battery_info_widget.settings_changed.connect(self._sync_battery_info_to_capacity)

        # Synchronize battery preset lists - when one panel saves/deletes a preset, reload the other panel's list
        self.battery_capacity_panel.battery_info_widget.preset_list_changed.connect(self.battery_load_panel.reload_battery_presets)
        self.battery_load_panel.battery_info_widget.preset_list_changed.connect(self.battery_capacity_panel.reload_battery_presets)

        # Connect charger panel signals
        self.charger_panel.test_started.connect(self._on_charger_start)
        self.charger_panel.test_stopped.connect(self._on_charger_stop)
        self.charger_panel.manual_save_requested.connect(self._on_charger_save)
        self.charger_panel.session_loaded.connect(self._on_session_loaded)
        self.charger_panel.export_csv_requested.connect(self._on_export_csv)

        # Connect battery charger panel signals
        self.battery_charger_panel.test_initialized.connect(self._on_battery_charger_initialized)
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
        self.status_updated.connect(self.battery_charger_panel.update_device_status)
        self.connection_changed.connect(self._update_ui_connection)
        self.test_progress.connect(self.battery_capacity_panel.update_progress)
        self.error_occurred.connect(self._show_error_message)
        self.prepare_needed.connect(self._run_usb_prepare)

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

        test_viewer_action = QAction("Test &Viewer", self)
        test_viewer_action.triggered.connect(self._launch_test_viewer)
        tools_menu.addAction(test_viewer_action)

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

        help_action = QAction("&Test Bench Help", self)
        help_action.triggered.connect(self._show_help)
        help_menu.addAction(help_action)

        troubleshooting_action = QAction("Connection &Troubleshooting", self)
        troubleshooting_action.triggered.connect(self._show_connection_troubleshooting)
        help_menu.addAction(troubleshooting_action)

        help_menu.addSeparator()

        # Tooltips toggle
        self.tooltips_action = QAction("Show &Tooltips", self)
        self.tooltips_action.setCheckable(True)
        self.tooltips_action.setChecked(True)  # Default to enabled
        self.tooltips_action.toggled.connect(self._toggle_tooltips)
        help_menu.addAction(self.tooltips_action)

        help_menu.addSeparator()

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_system_tray(self) -> None:
        """Create system tray icon (menu bar icon on macOS)."""
        # Check if system tray is available
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        # Load menu bar icon
        icon_path = Path(__file__).parent.parent.parent / "resources" / "icons" / "menubar_icon_16.png"
        if not icon_path.exists():
            return

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(QIcon(str(icon_path)), self)
        self.tray_icon.setToolTip("DL24/P Test Bench")

        # Create context menu
        tray_menu = QMenu()

        # Show/Hide window action
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        hide_action = QAction("Hide Window", self)
        hide_action.triggered.connect(self.hide)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()

        # Quick connect/disconnect
        connect_action = QAction("Connect Device", self)
        connect_action.triggered.connect(self._connect_device)
        tray_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect Device", self)
        disconnect_action.triggered.connect(self._disconnect_device)
        tray_menu.addAction(disconnect_action)

        tray_menu.addSeparator()

        # Quit action
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)

        # Show the tray icon
        self.tray_icon.show()

    def _on_tray_icon_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click - toggle window visibility
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()

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
            self.battery_capacity_panel.test_runner = self.test_runner
            self.power_bank_panel.test_runner = self.test_runner

            # Set device and plot references for test panels
            self.battery_load_panel.set_device_and_plot(self.device, self.plot_panel)
            self.charger_panel.set_device_and_plot(self.device, self.plot_panel)
            self.battery_charger_panel.set_device_and_plot(self.device, self.plot_panel)

            self.connection_changed.emit(True)
            conn_type_str = "USB HID" if connection_type == ConnectionType.USB_HID else "Serial"
            self.statusbar.showMessage(f"Connected ({conn_type_str}) — trying to communicate with device...")
            self._awaiting_first_status = True
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
        self.battery_capacity_panel._update_ui_stopped()

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
    def _toggle_logging(self, enabled: bool, turn_on_load: bool = True) -> None:
        """Toggle manual data logging.

        Args:
            enabled: Whether to enable or disable logging
            turn_on_load: Whether to turn on the load when enabling (False for start delay)
        """
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
            self._update_test_complete_alert_state(True)  # Notify alert that test started
            self._disable_controls_during_test()  # Lock UI controls during test
            self._last_log_time = None  # Reset sample timer for new test
            self._last_autosave_time = None  # Reset autosave timer for new test
            self._last_db_commit_time = None  # Reset db commit timer for new test
            self._load_off_count = 0  # Reset load-off counter for new test
            import time as _time
            self._logging_started_at = _time.time()  # Grace period for load-off detection
            # Turn on the load when logging starts (unless delayed)
            if turn_on_load and self.device and self.device.is_connected:
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
            self._update_test_complete_alert_state(False)  # Notify alert that test stopped
            self._enable_controls_after_test()  # Unlock UI controls after test
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

        # Build test data structure using Reading.to_dict()
        readings_data = []
        for reading in readings:
            readings_data.append(reading.to_dict())

        # Calculate summary statistics
        if readings_data:
            final_reading = readings_data[-1]
            first_reading = readings_data[0]
            summary = {
                "total_readings": len(readings_data),
                "start_time": first_reading["timestamp"],
                "end_time": final_reading["timestamp"],
                "total_runtime_seconds": final_reading["runtime_s"],
            }

            # Add final values for non-battery-charger tests
            # Battery charger tests have multiple voltage steps, so final values aren't meaningful
            if test_panel_type != "battery_charger":
                summary["final_voltage"] = final_reading["voltage_v"]
                summary["final_capacity_mah"] = final_reading["capacity_mah"]
                summary["final_energy_wh"] = final_reading["energy_wh"]

            # Calculate battery resistance for battery load tests
            if test_panel_type == "battery_load" and len(readings_data) >= 2:
                try:
                    # Extract current (A) and voltage (V) data
                    currents = [r["current_a"] for r in readings_data]
                    voltages = [r["voltage_v"] for r in readings_data]

                    # Filter out zero current readings (if any)
                    valid_points = [(c, v) for c, v in zip(currents, voltages) if c > 0]

                    if len(valid_points) >= 2:
                        currents_filtered = [c for c, v in valid_points]
                        voltages_filtered = [v for c, v in valid_points]

                        # Calculate linear regression: V = V0 - I*R
                        # Using numpy polyfit (degree 1 for linear fit)
                        import numpy as np

                        # Fit: voltage = intercept + slope * current
                        # slope is negative of internal resistance
                        coeffs = np.polyfit(currents_filtered, voltages_filtered, 1)
                        slope = coeffs[0]  # dV/dI
                        intercept = coeffs[1]  # V at I=0

                        # Internal resistance is -slope (since V decreases as I increases)
                        battery_resistance = -slope

                        # Calculate R-squared
                        voltages_pred = np.polyval(coeffs, currents_filtered)
                        ss_res = np.sum((np.array(voltages_filtered) - voltages_pred) ** 2)
                        ss_tot = np.sum((np.array(voltages_filtered) - np.mean(voltages_filtered)) ** 2)
                        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

                        summary["battery_resistance_ohm"] = float(battery_resistance)
                        summary["resistance_r_squared"] = float(r_squared)
                except Exception as e:
                    # If calculation fails, don't add resistance values
                    print(f"Warning: Could not calculate battery resistance: {e}")
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
        test_config = self.battery_capacity_panel.get_test_config()
        battery_info = self.battery_capacity_panel.get_battery_info()

        # Use provided filename or get from automation panel
        if filename is None:
            filename = self.battery_capacity_panel.filename_edit.text().strip()
            if not filename:
                filename = self.battery_capacity_panel.generate_test_filename()

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

    def _launch_test_viewer(self) -> None:
        """Launch the Test Viewer application."""
        if getattr(sys, 'frozen', False):
            # In frozen builds, sys.executable is the app bundle — launch in-process
            self._launch_test_viewer_inprocess()
        else:
            self._launch_test_viewer_subprocess()

    def _launch_test_viewer_inprocess(self) -> None:
        """Launch the Test Viewer as an in-process window (for frozen builds)."""
        try:
            # If already open, just raise the window
            if hasattr(self, '_test_viewer_window') and self._test_viewer_window is not None:
                if self._test_viewer_window.isVisible():
                    self._test_viewer_window.raise_()
                    self._test_viewer_window.activateWindow()
                    return

            from ..viewer.main_window import ViewerMainWindow
            self._test_viewer_window = ViewerMainWindow()
            self._test_viewer_window.show()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to launch Test Viewer:\n{str(e)}"
            )

    def _launch_test_viewer_subprocess(self) -> None:
        """Launch the Test Viewer as a separate process (for dev/non-frozen)."""
        try:
            # Check if Test Viewer is already running
            if self._test_viewer_process is not None and self._test_viewer_process.poll() is None:
                # Process is still running, try to activate its window
                if sys.platform == 'darwin':
                    try:
                        activate_script = '''
                        tell application "System Events"
                            set processList to every process whose visible is true
                            repeat with proc in processList
                                try
                                    tell proc
                                        set windowList to every window
                                        repeat with win in windowList
                                            if name of win contains "Test Viewer" then
                                                set frontmost to true
                                                perform action "AXRaise" of win
                                                return
                                            end if
                                        end repeat
                                    end tell
                                end try
                            end repeat
                        end tell
                        '''
                        subprocess.run(['osascript', '-e', activate_script], check=False, timeout=2)
                    except Exception:
                        pass
                QMessageBox.information(
                    self,
                    "Test Viewer",
                    "Test Viewer is already running."
                )
                return

            # Launch Test Viewer as a separate process
            self._test_viewer_process = subprocess.Popen([sys.executable, "-m", "atorch.viewer"])
        except Exception as e:
            QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to launch Test Viewer:\n{str(e)}"
            )

    @Slot()
    def _show_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About DL24/P Test Bench",
            "<h2>DL24/P Test Bench</h2>"
            "<p><b>Version 1.0.0</b></p>"
            "<p>Test automation suite for the aTorch DL24P electronic load.</p>"
            "<p>Features:</p>"
            "<ul>"
            "<li>Battery Capacity — discharge testing with mAh/Wh measurement</li>"
            "<li>Battery Load — voltage vs. load characterization</li>"
            "<li>Battery Charger — CC-CV charging profile analysis</li>"
            "<li>Real-time plotting with configurable axes</li>"
            "<li>Preset management and session persistence</li>"
            "<li>JSON, CSV, and Excel export</li>"
            "<li>SQLite database storage with history browser</li>"
            "</ul>"
            "<p style='color: #888;'>Wall Charger and Power Bank tests are under development.</p>"
            "<p>© 2026 • Built with PySide6 and pyqtgraph</p>"
            "<p>For help, see <b>Help → Test Bench Help</b></p>",
        )

    @Slot(bool)
    def _toggle_tooltips(self, enabled: bool) -> None:
        """Toggle tooltips on/off throughout the application.

        Args:
            enabled: True to show tooltips, False to hide them
        """
        # Save preference
        self._save_tooltip_preference(enabled)

        # Apply to all controls
        self._set_tooltips_enabled(enabled)

    def _save_tooltip_preference(self, enabled: bool) -> None:
        """Save tooltip preference to settings file.

        Args:
            enabled: True if tooltips are enabled
        """
        settings_file = Path.home() / ".atorch" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing settings or create new
        settings = {}
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
            except Exception:
                pass

        # Update tooltip preference
        settings["tooltips_enabled"] = enabled

        # Save settings
        try:
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass

    def _load_tooltip_preference(self) -> bool:
        """Load tooltip preference from settings file.

        Returns:
            True if tooltips should be enabled (default), False otherwise
        """
        settings_file = Path.home() / ".atorch" / "settings.json"

        if not settings_file.exists():
            return True  # Default to enabled

        try:
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                return settings.get("tooltips_enabled", True)
        except Exception:
            return True  # Default to enabled on error

    def _set_tooltips_enabled(self, enabled: bool) -> None:
        """Enable or disable all tooltips in the application.

        Args:
            enabled: True to show tooltips, False to hide them
        """
        # Control Panel
        for widget in [
            self.control_panel.port_combo,
            self.control_panel.refresh_btn,
            self.control_panel.connect_btn,
            self.control_panel.disconnect_btn,
            self.control_panel.debug_log_checkbox,
            self.control_panel.cc_btn,
            self.control_panel.cp_btn,
            self.control_panel.cv_btn,
            self.control_panel.cr_btn,
            self.control_panel.power_switch,
            self.control_panel.current_spin,
            self.control_panel.set_current_btn,
            self.control_panel.power_spin,
            self.control_panel.set_power_btn,
            self.control_panel.voltage_spin,
            self.control_panel.set_voltage_btn,
            self.control_panel.resistance_spin,
            self.control_panel.set_resistance_btn,
            self.control_panel.cutoff_spin,
            self.control_panel.set_cutoff_btn,
            self.control_panel.discharge_hours_spin,
            self.control_panel.discharge_mins_spin,
            self.control_panel.set_discharge_btn,
        ]:
            if enabled:
                # Restore original tooltip (stored in whatsThis)
                widget.setToolTip(widget.whatsThis() if widget.whatsThis() else widget.toolTip())
            else:
                # Save current tooltip to whatsThis and clear tooltip
                if widget.toolTip() and not widget.whatsThis():
                    widget.setWhatsThis(widget.toolTip())
                widget.setToolTip("")

        # Preset current buttons
        for i in range(self.control_panel.preset_btns.count()):
            widget = self.control_panel.preset_btns.itemAt(i).widget()
            if widget:
                if enabled:
                    widget.setToolTip(widget.whatsThis() if widget.whatsThis() else widget.toolTip())
                else:
                    if widget.toolTip() and not widget.whatsThis():
                        widget.setWhatsThis(widget.toolTip())
                    widget.setToolTip("")

        # Status Panel
        for widget in [
            self.status_panel.log_switch,
            self.status_panel.sample_time_combo,
            self.status_panel.battery_name_edit,
            self.status_panel.save_btn,
            self.status_panel.clear_log_btn,
            self.status_panel.clear_btn,
        ]:
            if enabled:
                widget.setToolTip(widget.whatsThis() if widget.whatsThis() else widget.toolTip())
            else:
                if widget.toolTip() and not widget.whatsThis():
                    widget.setWhatsThis(widget.toolTip())
                widget.setToolTip("")

    @Slot()
    def _show_help(self) -> None:
        """Show comprehensive help documentation."""
        dialog = QDialog(self)
        dialog.setWindowTitle("DL24/P Test Bench Help")
        dialog.resize(900, 700)

        layout = QVBoxLayout(dialog)

        # Create text browser for scrollable HTML content
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(self._get_help_html())
        layout.addWidget(browser)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    @Slot()
    def _show_connection_troubleshooting(self) -> None:
        """Show USB connection troubleshooting help."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Connection Troubleshooting")
        dialog.resize(700, 600)

        layout = QVBoxLayout(dialog)

        # Create text browser for scrollable HTML content
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(self._get_troubleshooting_html())
        layout.addWidget(browser)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def _get_troubleshooting_html(self) -> str:
        """Get USB connection troubleshooting documentation as HTML.

        Returns:
            HTML string with troubleshooting information
        """
        return """
        <html>
        <head>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.6; padding: 15px; }
                h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                h2 { color: #34495e; margin-top: 20px; border-bottom: 1px solid #bdc3c7; padding-bottom: 5px; }
                h3 { color: #7f8c8d; margin-top: 15px; }
                .problem { background-color: #f8d7da; border-left: 4px solid #dc3545; padding: 10px; margin: 10px 0; }
                .solution { background-color: #d4edda; border-left: 4px solid #28a745; padding: 10px; margin: 10px 0; }
                .note { background-color: #d1ecf1; border-left: 4px solid #17a2b8; padding: 10px; margin: 10px 0; }
                ul { margin-left: 20px; }
                li { margin: 8px 0; }
                code { background-color: #ecf0f1; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
            </style>
        </head>
        <body>
            <h1>USB Connection Troubleshooting</h1>

            <h2>Problem: Live Readings Stop Updating</h2>
            <div class="problem">
                <strong>Symptom:</strong> The device is connected and can be controlled (load on/off works),
                but Live Readings (voltage, current, power) stop updating.
            </div>

            <h3>Root Cause</h3>
            <p>This is a <strong>known issue with macOS USB HID drivers</strong>, particularly when:</p>
            <ul>
                <li>The Mac goes to sleep or the display turns off</li>
                <li>macOS suspends USB devices for power management</li>
                <li>The USB HID driver enters a stuck state where commands are sent but responses aren't received</li>
            </ul>

            <h3>Solutions (Try in Order)</h3>

            <div class="solution">
                <strong>1. Click the Reset Button</strong>
                <ul>
                    <li>Click the <code>Reset</code> button next to the Disconnect button</li>
                    <li>This disconnects and reconnects after a 2-second delay</li>
                    <li>Works in some cases, but not always due to macOS driver limitations</li>
                </ul>
            </div>

            <div class="solution">
                <strong>2. Manual Disconnect/Reconnect</strong>
                <ul>
                    <li>Click <code>Disconnect</code></li>
                    <li>Wait 2-3 seconds</li>
                    <li>Click <code>Connect</code></li>
                    <li>Same as Reset button, but with manual control over timing</li>
                </ul>
            </div>

            <div class="solution">
                <strong>3. Unplug and Replug USB Cable (Most Reliable)</strong>
                <ul>
                    <li>Physically unplug the USB cable from the DL24P or computer</li>
                    <li>Wait 2-3 seconds</li>
                    <li>Plug it back in</li>
                    <li>Click <code>Connect</code> in the app</li>
                    <li><strong>This is the most reliable solution</strong> for stuck USB HID states</li>
                </ul>
            </div>

            <h3>Why Software Reset Doesn't Always Work</h3>
            <p>Research shows this is a limitation of the hidapi library and macOS USB HID drivers:</p>
            <ul>
                <li><strong>macOS Power Management:</strong> When the Mac sleeps, USB devices may not properly wake up
                    (<a href="https://kb.plugable.com/docking-stations-and-video/devices-are-not-detected-after-waking-from-sleep-or-after-rebooting-on-macos">Plugable KB Article</a>)</li>
                <li><strong>HID Driver State:</strong> The IOHIDDevice can get stuck in a state where closing and reopening
                    doesn't clear pending operations (<a href="https://github.com/libusb/hidapi/issues/171">hidapi Issue #171</a>)</li>
                <li><strong>No Reset Function:</strong> There's no programmatic way to reset IOHIDDevice state - physical
                    disconnect is required (<a href="https://github.com/signal11/hidapi/issues/114">hidapi Issue #114</a>)</li>
            </ul>

            <h3>Prevention Tips</h3>
            <div class="note">
                <ul>
                    <li><strong>Prevent Mac Sleep:</strong> System Settings → Battery → Prevent automatic sleeping when display is off</li>
                    <li><strong>Use a USB Hub:</strong> Some users report better reliability with powered USB hubs</li>
                    <li><strong>Avoid USB-C Adapters:</strong> Direct USB-A connection may be more stable</li>
                    <li><strong>Keep App Active:</strong> Minimize display sleep timeout while running tests</li>
                </ul>
            </div>

            <h2>Other Connection Issues</h2>

            <h3>Device Not Found</h3>
            <ul>
                <li>Check USB cable is fully inserted</li>
                <li>Try a different USB port</li>
                <li>Verify device powers on (screen shows readings)</li>
                <li>Check that no other app is using the device</li>
            </ul>

            <h3>Connection Error</h3>
            <ul>
                <li>Close any other apps that might be using the DL24P</li>
                <li>Restart the Test Bench app</li>
                <li>Try unplugging/replugging USB cable</li>
            </ul>

            <h3>Debug Logging</h3>
            <p>Enable <strong>Debug Log</strong> checkbox in the Control Panel to see detailed USB communication
            in <code>debug.log</code>. Look for "No response received" warnings to confirm the stuck state issue.</p>
        </body>
        </html>
        """

    def _get_help_html(self) -> str:
        """Get comprehensive help documentation as HTML.

        Returns:
            HTML string with full documentation
        """
        return """
        <html>
        <head>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                    line-height: 1.7; color: #1a1a2e; padding: 20px;
                }
                h1 {
                    color: #16213e; font-size: 26px; font-weight: 700;
                    border-bottom: 3px solid #3b82f6; padding-bottom: 12px; margin-bottom: 20px;
                }
                h2 {
                    color: #1e3a5f; font-size: 20px; font-weight: 600;
                    margin-top: 28px; padding: 8px 12px;
                    background: linear-gradient(135deg, #eff6ff, #f0f9ff);
                    border-left: 4px solid #3b82f6; border-radius: 4px;
                }
                h3 {
                    color: #334155; font-size: 16px; font-weight: 600; margin-top: 18px;
                }
                code {
                    background-color: #f1f5f9; padding: 2px 6px; border-radius: 4px;
                    font-family: 'SF Mono', Menlo, monospace; font-size: 13px; color: #334155;
                }
                .callout {
                    padding: 12px 16px; margin: 14px 0; border-radius: 8px;
                    font-size: 14px; line-height: 1.5;
                }
                .warning {
                    background-color: #fef2f2; border-left: 4px solid #ef4444; color: #991b1b;
                }
                .tip {
                    background-color: #f0fdf4; border-left: 4px solid #22c55e; color: #166534;
                }
                .note {
                    background-color: #fffbeb; border-left: 4px solid #f59e0b; color: #92400e;
                }
                .info {
                    background-color: #eff6ff; border-left: 4px solid #3b82f6; color: #1e40af;
                }
                .wip {
                    background-color: #f5f5f5; border-left: 4px solid #9ca3af; color: #6b7280;
                    font-style: italic;
                }
                ul { margin-left: 16px; padding-left: 8px; }
                li { margin: 6px 0; }
                ol li { margin: 8px 0; }
                b { color: #1e293b; }
                a { color: #3b82f6; }
                table {
                    border-collapse: collapse; margin: 12px 0; width: 100%;
                }
                th {
                    background: #f1f5f9; padding: 8px 12px; text-align: left;
                    border-bottom: 2px solid #cbd5e1; font-weight: 600; font-size: 13px;
                }
                td {
                    padding: 6px 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px;
                }
                .section-divider {
                    border: none; border-top: 1px solid #e2e8f0; margin: 28px 0;
                }
            </style>
        </head>
        <body>
            <h1>DL24/P Test Bench Help</h1>

            <h2>Getting Started</h2>

            <h3>Connecting to the DL24P</h3>
            <ol>
                <li>Connect the DL24P to your computer via USB</li>
                <li>The app auto-detects the device — click <b>Connect</b> in the Control Panel</li>
                <li>The status bar shows connection state and live voltage once communication is established</li>
            </ol>

            <div class="callout note">
                <b>macOS note:</b> After power-cycling the DL24P, the app may prompt for your password
                to send a one-time USB reset command. This is normal and only needed once per power cycle.
            </div>

            <h3>Basic Controls</h3>
            <p>The Control Panel provides manual control of the electronic load:</p>
            <ul>
                <li><b>Mode:</b> CC (Constant Current), CP (Constant Power), CV (Constant Voltage), CR (Constant Resistance)</li>
                <li><b>Value:</b> Set the load value for the selected mode</li>
                <li><b>Voltage Cutoff:</b> Minimum voltage before the load automatically turns off</li>
                <li><b>Load On/Off:</b> Toggle the electronic load</li>
            </ul>

            <div class="callout warning">
                <b>Important:</b> Always set an appropriate voltage cutoff when testing batteries to prevent over-discharge damage.
            </div>

            <hr class="section-divider">

            <h2>Test Panels</h2>

            <h3>Battery Capacity</h3>
            <p>Discharges a battery at constant current and measures total capacity (mAh) and energy (Wh).</p>
            <ul>
                <li><b>Discharge Current:</b> Constant current draw (e.g., 1.0A)</li>
                <li><b>Voltage Cutoff:</b> Stop voltage (e.g., 3.0V for Li-Ion)</li>
                <li><b>Time Limit:</b> Optional maximum test duration</li>
                <li><b>Battery Info:</b> Document the battery name, chemistry, rated capacity, etc.</li>
            </ul>
            <p><b>Use for:</b> Measuring actual capacity, verifying specs, comparing brands, tracking degradation.</p>

            <div class="callout tip">
                <b>Tip:</b> Use presets for common battery types (Canon, Nikon, Eneloop, etc.) to quickly set up tests.
                Use 0.5C or lower discharge rate for the most accurate capacity readings.
            </div>

            <h3>Battery Load</h3>
            <p>Steps through load levels to characterize how battery voltage responds under different loads.</p>
            <ul>
                <li><b>Load Type:</b> Current, Power, or Resistance sweep</li>
                <li><b>Min/Max:</b> Load range to test (e.g., 0.5A to 3A)</li>
                <li><b>Steps:</b> Number of measurement points</li>
                <li><b>Dwell Time:</b> Settling time at each level for stable readings</li>
            </ul>
            <p><b>Use for:</b> Measuring internal resistance, evaluating high-drain performance, comparing battery health.</p>

            <h3>Battery Charger</h3>
            <p>Simulates battery voltage levels using CV mode and measures the charger's current output,
            revealing the CC-CV charging profile.</p>
            <ul>
                <li><b>Chemistry:</b> Determines voltage range (Li-Ion 1S/2S/3S, NiMH, LiFePO4)</li>
                <li><b>Voltage Range:</b> Simulated battery voltage from depleted to full</li>
                <li><b>Steps / Dwell:</b> Resolution and settling time</li>
            </ul>
            <p><b>Setup:</b> Connect charger output to DL24P input. The DL24P acts as a simulated battery.</p>
            <p><b>Use for:</b> Verifying charger specs, comparing charging profiles, identifying counterfeits.</p>

            <div class="callout wip">
                <b>Coming soon:</b> Wall Charger and Power Bank test panels are under development.
            </div>

            <hr class="section-divider">

            <h2>Plots &amp; Live Data</h2>

            <h3>Real-Time Plots</h3>
            <p>The Plot Panel displays live data with up to 4 configurable axes:</p>
            <ul>
                <li><b>Y (left axis):</b> Primary parameter</li>
                <li><b>Y1, Y2, Y3 (right axes):</b> Additional parameters with independent scales</li>
                <li><b>X axis:</b> Time, Capacity, Energy, or any measured parameter</li>
            </ul>
            <p><b>Parameters:</b> Voltage, Current, Power, Load R, Battery R, MOSFET Temp, External Temp, Capacity, Energy</p>
            <p>Features auto-scaling with SI prefixes, adjustable time windows (30s to All), interactive zoom/pan, and point markers.</p>

            <h3>Status Panel</h3>
            <p>Displays live readings: voltage, current, power, capacity (mAh), energy (Wh),
            MOSFET and external temperatures, fan speed, load and battery resistance, and elapsed time.</p>

            <hr class="section-divider">

            <h2>Data Management</h2>

            <h3>Logging</h3>
            <ul>
                <li>Toggle with the <b>Log Data</b> switch in the Status Panel</li>
                <li>Records at 1 Hz to both SQLite database and in-memory buffer (last 48 hours)</li>
            </ul>

            <h3>Saving &amp; Exporting</h3>
            <ul>
                <li><b>Auto-save:</b> Enable in test panels — saves JSON when test completes</li>
                <li><b>Manual save:</b> Click <b>Save</b> for a custom filename</li>
                <li><b>Export:</b> CSV and Excel formats available</li>
                <li><b>Location:</b> <code>~/.atorch/test_data/</code></li>
            </ul>

            <h3>History Panel</h3>
            <p>Browse and reload saved test data. Click any file to load it into the plot and test panel.
            Use <b>Show Folder</b> to open the data directory.</p>

            <h3>Database Management</h3>
            <p>Access via <b>Tools → Database Management</b> to view statistics or purge old data.</p>

            <div class="callout warning">
                <b>Warning:</b> Database purge is permanent. Exported JSON/CSV files are not affected.
            </div>

            <hr class="section-divider">

            <h2>Presets</h2>
            <ul>
                <li><b>Battery presets:</b> Common batteries with chemistry, voltage, and capacity pre-filled (Canon, Nikon, Sony, Eneloop, etc.)</li>
                <li><b>Test presets:</b> Pre-configured test parameters for common scenarios</li>
                <li>Save your own with <b>Save</b>, delete user presets with <b>Delete</b></li>
                <li>Default presets cannot be deleted</li>
            </ul>

            <hr class="section-divider">

            <h2>Settings</h2>

            <table>
                <tr><th>Setting</th><th>Location</th><th>Description</th></tr>
                <tr><td>Auto-connect</td><td>File → Settings</td><td>Connect to DL24P automatically on startup</td></tr>
                <tr><td>Backlight</td><td>Device → Settings</td><td>Screen brightness and standby timeout</td></tr>
                <tr><td>Counter Reset</td><td>Device → Settings</td><td>Clear mAh, Wh, and time counters on device</td></tr>
                <tr><td>Factory Reset</td><td>Device → Settings</td><td>Restore device to default settings</td></tr>
                <tr><td>Tooltips</td><td>Help → Show Tooltips</td><td>Toggle hover help throughout the app</td></tr>
            </table>

            <hr class="section-divider">

            <h2>Battery Chemistry Reference</h2>

            <table>
                <tr><th>Chemistry</th><th>Nominal V</th><th>Cutoff V</th><th>Full V</th></tr>
                <tr><td>Li-Ion / LiPo</td><td>3.7V</td><td>2.5–3.0V</td><td>4.2V</td></tr>
                <tr><td>LiFePO4</td><td>3.2V</td><td>2.5V</td><td>3.65V</td></tr>
                <tr><td>NiMH</td><td>1.2V</td><td>0.9–1.0V</td><td>1.45V</td></tr>
                <tr><td>NiCd</td><td>1.2V</td><td>0.9–1.0V</td><td>1.45V</td></tr>
                <tr><td>Lead Acid</td><td>2.0V/cell</td><td>1.75V/cell</td><td>2.4V/cell</td></tr>
            </table>

            <hr class="section-divider">

            <h2>Troubleshooting</h2>

            <h3>Device won't connect</h3>
            <ul>
                <li>Check USB cable is fully seated — try a different cable or port</li>
                <li>Verify the DL24P screen is on and showing readings</li>
                <li>Close any other apps that might be using the device</li>
                <li>See <b>Help → Connection Troubleshooting</b> for USB-specific issues</li>
            </ul>

            <h3>Readings stop updating</h3>
            <ul>
                <li>macOS may suspend USB devices during sleep — unplug and replug the cable</li>
                <li>Use <b>Reset</b> button or disconnect/reconnect</li>
                <li>Keep display sleep disabled during long tests</li>
            </ul>

            <h3>Test stops prematurely</h3>
            <ul>
                <li>Voltage cutoff was reached (check the plot)</li>
                <li>Time limit expired</li>
                <li>DL24P overheated (check MOSFET temperature — device has thermal protection)</li>
            </ul>

            <hr class="section-divider">

            <h2>Technical Specifications</h2>

            <table>
                <tr><th>Parameter</th><th>Value</th></tr>
                <tr><td>Voltage range</td><td>0–30V</td></tr>
                <tr><td>Current range</td><td>0–24A</td></tr>
                <tr><td>Power (max)</td><td>150W (with active cooling)</td></tr>
                <tr><td>Modes</td><td>CC, CP, CV, CR</td></tr>
                <tr><td>Resolution</td><td>10mV, 10mA</td></tr>
                <tr><td>Connection</td><td>USB HID (no drivers needed)</td></tr>
                <tr><td>Logging rate</td><td>1 Hz</td></tr>
                <tr><td>Database</td><td>SQLite 3</td></tr>
                <tr><td>Export formats</td><td>JSON, CSV, Excel</td></tr>
            </table>

            <hr class="section-divider">

            <h2>File Locations</h2>

            <table>
                <tr><th>Content</th><th>Path</th></tr>
                <tr><td>User data</td><td><code>~/.atorch/</code></td></tr>
                <tr><td>Test results</td><td><code>~/.atorch/test_data/</code></td></tr>
                <tr><td>Database</td><td><code>~/.atorch/tests.db</code></td></tr>
                <tr><td>Session state</td><td><code>~/.atorch/*_session.json</code></td></tr>
                <tr><td>User presets</td><td><code>~/.atorch/*_presets/</code></td></tr>
            </table>

            <hr class="section-divider">

            <p style="text-align: center; color: #94a3b8; font-size: 13px; margin-top: 24px;">
                DL24/P Test Bench v1.0.0 &nbsp;·&nbsp; Built with PySide6 and pyqtgraph<br>
                <a href="https://github.com/nevetssf/aTorch-DL24P" style="color: #64748b;">github.com/nevetssf/aTorch-DL24P</a>
            </p>
        </body>
        </html>
        """

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
            "charger": 3,
            "power_bank": 4,
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
        self.battery_capacity_panel._loading_settings = True
        try:
            test_config = data.get("test_config", {})
            if "discharge_type_index" in test_config:
                self.battery_capacity_panel.type_combo.setCurrentIndex(test_config["discharge_type_index"])
            elif "discharge_type" in test_config:
                type_map = {"CC": 0, "CP": 1, "CR": 2}
                self.battery_capacity_panel.type_combo.setCurrentIndex(type_map.get(test_config["discharge_type"], 0))
            if "value" in test_config:
                self.battery_capacity_panel.value_spin.setValue(test_config["value"])
            if "voltage_cutoff" in test_config:
                self.battery_capacity_panel.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.battery_capacity_panel.timed_checkbox.setChecked(test_config["timed"])
            if "duration_seconds" in test_config:
                self.battery_capacity_panel.duration_spin.setValue(test_config["duration_seconds"])

            # Load battery info
            battery_info = data.get("battery_info", {})
            if battery_info:
                self.battery_capacity_panel.set_battery_info(battery_info)

            # Update filename
            self.battery_capacity_panel.filename_edit.setText(Path(file_path).name)

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
                self.battery_capacity_panel._update_summary_from_readings(readings)

            self.statusbar.showMessage(f"Loaded Battery Capacity test: {Path(file_path).name}")

        finally:
            self.battery_capacity_panel._loading_settings = False

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

                # Calculate and update Test Summary
                summary = data.get("summary", {})
                resistance_ohm = summary.get("battery_resistance_ohm")
                r_squared = summary.get("resistance_r_squared")

                # If resistance not in file, calculate it now
                if resistance_ohm is None and len(readings) >= 2:
                    try:
                        import numpy as np
                        # Extract current and voltage data
                        currents = [r.get("current_a", 0) for r in readings]
                        voltages = [r.get("voltage_v", 0) for r in readings]

                        # Filter out zero current readings
                        valid_points = [(c, v) for c, v in zip(currents, voltages) if c > 0]

                        if len(valid_points) >= 2:
                            currents_filtered = [c for c, v in valid_points]
                            voltages_filtered = [v for c, v in valid_points]

                            # Linear fit: voltage = intercept + slope * current
                            coeffs = np.polyfit(currents_filtered, voltages_filtered, 1)
                            slope = coeffs[0]
                            resistance_ohm = -slope  # Internal resistance is -slope

                            # Calculate R-squared
                            voltages_pred = np.polyval(coeffs, currents_filtered)
                            ss_res = np.sum((np.array(voltages_filtered) - voltages_pred) ** 2)
                            ss_tot = np.sum((np.array(voltages_filtered) - np.mean(voltages_filtered)) ** 2)
                            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

                            # Update the JSON file with calculated values
                            if "summary" not in data:
                                data["summary"] = {}
                            data["summary"]["battery_resistance_ohm"] = float(resistance_ohm)
                            data["summary"]["resistance_r_squared"] = float(r_squared)

                            try:
                                with open(file_path, 'w') as f:
                                    json.dump(data, f, indent=2)
                            except Exception as e:
                                print(f"Warning: Could not update JSON file with resistance: {e}")
                    except Exception as e:
                        print(f"Warning: Could not calculate battery resistance: {e}")

                # Update Test Summary table
                runtime_s = summary.get("total_runtime_seconds", 0)
                if not runtime_s and readings:
                    runtime_s = int(readings[-1].get("runtime_s", 0))

                self.battery_load_panel.update_test_summary(
                    runtime_s=runtime_s,
                    load_type=test_config.get("load_type", "Current"),
                    min_val=test_config.get("min", 0),
                    max_val=test_config.get("max", 0),
                    resistance_ohm=resistance_ohm,
                    r_squared=r_squared
                )

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
            if "notes" in charger_info:
                self.battery_charger_panel.charger_notes_edit.setPlainText(charger_info["notes"])

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

    @Slot()
    def _sync_battery_info_on_startup(self) -> None:
        """Sync battery info on startup using most recently modified session file."""
        atorch_dir = Path.home() / ".atorch"
        capacity_session = atorch_dir / "battery_capacity_session.json"
        load_session = atorch_dir / "battery_load_session.json"

        # Determine which session file was modified most recently
        capacity_mtime = capacity_session.stat().st_mtime if capacity_session.exists() else 0
        load_mtime = load_session.stat().st_mtime if load_session.exists() else 0

        # Sync from the more recently modified session file
        if capacity_mtime >= load_mtime:
            # Battery Capacity is more recent, sync to Battery Load
            self._sync_battery_info_to_load()
        else:
            # Battery Load is more recent, sync to Battery Capacity
            self._sync_battery_info_to_capacity()

    def _sync_battery_info_to_load(self) -> None:
        """Sync battery info from Battery Capacity panel to Battery Load panel."""
        # Avoid sync loops - check if battery load panel is currently loading settings
        if not self.battery_load_panel._loading_settings:
            battery_info = self.battery_capacity_panel.get_battery_info()
            self.battery_load_panel.battery_info_widget.set_battery_info(battery_info)

            # Also sync the preset dropdown selection
            preset_name = self.battery_capacity_panel.battery_info_widget.presets_combo.currentText()
            if preset_name and not preset_name.startswith("---"):
                # Find matching preset in battery load panel
                index = self.battery_load_panel.battery_info_widget.presets_combo.findText(preset_name)
                if index >= 0:
                    # Temporarily block signals to avoid triggering another sync
                    self.battery_load_panel.battery_info_widget.presets_combo.blockSignals(True)
                    self.battery_load_panel.battery_info_widget.presets_combo.setCurrentIndex(index)
                    self.battery_load_panel.battery_info_widget.presets_combo.blockSignals(False)

    @Slot()
    def _sync_battery_info_to_capacity(self) -> None:
        """Sync battery info from Battery Load panel to Battery Capacity panel."""
        # Avoid sync loops - check if automation panel is currently loading settings
        if not self.battery_capacity_panel._loading_settings:
            battery_info = self.battery_load_panel.battery_info_widget.get_battery_info()
            self.battery_capacity_panel.set_battery_info(battery_info)

            # Also sync the preset dropdown selection
            preset_name = self.battery_load_panel.battery_info_widget.presets_combo.currentText()
            if preset_name and not preset_name.startswith("---"):
                # Find matching preset in automation panel
                index = self.battery_capacity_panel.battery_info_widget.presets_combo.findText(preset_name)
                if index >= 0:
                    # Temporarily block signals to avoid triggering another sync
                    self.battery_capacity_panel.battery_info_widget.presets_combo.blockSignals(True)
                    self.battery_capacity_panel.battery_info_widget.presets_combo.setCurrentIndex(index)
                    self.battery_capacity_panel.battery_info_widget.presets_combo.blockSignals(False)

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
            # Cancel start delay timer if active
            if hasattr(self, '_start_delay_timer') and self._start_delay_timer is not None:
                self._start_delay_timer.stop()
                self._start_delay_timer.deleteLater()
                self._start_delay_timer = None
            # Stop request - save data and turn off logging
            if self._logging_enabled:
                num_readings = len(self._accumulated_readings)
                # Save test data to JSON if auto-save is enabled
                if self.battery_capacity_panel.autosave_checkbox.isChecked():
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
        mode_names = {0: "CC", 2: "CR"}
        if discharge_type == 0:  # Constant Current
            self.control_panel.mode_btn_group.button(0).setChecked(True)  # CC button
            self.control_panel.current_spin.setValue(value)
            self.device.set_current(value)
            mode_str = f"{value}A"
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

        # Get start delay from panel
        start_delay = self.battery_capacity_panel.start_delay_spin.value()

        # Start logging
        if not self._logging_enabled:
            self.status_panel.log_switch.setChecked(True)
            if start_delay > 0:
                # Start logging without turning on load (capture unloaded voltage)
                self._toggle_logging(True, turn_on_load=False)
                # Set up countdown timer to turn on load after delay
                self._start_delay_remaining = start_delay
                self.battery_capacity_panel.update_start_delay_countdown(start_delay)
                self._start_delay_timer = QTimer(self)
                self._start_delay_timer.timeout.connect(self._on_start_delay_tick)
                self._start_delay_timer.start(1000)
                self.statusbar.showMessage(
                    f"Test started: {mode_names[discharge_type]} {mode_str}, cutoff {voltage_cutoff}V "
                    f"(load on in {start_delay}s)"
                )
            else:
                self._toggle_logging(True)
                self.statusbar.showMessage(
                    f"Test started: {mode_names[discharge_type]} {mode_str}, cutoff {voltage_cutoff}V"
                )

    @Slot()
    def _on_start_delay_tick(self) -> None:
        """Handle start delay countdown tick (called every 1s)."""
        self._start_delay_remaining -= 1
        if self._start_delay_remaining <= 0:
            # Delay complete - turn on the load
            self._start_delay_timer.stop()
            self._start_delay_timer.deleteLater()
            self._start_delay_timer = None
            if self.device and self.device.is_connected:
                self.device.turn_on()
                self.control_panel.power_switch.setChecked(True)
            # Reset grace period start so load-off detection starts fresh
            import time as _time
            self._logging_started_at = _time.time()
            self.battery_capacity_panel.status_label.setText("Running")
            self.battery_capacity_panel.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.statusbar.showMessage("Load turned on")
        else:
            # Update countdown
            self.battery_capacity_panel.update_start_delay_countdown(self._start_delay_remaining)

    @Slot()
    def _on_automation_pause(self) -> None:
        """Handle pause request from automation panel - stop logging and load, keep data."""
        # Stop logging (but don't clear data)
        if self._logging_enabled:
            self._current_session.end_time = datetime.now()
            self.database.update_session(self._current_session)
            self._current_session = None
            self._logging_enabled = False
            self._update_test_complete_alert_state(False)  # Notify alert that test paused
            self._enable_controls_after_test()  # Unlock UI controls when paused
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
            self._update_test_complete_alert_state(True)  # Notify alert that test resumed
            self._disable_controls_during_test()  # Lock UI controls during resumed test
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

            # Calculate resistance before saving/displaying
            resistance_ohm = None
            r_squared = None
            if len(self._accumulated_readings) >= 2:
                try:
                    import numpy as np
                    # Extract current and voltage data
                    currents = [r.current_a for r in self._accumulated_readings]
                    voltages = [r.voltage_v for r in self._accumulated_readings]

                    # Filter out zero current readings
                    valid_points = [(c, v) for c, v in zip(currents, voltages) if c > 0]

                    if len(valid_points) >= 2:
                        currents_filtered = [c for c, v in valid_points]
                        voltages_filtered = [v for c, v in valid_points]

                        # Linear fit: voltage = intercept + slope * current
                        coeffs = np.polyfit(currents_filtered, voltages_filtered, 1)
                        slope = coeffs[0]
                        resistance_ohm = -slope  # Internal resistance is -slope

                        # Calculate R-squared
                        voltages_pred = np.polyval(coeffs, currents_filtered)
                        ss_res = np.sum((np.array(voltages_filtered) - voltages_pred) ** 2)
                        ss_tot = np.sum((np.array(voltages_filtered) - np.mean(voltages_filtered)) ** 2)
                        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
                except Exception as e:
                    print(f"Warning: Could not calculate battery resistance: {e}")

            # Get test parameters
            test_config = self.battery_load_panel.get_test_config()
            runtime_s = int(self._accumulated_readings[-1].runtime_s) if self._accumulated_readings else 0

            # Update summary table
            self.battery_load_panel.update_test_summary(
                runtime_s=runtime_s,
                load_type=test_config["load_type"],
                min_val=test_config["min"],
                max_val=test_config["max"],
                resistance_ohm=resistance_ohm,
                r_squared=r_squared
            )

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
    def _on_battery_charger_initialized(self) -> None:
        """Handle test initialization from battery charger panel.

        This is called when the user clicks Start, BEFORE the settle phase begins.
        This is where we clear accumulated data and reset counters.
        """
        # Auto-connect if DL24 device detected and not connected
        if not self.device or not self.device.is_connected:
            if not self._try_auto_connect():
                return

        # Clear accumulated data and reset counters BEFORE test begins
        self.plot_panel.clear_data()
        self.status_panel.clear_logging_time()
        self.status_panel.set_points_count(0)
        self._accumulated_readings.clear()
        self._last_completed_session = None
        # Reset device counters (mAh, Wh, time)
        self.device.reset_counters()
        # Lock UI controls during test
        self._disable_controls_during_test()

    @Slot()
    def _on_battery_charger_start(self) -> None:
        """Handle logging start from battery charger panel.

        This is called when the settle phase completes and logging should begin.
        Data has already been cleared in _on_battery_charger_initialized.
        """
        # Start logging WITHOUT turning on load (panel controls load)
        if not self._logging_enabled:
            self._logging_enabled = True
            self._logging_start_time = datetime.now()
            self._current_session = TestSession(
                name=f"Battery Charger Test {self._logging_start_time.strftime('%Y-%m-%d %H:%M')}",
                start_time=self._logging_start_time,
                test_type="stepped",
            )
            # Don't turn on load here - panel manages it
            self.statusbar.showMessage("Logging started")
        else:
            # Resume logging (for subsequent steps)
            self.statusbar.showMessage("Logging resumed")

    @Slot()
    def _on_battery_charger_stop(self) -> None:
        """Handle test stop from battery charger panel.

        Note: Battery Charger panel manages the load state directly.
        This handler only controls logging, not the load.
        """
        # Check if this is final stop (end of test) or pause between steps
        # If panel is still running, this is a pause; otherwise it's final stop
        is_final_stop = not self.battery_charger_panel._test_running

        if self._logging_enabled and is_final_stop:
            # Final stop - end logging and save
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
            # Stop logging WITHOUT turning off load (panel controls load)
            self._logging_enabled = False
            # Unlock UI controls after test
            self._enable_controls_after_test()
        elif self._logging_enabled:
            # Pause between steps - just stop logging, don't save yet
            self._logging_enabled = False
            self.statusbar.showMessage("Logging paused")

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

    @Slot()
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

                # Calculate runtime as time elapsed from first measurement
                if start_time:
                    runtime_s = int((timestamp - start_time).total_seconds())
                else:
                    # Fallback to stored runtime if timestamp calculation fails
                    runtime_s = reading_dict.get("runtime_s", reading_dict.get("runtime_seconds", 0))

                reading = Reading(
                    timestamp=timestamp,
                    # Handle both old and new parameter names for backwards compatibility
                    voltage_v=reading_dict.get("voltage_v", reading_dict.get("voltage", 0)),
                    current_a=reading_dict.get("current_a", reading_dict.get("current", 0)),
                    power_w=reading_dict.get("power_w", reading_dict.get("power", 0)),
                    energy_wh=reading_dict.get("energy_wh", 0),
                    capacity_mah=reading_dict.get("capacity_mah", 0),
                    mosfet_temp_c=reading_dict.get("mosfet_temp_c", reading_dict.get("temperature_c", 0)),
                    ext_temp_c=reading_dict.get("ext_temp_c", reading_dict.get("ext_temperature_c", 0)),
                    fan_speed_rpm=reading_dict.get("fan_speed_rpm", reading_dict.get("fan_rpm", 0)),
                    load_r_ohm=reading_dict.get("load_r_ohm", reading_dict.get("load_resistance_ohm")),
                    battery_r_ohm=reading_dict.get("battery_r_ohm", reading_dict.get("battery_resistance_ohm")),
                    runtime_s=runtime_s,
                    # Setpoint fields (parameters sent to tester)
                    # Handle both old (set_mode, set_resistance_r) and new (load_mode, set_resistance_ohm) names
                    load_mode=reading_dict.get("load_mode", reading_dict.get("set_mode")),
                    set_current_a=reading_dict.get("set_current_a"),
                    set_voltage_v=reading_dict.get("set_voltage_v"),
                    set_power_w=reading_dict.get("set_power_w"),
                    set_resistance_ohm=reading_dict.get("set_resistance_ohm", reading_dict.get("set_resistance_r")),
                    cutoff_voltage_v=reading_dict.get("cutoff_voltage_v"),
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
        json_filename = self.battery_capacity_panel.filename_edit.text().strip()
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
            battery_info = self.battery_capacity_panel.get_battery_info()
            battery_name = battery_info.get("name", "Unknown")
            test_type = self.battery_capacity_panel.type_combo.currentText()

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
                    "mosfet_temp_C",
                    "ext_temp_C",
                    "fan_speed_RPM",
                    "load_r_ohm",
                    "battery_r_ohm",
                ])

                # Write readings
                start_time = self._accumulated_readings[0].timestamp if self._accumulated_readings else None
                for reading in self._accumulated_readings:
                    # Calculate runtime from timestamps
                    if start_time and reading.timestamp:
                        runtime = (reading.timestamp - start_time).total_seconds()
                    else:
                        runtime = reading.runtime_s

                    writer.writerow([
                        reading.timestamp.isoformat(),
                        f"{runtime:.1f}",
                        f"{reading.voltage_v:.3f}",
                        f"{reading.current_a:.4f}",
                        f"{reading.power_w:.2f}",
                        f"{reading.energy_wh:.4f}",
                        f"{reading.capacity_mah:.1f}",
                        reading.mosfet_temp_c,
                        reading.ext_temp_c,
                        reading.fan_speed_rpm if hasattr(reading, 'fan_speed_rpm') else 0,
                        f"{reading.load_r_ohm:.2f}" if hasattr(reading, 'load_r_ohm') and reading.load_r_ohm else "",
                        f"{reading.battery_r_ohm:.2f}" if hasattr(reading, 'battery_r_ohm') and reading.battery_r_ohm else "",
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

    def _on_prepare_needed(self) -> None:
        """Handle device needing USB prepare (called from device thread)."""
        # Emit signal to handle on main thread
        self.prepare_needed.emit()

    # Timeout for the macOS password dialog before giving up
    USB_PREPARE_TIMEOUT = 60  # seconds

    @Slot()
    def _run_usb_prepare(self) -> None:
        """Run USB prepare script with admin privileges to initialize device.

        On macOS, the DL24P requires a SET_IDLE HID class request after power-cycling
        that macOS doesn't send during USB enumeration (Windows does). This runs
        usb_prepare.py via osascript to prompt for admin credentials.
        """
        if sys.platform != 'darwin':
            QMessageBox.information(
                self, "Device Not Responding",
                "The device was detected but is not responding.\n\n"
                "Try unplugging and re-plugging the USB cable, then reconnect."
            )
            return

        self.statusbar.showMessage("No response from device — USB initialization needed")

        # Locate usb_prepare.py
        if getattr(sys, 'frozen', False):
            bundle_dir = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
            usb_prepare_path = bundle_dir / 'usb_prepare.py'
        else:
            usb_prepare_path = Path(__file__).resolve().parent.parent.parent / 'usb_prepare.py'

        if not usb_prepare_path.exists():
            QMessageBox.warning(
                self, "Device Not Responding",
                "The device was detected but is not responding.\n\n"
                "The USB initialization script could not be found.\n"
                "Run manually in a terminal:\n\n"
                "  sudo python usb_prepare.py"
            )
            self.statusbar.showMessage("Disconnected — USB init script not found")
            return

        # Explain what's about to happen
        explain = QMessageBox(self)
        explain.setIcon(QMessageBox.Information)
        explain.setWindowTitle("USB Device Initialization Required")
        explain.setText(
            "The DL24P was detected but is not responding to commands."
        )
        explain.setInformativeText(
            "After power-cycling, the device needs a one-time USB reset that "
            "requires administrator privileges.\n\n"
            "macOS will ask for your password to perform this initialization. "
            "This is safe — it sends a standard USB HID reset command to the device."
        )
        explain.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        explain.setDefaultButton(QMessageBox.Ok)
        explain.button(QMessageBox.Ok).setText("Continue")
        if explain.exec() != QMessageBox.Ok:
            self.statusbar.showMessage("USB initialization cancelled — device not connected")
            return

        # Disconnect first so usb_prepare.py can claim the device
        self.statusbar.showMessage("Releasing USB device for initialization...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()  # Ensure dialog is dismissed and status bar updates
        if self.device and self.device.is_connected:
            self.device.disconnect()
            self.connection_changed.emit(False)

        self.statusbar.showMessage("Requesting administrator authorization...")
        QApplication.processEvents()

        # Build the shell command for osascript
        # In frozen builds, sys.executable is the app binary, not Python
        if getattr(sys, 'frozen', False):
            import shutil
            python_exec = shutil.which('python3') or '/usr/bin/python3'
        else:
            python_exec = sys.executable
        cmd_str = (
            f'DYLD_LIBRARY_PATH=/opt/homebrew/lib '
            f'{python_exec} -B {usb_prepare_path}'
        )
        cmd_str_escaped = cmd_str.replace('\\', '\\\\').replace('"', '\\"')

        # Use 'with prompt' to show "Test Bench" in the macOS auth dialog
        prompt_text = (
            "Test Bench needs to send a USB reset command to initialize "
            "the DL24P device."
        )
        prompt_escaped = prompt_text.replace('\\', '\\\\').replace('"', '\\"')
        applescript = (
            f'do shell script "{cmd_str_escaped}" '
            f'with prompt "{prompt_escaped}" '
            f'with administrator privileges'
        )

        try:
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True, text=True, timeout=self.USB_PREPARE_TIMEOUT
            )
            if result.returncode == 0:
                self.statusbar.showMessage("USB device initialized — waiting for driver to reattach...")

                # Show success dialog that auto-dismisses after 3 seconds
                success = QMessageBox(self)
                success.setIcon(QMessageBox.Information)
                success.setWindowTitle("USB Initialization Complete")
                success.setText("Device initialized successfully.")
                success.setInformativeText("Reconnecting automatically...")
                success.setStandardButtons(QMessageBox.NoButton)
                success.show()
                QTimer.singleShot(3000, success.accept)

                QTimer.singleShot(1500, self._reconnect_after_prepare)
            else:
                stderr = result.stderr.strip()
                if 'User canceled' in stderr or 'canceled' in stderr.lower():
                    self.statusbar.showMessage("Disconnected — USB initialization cancelled")
                    self._show_prepare_cancelled_dialog()
                else:
                    self.statusbar.showMessage("Disconnected — USB initialization failed")
                    QMessageBox.warning(
                        self, "USB Initialization Failed",
                        f"The initialization did not complete successfully.\n\n{stderr[:200]}"
                    )
        except subprocess.TimeoutExpired:
            self.statusbar.showMessage("Disconnected — password dialog timed out")
            self._show_prepare_cancelled_dialog()
        except Exception as e:
            self.statusbar.showMessage("Disconnected — USB initialization error")
            QMessageBox.warning(
                self, "USB Initialization Error",
                f"An unexpected error occurred:\n\n{e}"
            )

    def _show_prepare_cancelled_dialog(self) -> None:
        """Show dialog explaining that the device cannot work without USB init."""
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Warning)
        dlg.setWindowTitle("Connection Not Established")
        dlg.setText("The device could not be initialized.")
        dlg.setInformativeText(
            "The DL24P requires a USB reset command after power-cycling, "
            "which needs your macOS password.\n\n"
            "Without this step, the device will not respond to the app.\n\n"
            "To try again, click Connect."
        )
        dlg.setStandardButtons(QMessageBox.Ok)
        dlg.exec()

    def _reconnect_after_prepare(self) -> None:
        """Reconnect to device after USB prepare completed successfully."""
        try:
            self.statusbar.showMessage("Scanning for device...")
            self.control_panel._refresh_ports()
            self.statusbar.showMessage("Reconnecting to device...")
            self._connect_device()
        except Exception as e:
            self.statusbar.showMessage(f"Reconnect failed: {e}")

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
        # Show "Communication established" on first successful response after connect
        if self._awaiting_first_status:
            self._awaiting_first_status = False
            conn_type_str = "USB HID" if isinstance(self.device, USBHIDDevice) else "Serial"
            self.statusbar.showMessage(
                f"Communication established ({conn_type_str}) — {status.voltage_v:.2f}V"
            )

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

                # Determine setpoint fields based on current mode
                # Device mode: 0=CC, 1=CV, 2=CR, 3=CP
                load_mode = None
                set_current_a = None
                set_voltage_v = None
                set_power_w = None
                set_resistance_ohm = None

                if status.mode is not None and status.value_set is not None:
                    if status.mode == 0:  # CC mode
                        load_mode = "CC"
                        set_current_a = status.value_set
                    elif status.mode == 1:  # CV mode
                        load_mode = "CV"
                        set_voltage_v = status.value_set
                    elif status.mode == 2:  # CR mode
                        load_mode = "CR"
                        set_resistance_ohm = status.value_set
                    elif status.mode == 3:  # CP mode
                        load_mode = "CP"
                        set_power_w = status.value_set

                # Get cutoff voltage (available for all modes)
                cutoff_voltage_v = status.voltage_cutoff if status.voltage_cutoff is not None else None

                reading = Reading(
                    timestamp=datetime.now(),
                    voltage_v=status.voltage_v,
                    current_a=status.current_a,
                    power_w=status.power_w,
                    energy_wh=status.energy_wh,
                    capacity_mah=status.capacity_mah,
                    mosfet_temp_c=status.mosfet_temp_c,
                    ext_temp_c=status.ext_temp_c,
                    fan_speed_rpm=status.fan_speed_rpm,
                    load_r_ohm=status.load_r_ohm,
                    battery_r_ohm=status.battery_r_ohm,
                    runtime_s=status.runtime_seconds,
                    load_mode=load_mode,
                    set_current_a=set_current_a,
                    set_voltage_v=set_voltage_v,
                    set_power_w=set_power_w,
                    set_resistance_ohm=set_resistance_ohm,
                    cutoff_voltage_v=cutoff_voltage_v,
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
            self.battery_capacity_panel.update_test_progress(elapsed, status.capacity_mah,
                                                      status.voltage_v, status.energy_wh)

        # Pulse communication indicator to show data received
        self.control_panel.pulse_comm_indicator()

        self.status_panel.update_status(status)

        # Poll load state during logging — abort test if load is off
        # This catches both on→off transitions AND load never turning on
        if self._logging_enabled:
            import time as _time
            if status.load_on:
                self._load_off_count = 0  # Reset counter when load is on
            else:
                # Allow a 3-second grace period after load turn-on for it to take effect
                # During start delay, the timer is active so skip load-off detection entirely
                if getattr(self, '_start_delay_timer', None) is not None:
                    grace_elapsed = False
                else:
                    grace_elapsed = (_time.time() - getattr(self, '_logging_started_at', 0)) > 3.0
                if grace_elapsed:
                    self._load_off_count += 1

                if self._load_off_count >= self._load_off_abort_threshold:
                    # Load has been off for multiple consecutive polls — abort test
                    num_readings = len(self._accumulated_readings)
                    self._logging_enabled = False  # Stop immediately to prevent more data
                    self._load_off_count = 0
                    self._update_test_complete_alert_state(False)
                    self._enable_controls_after_test()
                    self.status_panel.log_switch.setChecked(False)
                    # End the current session properly so next Start Test works
                    if self._current_session:
                        self.database.commit()
                        self._current_session.end_time = datetime.now()
                        self.database.update_session(self._current_session)
                        self._last_completed_session = self._current_session
                        self._current_session = None
                    self._logging_start_time = None

                    # Stop the automation test if running
                    self.battery_capacity_panel._update_ui_stopped()

                    # Stop battery load test if running
                    if self.battery_load_panel._test_running:
                        self.battery_load_panel._test_timer.stop()
                        self.battery_load_panel.start_btn.setText("Start")
                        self.battery_load_panel.status_label.setText("Test Aborted (Load Off)")
                        self.battery_load_panel.progress_bar.setValue(100)
                        self.battery_load_panel._test_running = False

                    # Save test data if auto-save is enabled
                    if self.battery_capacity_panel.autosave_checkbox.isChecked():
                        saved_path = self._save_test_json()
                        if saved_path:
                            self.statusbar.showMessage(
                                f"Test aborted (load off): {num_readings} readings saved to {saved_path}"
                            )
                        else:
                            self.statusbar.showMessage(
                                f"Test aborted (load off): {num_readings} readings - click Save to export"
                            )
                    elif self.battery_load_panel.autosave_checkbox.isChecked():
                        saved_path = self._save_battery_load_json()
                        if saved_path:
                            self.statusbar.showMessage(
                                f"Battery Load test aborted (load off): {num_readings} readings saved to {saved_path}"
                            )
                            self.history_panel.refresh()
                        else:
                            self.statusbar.showMessage(
                                f"Battery Load test aborted (load off): {num_readings} readings - click Save to export"
                            )
                    else:
                        self.statusbar.showMessage(
                            f"Test aborted (load off): {num_readings} readings - click Save to export"
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
        self.battery_capacity_panel.set_connected(connected)
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
    def _toggle_battery_capacity_panel(self) -> None:
        """Toggle visibility of the Test Automation panel content."""
        is_visible = self.bottom_tabs.isVisible()
        panel_height = 380

        if is_visible:
            # Collapse: store current window height, hide tabs, shrink window
            self._expanded_window_height = self.height()
            self.bottom_tabs.setVisible(False)
            self.automation_content.setFixedHeight(0)
            self.battery_capacity_toggle.setArrowType(Qt.RightArrow)
            # Shrink window
            self.setFixedHeight(self.height() - panel_height)
            # Remove fixed height constraint to allow future resizing
            self.setMinimumHeight(200)
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        else:
            # Expand: restore tabs and window height
            self.automation_content.setFixedHeight(panel_height)
            self.bottom_tabs.setVisible(True)
            self.battery_capacity_toggle.setArrowType(Qt.DownArrow)
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
