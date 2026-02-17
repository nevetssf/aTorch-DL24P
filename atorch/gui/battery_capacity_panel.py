"""Test automation panel."""

import json
import platform
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QTextEdit,
    QProgressBar,
    QMessageBox,
    QFormLayout,
    QInputDialog,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PySide6.QtCore import Qt, Slot, Signal, QTimer

from ..automation.test_runner import TestRunner, TestProgress, TestState
from ..data.database import Database
from .battery_info_widget import BatteryInfoWidget


class BatteryCapacityPanel(QWidget):
    """Panel for test automation control."""

    # Signal emitted when test should start: (discharge_type, value, voltage_cutoff, duration_s or 0)
    # discharge_type: 0=CC, 2=CR
    start_test_requested = Signal(int, float, float, int)
    # Signal emitted when pause is clicked (stops logging and load, keeps data)
    pause_test_requested = Signal()
    # Signal emitted when resume is clicked (continues logging and load)
    resume_test_requested = Signal()
    # Signal emitted when Apply is clicked: (discharge_type, value, voltage_cutoff, duration_s or 0)
    apply_settings_requested = Signal(int, float, float, int)
    # Signal emitted when manual Save is clicked (filename)
    manual_save_requested = Signal(str)
    # Signal emitted when battery info changes (for syncing with battery load panel)
    battery_info_changed = Signal()
    # Signal emitted when session is loaded from file (readings list)
    session_loaded = Signal(list)  # List of reading dicts
    # Signal emitted when Export CSV is clicked
    export_csv_requested = Signal()

    def __init__(self, test_runner: TestRunner, database: Database):
        super().__init__()

        self.test_runner = test_runner
        self.database = database
        self._loading_settings = False  # Flag to prevent save during load

        # Load default presets from resources/battery_capacity directory
        self._camera_battery_presets = self._load_presets_file("battery_capacity/presets_camera.json")
        self._household_battery_presets = self._load_presets_file("battery_capacity/presets_household.json")
        self._default_test_presets = self._load_presets_file("battery_capacity/presets_test.json")

        # User presets directories and settings file
        self._atorch_dir = Path.home() / ".atorch"
        self._atorch_dir.mkdir(parents=True, exist_ok=True)
        self._battery_presets_dir = self._atorch_dir / "battery_presets"
        self._battery_presets_dir.mkdir(parents=True, exist_ok=True)
        self._test_presets_dir = self._atorch_dir / "test_presets"
        self._test_presets_dir.mkdir(parents=True, exist_ok=True)
        self._last_session_file = self._atorch_dir / "battery_capacity_session.json"

        self._create_ui()
        self._connect_save_signals()
        self._load_last_session()

    def _load_presets_file(self, filename: str) -> dict:
        """Load battery presets from a file in the resources directory."""
        module_dir = Path(__file__).parent.parent.parent
        presets_file = module_dir / "resources" / filename

        try:
            with open(presets_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _create_ui(self) -> None:
        """Create the automation panel UI."""
        layout = QHBoxLayout(self)

        # Left: Test configuration
        config_group = QGroupBox("Test Conditions")
        config_group.setFixedWidth(350)
        config_layout = QVBoxLayout(config_group)

        # Test presets row (at top)
        test_presets_layout = QHBoxLayout()
        test_presets_layout.addWidget(QLabel("Presets"))
        self.test_presets_combo = QComboBox()
        self.test_presets_combo.setToolTip("Load saved test configuration presets")
        test_presets_layout.addWidget(self.test_presets_combo, 1)
        self.test_presets_combo.currentIndexChanged.connect(self._on_test_preset_selected)
        self.save_test_preset_btn = QPushButton("Save")
        self.save_test_preset_btn.setMaximumWidth(50)
        self.save_test_preset_btn.setToolTip("Save current test configuration as preset")
        self.save_test_preset_btn.clicked.connect(self._save_test_preset)
        test_presets_layout.addWidget(self.save_test_preset_btn)
        self.delete_test_preset_btn = QPushButton("Delete")
        self.delete_test_preset_btn.setMaximumWidth(50)
        self.delete_test_preset_btn.setEnabled(False)
        self.delete_test_preset_btn.setToolTip("Delete selected test preset")
        self.delete_test_preset_btn.clicked.connect(self._delete_test_preset)
        test_presets_layout.addWidget(self.delete_test_preset_btn)
        config_layout.addLayout(test_presets_layout)

        # Parameters panel (contains discharge type, parameters, and apply button)
        params_panel = QGroupBox()
        params_panel_layout = QVBoxLayout(params_panel)
        params_panel_layout.setContentsMargins(6, 6, 6, 6)

        # Discharge type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Discharge Type"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["CC", "CR"])
        self.type_combo.setToolTip("CC = Constant Current\nCR = Constant Resistance")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.type_combo.currentIndexChanged.connect(self._on_filename_field_changed)
        type_layout.addWidget(self.type_combo)
        params_panel_layout.addLayout(type_layout)

        # Parameters form
        self.params_form = QFormLayout()

        # Value spinbox (Current/Power/Resistance depending on type)
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 24.0)
        self.value_spin.setDecimals(3)
        self.value_spin.setSingleStep(0.1)
        self.value_spin.setValue(0.5)
        self.value_spin.setToolTip("Discharge value (current/resistance depending on type)")
        self.value_spin.valueChanged.connect(self._on_filename_field_changed)
        self.value_label = QLabel("Current (A)")
        self.value_label.setMinimumWidth(85)  # Fixed width to prevent layout jumping
        self.params_form.addRow(self.value_label, self.value_spin)

        # Voltage cutoff
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 200.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(3.0)
        self.cutoff_spin.setToolTip("Stop test when battery voltage drops below this value")
        self.cutoff_spin.valueChanged.connect(self._on_filename_field_changed)
        self.params_form.addRow("V Cutoff", self.cutoff_spin)

        # Time Limit (optional duration limit)
        time_limit_layout = QHBoxLayout()
        self.timed_checkbox = QCheckBox()
        self.timed_checkbox.setChecked(False)
        self.timed_checkbox.setToolTip("Enable time limit for test")
        self.timed_checkbox.toggled.connect(self._on_timed_toggled)
        time_limit_layout.addWidget(self.timed_checkbox)

        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 99)
        self.hours_spin.setValue(1)
        self.hours_spin.setSuffix("h")
        self.hours_spin.setEnabled(False)
        self.hours_spin.setToolTip("Maximum test duration in hours")
        time_limit_layout.addWidget(self.hours_spin)

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)
        self.minutes_spin.setValue(0)
        self.minutes_spin.setSuffix("m")
        self.minutes_spin.setEnabled(False)
        self.minutes_spin.setToolTip("Maximum test duration in minutes")
        time_limit_layout.addWidget(self.minutes_spin)

        # Keep duration_spin for backwards compatibility with existing code
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 86400)
        self.duration_spin.setValue(3600)
        self.duration_spin.setVisible(False)  # Hidden, calculated from hours/minutes

        self.params_form.addRow("Time Limit", time_limit_layout)

        params_panel_layout.addLayout(self.params_form)

        # Apply button
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setToolTip("Apply test settings to device without starting test")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        params_panel_layout.addWidget(self.apply_btn)

        # Add parameters panel to config layout
        config_layout.addWidget(params_panel)

        # Load test presets into dropdown
        self._load_test_presets_list()

        layout.addWidget(config_group)

        # Middle: Battery info (using shared widget)
        self.battery_info_widget = BatteryInfoWidget("Battery Info", 350)
        self.battery_info_widget.settings_changed.connect(self._on_battery_info_changed)
        self.battery_info_widget.settings_changed.connect(self._on_filename_field_changed)
        # Connect preset controls
        self.battery_info_widget.presets_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.battery_info_widget.save_preset_btn.clicked.connect(self._save_battery_preset)
        self.battery_info_widget.delete_preset_btn.clicked.connect(self._delete_battery_preset)
        layout.addWidget(self.battery_info_widget)

        # Load battery presets into dropdown
        self._load_battery_presets_list()

        # Right: Test control
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Abort button
        self.start_btn = QPushButton("Start")
        self.start_btn.setToolTip("Start capacity test - applies settings and begins discharge")
        self.start_btn.clicked.connect(self._on_start_clicked)
        control_layout.addWidget(self.start_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        control_layout.addWidget(self.progress_bar)

        # Status label (bold, color-coded)
        self.status_label = QLabel("Not Connected")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        control_layout.addWidget(self.status_label)

        # Elapsed time (normal weight, larger font)
        self.elapsed_label = QLabel("0h 0m 0s")
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        font = self.elapsed_label.font()
        font.setPointSize(14)
        font.setBold(False)  # Normal weight, not bold
        self.elapsed_label.setFont(font)
        control_layout.addWidget(self.elapsed_label)

        # Remaining time estimate
        self.remaining_label = QLabel("")
        self.remaining_label.setAlignment(Qt.AlignCenter)
        self.remaining_label.setStyleSheet("color: #666;")
        control_layout.addWidget(self.remaining_label)

        # Reduce spacing before Test Summary
        control_layout.addSpacing(-5)

        # Test Summary table
        summary_group = QGroupBox("Test Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(6, 0, 6, 6)

        self.summary_table = QTableWidget(1, 4)
        self.summary_table.setHorizontalHeaderLabels(["Run Time", "Median V", "Capacity", "Energy"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.NoSelection)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Set all columns to stretch equally
        for col in range(4):
            self.summary_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)

        # Make the single row taller
        self.summary_table.setRowHeight(0, 35)

        # Create value items (store references for updates)
        self.summary_runtime_item = QTableWidgetItem("--")
        self.summary_voltage_item = QTableWidgetItem("--")
        self.summary_capacity_item = QTableWidgetItem("--")
        self.summary_energy_item = QTableWidgetItem("--")

        # Center align all values
        for item in [self.summary_runtime_item, self.summary_voltage_item,
                     self.summary_capacity_item, self.summary_energy_item]:
            item.setTextAlignment(Qt.AlignCenter)

        self.summary_table.setItem(0, 0, self.summary_runtime_item)
        self.summary_table.setItem(0, 1, self.summary_voltage_item)
        self.summary_table.setItem(0, 2, self.summary_capacity_item)
        self.summary_table.setItem(0, 3, self.summary_energy_item)

        # Set fixed height to prevent scrolling
        table_height = self.summary_table.horizontalHeader().height() + self.summary_table.rowHeight(0) + 2
        self.summary_table.setFixedHeight(table_height)

        summary_layout.addWidget(self.summary_table)
        control_layout.addWidget(summary_group)

        control_layout.addStretch()

        # Auto Save section
        autosave_layout = QHBoxLayout()
        self.autosave_checkbox = QCheckBox("Auto Save")
        self.autosave_checkbox.setChecked(True)
        self.autosave_checkbox.setToolTip("Automatically save test data when test completes")
        self.autosave_checkbox.toggled.connect(self._on_autosave_toggled)
        autosave_layout.addWidget(self.autosave_checkbox)
        self.save_btn = QPushButton("Save")
        self.save_btn.setMaximumWidth(50)
        self.save_btn.setToolTip("Manually save test data to JSON file")
        self.save_btn.clicked.connect(self._on_save_clicked)
        autosave_layout.addWidget(self.save_btn)
        self.load_btn = QPushButton("Load")
        self.load_btn.setMaximumWidth(50)
        self.load_btn.setToolTip("Load previous test data from JSON file")
        self.load_btn.clicked.connect(self._on_load_clicked)
        autosave_layout.addWidget(self.load_btn)
        self.export_btn = QPushButton("Export")
        self.export_btn.setMaximumWidth(60)
        self.export_btn.setToolTip("Export test data to CSV file")
        self.export_btn.clicked.connect(self._on_export_clicked)
        autosave_layout.addWidget(self.export_btn)
        self.show_folder_btn = QPushButton("Show Folder")
        self.show_folder_btn.setMaximumWidth(80)
        self.show_folder_btn.setToolTip("Open folder containing saved test data files")
        self.show_folder_btn.clicked.connect(self._on_show_folder_clicked)
        autosave_layout.addWidget(self.show_folder_btn)
        control_layout.addLayout(autosave_layout)

        # Filename text field
        self.filename_edit = QLineEdit()
        self.filename_edit.setReadOnly(True)  # Read-only when Auto Save is checked
        self.filename_edit.setPlaceholderText("Test filename...")
        self._update_filename()  # Initialize with generated filename
        control_layout.addWidget(self.filename_edit)

        layout.addWidget(control_group)

    @Slot(bool)
    def _on_timed_toggled(self, checked: bool) -> None:
        """Handle timed checkbox toggle."""
        self.hours_spin.setEnabled(checked)
        self.minutes_spin.setEnabled(checked)
        self._sync_duration()

    def _sync_duration(self) -> None:
        """Sync duration_spin value from hours and minutes spinboxes."""
        hours = self.hours_spin.value()
        minutes = self.minutes_spin.value()
        self.duration_spin.setValue(hours * 3600 + minutes * 60)

    def _sync_hours_minutes(self) -> None:
        """Sync hours and minutes from duration_spin value."""
        total_seconds = self.duration_spin.value()
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        self.hours_spin.blockSignals(True)
        self.minutes_spin.blockSignals(True)
        self.hours_spin.setValue(hours)
        self.minutes_spin.setValue(minutes)
        self.hours_spin.blockSignals(False)
        self.minutes_spin.blockSignals(False)

    @Slot(bool)
    def _on_autosave_toggled(self, checked: bool) -> None:
        """Handle Auto Save checkbox toggle."""
        self.filename_edit.setReadOnly(checked)
        if checked:
            # Reset to auto-generated filename
            self._update_filename()

    @Slot()
    def _on_save_clicked(self) -> None:
        """Handle manual Save button click."""
        filename = self.filename_edit.text().strip()
        if filename:
            # Ensure .json extension
            if not filename.endswith('.json'):
                filename += '.json'
            self.manual_save_requested.emit(filename)

    @Slot()
    def _on_load_clicked(self) -> None:
        """Handle Load button click - load a previous test session from JSON."""
        # Default to test_data directory
        default_dir = str(self._atorch_dir / "test_data")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Test Session",
            default_dir,
            "JSON Files (*.json)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load file: {e}")
            return

        self._loading_settings = True  # Prevent auto-save during load

        try:
            # Load test configuration
            test_config = data.get("test_config", {})
            if "discharge_type_index" in test_config:
                self.type_combo.setCurrentIndex(test_config["discharge_type_index"])
            elif "discharge_type" in test_config:
                # Handle string type names
                type_map = {"CC": 0, "CR": 1}  # combo indices
                self.type_combo.setCurrentIndex(type_map.get(test_config["discharge_type"], 0))
            if "value" in test_config:
                self.value_spin.setValue(test_config["value"])
            if "voltage_cutoff" in test_config:
                self.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.timed_checkbox.setChecked(test_config["timed"])
            if "duration_seconds" in test_config:
                self.duration_spin.setValue(test_config["duration_seconds"])
                self._sync_hours_minutes()

            # Load battery info
            battery_info = data.get("battery_info", {})
            self.battery_info_widget.set_battery_info(battery_info)

            # Update filename to show loaded file
            self.filename_edit.setText(Path(file_path).name)

            # Emit readings for display
            readings = data.get("readings", [])
            if readings:
                self.session_loaded.emit(readings)
                # Update summary with loaded data
                self._update_summary_from_readings(readings)

        finally:
            self._loading_settings = False

    @Slot()
    def _on_export_clicked(self) -> None:
        """Handle Export button click - export data as CSV."""
        self.export_csv_requested.emit()

    @Slot()
    def _on_show_folder_clicked(self) -> None:
        """Handle Show Folder button click - open test_data folder in system file browser."""
        folder_path = self._atorch_dir / "test_data"
        folder_path.mkdir(parents=True, exist_ok=True)

        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["open", str(folder_path)])
            elif system == "Windows":
                subprocess.run(["explorer", str(folder_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)])
        except Exception:
            pass

    def _update_filename(self) -> None:
        """Update the filename field with auto-generated name."""
        # Check if widgets are created (may be called during initialization)
        if hasattr(self, 'autosave_checkbox') and hasattr(self, 'filename_edit'):
            if self.autosave_checkbox.isChecked():
                self.filename_edit.setText(self.generate_test_filename())

    @Slot()
    def _on_filename_field_changed(self) -> None:
        """Handle changes to fields that affect the filename."""
        # Don't update filename during loading to preserve loaded filename
        if not self._loading_settings:
            self._update_filename()

    @Slot()
    def _on_battery_info_changed(self) -> None:
        """Handle battery info changes - emit signal to sync with other panels."""
        if not self._loading_settings:
            self.battery_info_changed.emit()

    @Slot(int)
    def _on_type_changed(self, index: int) -> None:
        """Handle discharge type selection change."""
        if index == 0:  # CC - Constant Current
            self.value_label.setText("Current (A):")
            self.value_spin.setToolTip("Discharge current in Amps")
            self.value_spin.setRange(0.0, 24.0)
            self.value_spin.setDecimals(3)
            self.value_spin.setSingleStep(0.1)
            self.value_spin.setValue(0.5)
        elif index == 1:  # CR - Constant Resistance
            self.value_label.setText("Resistance (Ω):")
            self.value_spin.setToolTip("Load resistance in Ohms")
            self.value_spin.setRange(0.1, 9999.0)
            self.value_spin.setDecimals(1)
            self.value_spin.setSingleStep(1.0)
            self.value_spin.setValue(10.0)

    @Slot()
    def _on_start_clicked(self) -> None:
        """Handle start/abort button click."""
        if self.start_btn.text() == "Abort":
            # Abort test - this will be handled by main window turning off logging
            self._update_ui_stopped(show_aborted=True)
            # Emit with zeros to signal stop
            self.start_test_requested.emit(0, 0, 0, 0)
        else:
            # Get test parameters (connection check will happen in main_window)
            # Map combo index to discharge type: 0=CC, 2=CR
            type_map = [0, 2]  # combo index 0→CC(0), combo index 1→CR(2)
            discharge_type = type_map[self.type_combo.currentIndex()]
            value = self.value_spin.value()
            cutoff = self.cutoff_spin.value()
            duration = self.duration_spin.value() if self.timed_checkbox.isChecked() else 0

            # Refresh filename if autosave is enabled
            if self.autosave_checkbox.isChecked():
                new_filename = self.generate_test_filename()
                self.filename_edit.setText(new_filename)

            # Apply settings first (like pressing Apply button)
            self.apply_settings_requested.emit(discharge_type, value, cutoff, duration)

            # Then start test (turns on load and starts logging)
            self.start_test_requested.emit(discharge_type, value, cutoff, duration)
            self._update_ui_running()

    @Slot()
    def _on_apply_clicked(self) -> None:
        """Handle Apply button click - sends settings to device."""
        # Map combo index to discharge type: 0=CC, 2=CR
        type_map = [0, 2]  # combo index 0→CC(0), combo index 1→CR(2)
        discharge_type = type_map[self.type_combo.currentIndex()]
        value = self.value_spin.value()
        cutoff = self.cutoff_spin.value()
        duration = self.duration_spin.value() if self.timed_checkbox.isChecked() else 0

        self.apply_settings_requested.emit(discharge_type, value, cutoff, duration)

    def update_progress(self, progress: TestProgress) -> None:
        """Update UI with test progress."""
        # Update status label with color coding
        self.status_label.setText(progress.message or progress.state.name)
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        # Update elapsed time
        h = progress.elapsed_seconds // 3600
        m = (progress.elapsed_seconds % 3600) // 60
        s = progress.elapsed_seconds % 60
        self.elapsed_label.setText(f"{h}h {m}m {s}s")

        # Update progress bar for cycle/stepped tests
        if progress.total_cycles > 1:
            percent = int(100 * progress.current_cycle / progress.total_cycles)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(
                f"Cycle {progress.current_cycle}/{progress.total_cycles}"
            )
        elif progress.total_steps > 1:
            percent = int(100 * progress.current_step / progress.total_steps)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(
                f"Step {progress.current_step}/{progress.total_steps}"
            )
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")

        # Check for completion
        if progress.state in (
            TestState.COMPLETED,
            TestState.VOLTAGE_CUTOFF,
            TestState.TIMEOUT,
            TestState.ERROR,
        ):
            self._update_ui_stopped()

    def _update_ui_running(self) -> None:
        """Update UI for running state."""
        self.start_btn.setText("Abort")
        self.status_label.setText("Running")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.type_combo.setEnabled(False)
        self.value_spin.setEnabled(False)
        self.cutoff_spin.setEnabled(False)
        self.timed_checkbox.setEnabled(False)
        self.hours_spin.setEnabled(False)
        self.minutes_spin.setEnabled(False)

        # Reset voltage readings and summary for new test
        self._voltage_readings = []
        self.summary_runtime_item.setText("--")
        self.summary_voltage_item.setText("--")
        self.summary_capacity_item.setText("--")
        self.summary_energy_item.setText("--")

    def _update_ui_stopped(self, show_aborted: bool = False) -> None:
        """Update UI for stopped state.

        Args:
            show_aborted: If True, show "Aborted" message briefly before reverting to normal status
        """
        self.start_btn.setText("Start")

        if show_aborted:
            # Show "Aborted" briefly, then revert to normal status
            self.status_label.setText("Aborted")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            QTimer.singleShot(2000, lambda: self._restore_normal_status())
        else:
            self._restore_normal_status()

    def _restore_normal_status(self) -> None:
        """Restore status label to normal state based on connection."""
        # Only show "Ready" if device is connected
        if self.test_runner and self.test_runner.device and self.test_runner.device.is_connected:
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.start_btn.setEnabled(True)
        else:
            self.status_label.setText("Not Connected")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.start_btn.setEnabled(False)
        self.type_combo.setEnabled(True)
        self.value_spin.setEnabled(True)
        self.cutoff_spin.setEnabled(True)
        self.timed_checkbox.setEnabled(True)
        self.hours_spin.setEnabled(self.timed_checkbox.isChecked())
        self.minutes_spin.setEnabled(self.timed_checkbox.isChecked())
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.elapsed_label.setText("0h 0m 0s")
        self.remaining_label.setText("")

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all input widgets during test."""
        self.test_presets_combo.setEnabled(enabled)
        self.save_test_preset_btn.setEnabled(enabled)
        self.delete_test_preset_btn.setEnabled(enabled)
        self.type_combo.setEnabled(enabled)
        self.value_spin.setEnabled(enabled)
        self.cutoff_spin.setEnabled(enabled)
        self.timed_checkbox.setEnabled(enabled)
        self.hours_spin.setEnabled(enabled and self.timed_checkbox.isChecked())
        self.minutes_spin.setEnabled(enabled and self.timed_checkbox.isChecked())
        self.battery_info_widget.set_inputs_enabled(enabled)
        self.autosave_checkbox.setEnabled(enabled)
        self.filename_edit.setEnabled(enabled)

    def set_connected(self, connected: bool) -> None:
        """Update status label and button based on connection state."""
        if self.start_btn.text() != "Abort":  # Not running
            if connected:
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.start_btn.setEnabled(True)
            else:
                self.status_label.setText("Not Connected")
                self.status_label.setStyleSheet("color: red;")
                self.start_btn.setEnabled(False)

    def reload_battery_presets(self) -> None:
        """Reload battery presets list (called when another panel saves/deletes a preset)."""
        self._load_battery_presets_list()

    def update_test_progress(self, elapsed_seconds: float, capacity_mah: float, voltage: float = 0.0, energy_wh: float = 0.0) -> None:
        """Update progress bar, elapsed time, and test summary.

        Args:
            elapsed_seconds: Time elapsed since test started
            capacity_mah: Current capacity drawn in mAh
            voltage: Current voltage reading in V
            energy_wh: Current energy in Wh
        """
        if self.start_btn.text() != "Abort":
            return  # Not running

        # Store voltage reading for median calculation
        if voltage > 0:
            if not hasattr(self, '_voltage_readings'):
                self._voltage_readings = []
            self._voltage_readings.append(voltage)

        # Update elapsed time display
        h = int(elapsed_seconds) // 3600
        m = (int(elapsed_seconds) % 3600) // 60
        s = int(elapsed_seconds) % 60
        self.elapsed_label.setText(f"{h}h {m}m {s}s")

        # Update test summary
        self._update_test_summary(elapsed_seconds, capacity_mah, energy_wh)

        # Method 1: If Timed is enabled, use time-based progress
        if self.timed_checkbox.isChecked():
            duration = self.duration_spin.value()
            if duration > 0:
                progress = min(100, int(100 * elapsed_seconds / duration))
                remaining = max(0, duration - elapsed_seconds)
                mins, secs = divmod(int(remaining), 60)
                hours, mins = divmod(mins, 60)
                self.progress_bar.setValue(progress)
                self.progress_bar.setFormat(f"{progress}% ({hours}h {mins}m {secs}s remaining)")
                self.remaining_label.setText(f"~{hours}h {mins}m {secs}s remaining")
                return

        # Method 2: Use capacity-based progress (nominal capacity / current draw rate)
        nominal_capacity = self.battery_info_widget.nominal_capacity_spin.value()
        if nominal_capacity > 0 and capacity_mah > 0:
            progress = min(100, int(100 * capacity_mah / nominal_capacity))
            self.progress_bar.setValue(progress)
            self.progress_bar.setFormat(f"{progress}% ({capacity_mah:.0f} / {nominal_capacity} mAh)")

            # Estimate remaining time based on discharge rate
            if elapsed_seconds > 10:  # Wait for stable rate
                discharge_rate_mah_per_sec = capacity_mah / elapsed_seconds
                if discharge_rate_mah_per_sec > 0:
                    remaining_mah = nominal_capacity - capacity_mah
                    remaining_secs = remaining_mah / discharge_rate_mah_per_sec
                    if remaining_secs > 0:
                        mins, secs = divmod(int(remaining_secs), 60)
                        hours, mins = divmod(mins, 60)
                        self.remaining_label.setText(f"~{hours}h {mins}m {secs}s remaining")
                        return

        # Clear remaining if can't estimate
        self.remaining_label.setText("")

    def _update_test_summary(self, elapsed_seconds: float, capacity_mah: float, energy_wh: float) -> None:
        """Update the test summary box with current stats.

        Args:
            elapsed_seconds: Time elapsed since test started
            capacity_mah: Current capacity drawn in mAh
            energy_wh: Current energy in Wh
        """
        print(f"DEBUG: _update_test_summary called - elapsed={elapsed_seconds}, capacity={capacity_mah}, energy={energy_wh}")

        # Run Time
        h = int(elapsed_seconds) // 3600
        m = (int(elapsed_seconds) % 3600) // 60
        s = int(elapsed_seconds) % 60
        runtime_text = f"{h}h {m}m {s}s"
        print(f"DEBUG: Setting runtime to: {runtime_text}")
        self.summary_runtime_item.setText(runtime_text)

        # Median Voltage
        if hasattr(self, '_voltage_readings') and self._voltage_readings:
            sorted_voltages = sorted(self._voltage_readings)
            n = len(sorted_voltages)
            if n % 2 == 0:
                median_v = (sorted_voltages[n//2 - 1] + sorted_voltages[n//2]) / 2
            else:
                median_v = sorted_voltages[n//2]
            self.summary_voltage_item.setText(f"{median_v:.3f} V")
        else:
            self.summary_voltage_item.setText("--")

        # Capacity with auto-scaling
        if capacity_mah >= 1000:
            self.summary_capacity_item.setText(f"{capacity_mah/1000:.3f} Ah")
        else:
            self.summary_capacity_item.setText(f"{capacity_mah:.1f} mAh")

        # Energy (always in Wh since battery energies are typically in this range)
        self.summary_energy_item.setText(f"{energy_wh:.2f} Wh")

    def _update_summary_from_readings(self, readings: list) -> None:
        """Update test summary from loaded readings.

        Args:
            readings: List of reading dictionaries from loaded JSON
        """
        if not readings:
            print("DEBUG: No readings provided")
            return

        print(f"DEBUG: Updating summary from {len(readings)} readings")
        print(f"DEBUG: First reading keys: {readings[0].keys() if readings else 'None'}")

        # Calculate run time from first to last reading using timestamps
        try:
            from datetime import datetime
            first_timestamp = datetime.fromisoformat(readings[0]["timestamp"])
            last_timestamp = datetime.fromisoformat(readings[-1]["timestamp"])
            elapsed_seconds = (last_timestamp - first_timestamp).total_seconds()
            print(f"DEBUG: Elapsed seconds: {elapsed_seconds}")

            h = int(elapsed_seconds) // 3600
            m = (int(elapsed_seconds) % 3600) // 60
            s = int(elapsed_seconds) % 60
            self.summary_runtime_item.setText(f"{h}h {m}m {s}s")
            print(f"DEBUG: Set runtime to {h}h {m}m {s}s")
        except Exception as e:
            print(f"DEBUG: Runtime error: {e}")
            self.summary_runtime_item.setText("--")

        # Calculate median voltage
        try:
            voltages = [r.get("voltage", 0) for r in readings if "voltage" in r]
            print(f"DEBUG: Found {len(voltages)} voltage readings")
            if voltages:
                sorted_voltages = sorted(voltages)
                n = len(sorted_voltages)
                if n % 2 == 0:
                    median_v = (sorted_voltages[n//2 - 1] + sorted_voltages[n//2]) / 2
                else:
                    median_v = sorted_voltages[n//2]
                self.summary_voltage_item.setText(f"{median_v:.3f} V")
                print(f"DEBUG: Set median voltage to {median_v:.3f} V")
            else:
                self.summary_voltage_item.setText("--")
                print("DEBUG: No voltages found")
        except Exception as e:
            print(f"DEBUG: Voltage error: {e}")
            self.summary_voltage_item.setText("--")

        # Get final capacity
        try:
            capacity_mah = readings[-1].get("capacity_mah", 0)
            print(f"DEBUG: Final capacity: {capacity_mah} mAh")
            if capacity_mah >= 1000:
                self.summary_capacity_item.setText(f"{capacity_mah/1000:.3f} Ah")
            else:
                self.summary_capacity_item.setText(f"{capacity_mah:.1f} mAh")
        except Exception as e:
            print(f"DEBUG: Capacity error: {e}")
            self.summary_capacity_item.setText("--")

        # Get final energy
        try:
            energy_wh = readings[-1].get("energy_wh", 0)
            print(f"DEBUG: Final energy: {energy_wh} Wh")
            self.summary_energy_item.setText(f"{energy_wh:.2f} Wh")
        except Exception as e:
            print(f"DEBUG: Energy error: {e}")
            self.summary_energy_item.setText("--")

    def _load_battery_presets_list(self) -> None:
        """Load the list of battery presets into the combo box."""
        self.battery_info_widget.presets_combo.clear()
        self.battery_info_widget.presets_combo.addItem("")  # Empty option

        # Add Camera Presets section
        if self._camera_battery_presets:
            self.battery_info_widget.presets_combo.addItem("--- Camera Presets ---")
            model = self.battery_info_widget.presets_combo.model()
            item = model.item(self.battery_info_widget.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._camera_battery_presets.keys()):
                self.battery_info_widget.presets_combo.addItem(preset_name)

        # Add Household Presets section
        if self._household_battery_presets:
            self.battery_info_widget.presets_combo.insertSeparator(self.battery_info_widget.presets_combo.count())
            self.battery_info_widget.presets_combo.addItem("--- Household Presets ---")
            model = self.battery_info_widget.presets_combo.model()
            item = model.item(self.battery_info_widget.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._household_battery_presets.keys()):
                self.battery_info_widget.presets_combo.addItem(preset_name)

        # Get user presets from files
        user_presets = sorted(self._battery_presets_dir.glob("*.json"))
        if user_presets:
            # Add separator and header
            self.battery_info_widget.presets_combo.insertSeparator(self.battery_info_widget.presets_combo.count())
            self.battery_info_widget.presets_combo.addItem("--- User Presets ---")
            model = self.battery_info_widget.presets_combo.model()
            item = model.item(self.battery_info_widget.presets_combo.count() - 1)
            item.setEnabled(False)

            # Add user presets
            for preset_file in user_presets:
                self.battery_info_widget.presets_combo.addItem(preset_file.stem)

    def _is_default_battery_preset(self, name: str) -> bool:
        """Check if a battery preset name is a default (read-only) preset."""
        return name in self._camera_battery_presets or name in self._household_battery_presets

    def _get_default_battery_preset(self, name: str) -> Optional[dict]:
        """Get default battery preset data by name."""
        if name in self._camera_battery_presets:
            return self._camera_battery_presets[name]
        if name in self._household_battery_presets:
            return self._household_battery_presets[name]
        return None

    @Slot(int)
    def _on_preset_selected(self, index: int) -> None:
        """Handle battery preset selection from combo box."""
        preset_name = self.battery_info_widget.presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            # Empty or separator - disable delete
            self.battery_info_widget.delete_preset_btn.setEnabled(False)
            return

        # Check if this is a default preset
        is_default = self._is_default_battery_preset(preset_name)

        # Enable/disable delete button (can't delete defaults)
        self.battery_info_widget.delete_preset_btn.setEnabled(not is_default)

        if is_default:
            # Load from in-memory defaults
            data = self._get_default_battery_preset(preset_name)
            if not data:
                return
        else:
            # Load from user preset file
            preset_file = self._battery_presets_dir / f"{preset_name}.json"
            if not preset_file.exists():
                return

            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        # Apply preset data to UI
        self.battery_info_widget.set_battery_info(data)

        # Emit signal to trigger sync to battery load panel
        self.battery_info_changed.emit()

    @Slot()
    def _save_battery_preset(self) -> None:
        """Save current battery info as a preset."""
        # Get current battery info
        battery_info = self.battery_info_widget.get_battery_info()

        # Build default name from manufacturer and battery name
        manufacturer = battery_info.get("manufacturer", "").strip()
        battery_name = battery_info.get("name", "").strip()
        if manufacturer and battery_name:
            default_name = f"{manufacturer} {battery_name}"
        elif manufacturer:
            default_name = manufacturer
        elif battery_name:
            default_name = battery_name
        else:
            default_name = "New Preset"

        # Get preset name from user
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:",
            text=default_name
        )
        if not ok or not name:
            return

        # Sanitize filename (cross-platform compatible, allow decimal points)
        safe_name = "".join(c for c in name if c.isalnum() or c in " -_.").strip()
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid preset name.")
            return

        # Prepare data for saving (use original field names for compatibility)
        data = {
            "name": battery_info.get("name", ""),
            "manufacturer": battery_info.get("manufacturer", ""),
            "oem_equivalent": battery_info.get("oem_equivalent", ""),
            "manufactured": battery_info.get("manufactured"),
            "rated_voltage": battery_info.get("rated_voltage", 3.7),
            "nominal_capacity": battery_info.get("nominal_capacity_mah", 0),
            "nominal_energy": battery_info.get("nominal_energy_wh", 0),
            "technology": battery_info.get("technology", "Li-Ion"),
            "notes": battery_info.get("notes", ""),
        }

        preset_file = self._battery_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_battery_presets_list()
            # Select the newly saved preset
            index = self.battery_info_widget.presets_combo.findText(safe_name)
            if index >= 0:
                self.battery_info_widget.presets_combo.setCurrentIndex(index)
            # Emit signal so other panels can reload their preset lists
            self.battery_info_widget.preset_list_changed.emit()
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    @Slot()
    def _delete_battery_preset(self) -> None:
        """Delete the currently selected preset."""
        preset_name = self.battery_info_widget.presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            QMessageBox.information(self, "No Selection", "Please select a preset to delete.")
            return

        # Check if this is a default preset
        if self._is_default_battery_preset(preset_name):
            QMessageBox.warning(
                self, "Cannot Delete",
                "Default presets cannot be deleted. You can save a modified version as a new user preset."
            )
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete the preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            preset_file = self._battery_presets_dir / f"{preset_name}.json"
            try:
                preset_file.unlink()
                self._load_battery_presets_list()
                # Emit signal so other panels can reload their preset lists
                self.battery_info_widget.preset_list_changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Delete Error", f"Failed to delete preset: {e}")

    # Test preset methods

    def _load_test_presets_list(self) -> None:
        """Load the list of test presets into the combo box."""
        self.test_presets_combo.clear()
        self.test_presets_combo.addItem("")  # Empty option

        # Add default presets section header
        if self._default_test_presets:
            self.test_presets_combo.addItem("--- Presets ---")
            model = self.test_presets_combo.model()
            item = model.item(self.test_presets_combo.count() - 1)
            item.setEnabled(False)

            # Add default presets (sorted alphabetically)
            for preset_name in sorted(self._default_test_presets.keys()):
                self.test_presets_combo.addItem(preset_name)

        # Get user presets from files
        user_presets = sorted(self._test_presets_dir.glob("*.json"))
        if user_presets:
            # Add separator and header
            self.test_presets_combo.insertSeparator(self.test_presets_combo.count())
            self.test_presets_combo.addItem("--- User Presets ---")
            model = self.test_presets_combo.model()
            item = model.item(self.test_presets_combo.count() - 1)
            item.setEnabled(False)

            # Add user presets
            for preset_file in user_presets:
                self.test_presets_combo.addItem(preset_file.stem)

    def _is_default_test_preset(self, name: str) -> bool:
        """Check if a test preset name is a default (read-only) preset."""
        return name in self._default_test_presets

    @Slot(int)
    def _on_test_preset_selected(self, index: int) -> None:
        """Handle test preset selection from combo box."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            # Empty or separator - disable delete
            self.delete_test_preset_btn.setEnabled(False)
            return

        # Check if this is a default preset
        is_default = self._is_default_test_preset(preset_name)

        # Enable/disable delete button (can't delete defaults)
        self.delete_test_preset_btn.setEnabled(not is_default)

        if is_default:
            # Load from in-memory defaults
            data = self._default_test_presets[preset_name]
        else:
            # Load from user preset file
            preset_file = self._test_presets_dir / f"{preset_name}.json"
            if not preset_file.exists():
                return

            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        # Apply preset data to UI
        self.type_combo.setCurrentIndex(data.get("discharge_type", 0))
        self.value_spin.setValue(data.get("value", 0.5))
        self.cutoff_spin.setValue(data.get("voltage_cutoff", 3.0))
        self.timed_checkbox.setChecked(data.get("timed", False))
        self.duration_spin.setValue(data.get("duration", 3600))
        self._sync_hours_minutes()

    @Slot()
    def _save_test_preset(self) -> None:
        """Save current test configuration as a preset."""
        # Build default name from current settings
        type_names = ["CC", "CR"]
        type_units = ["A", "ohm"]
        discharge_type = self.type_combo.currentIndex()
        value = self.value_spin.value()
        cutoff = self.cutoff_spin.value()
        default_name = f"{type_names[discharge_type]} {value}{type_units[discharge_type]} {cutoff}V"

        # Get preset name from user
        name, ok = QInputDialog.getText(
            self, "Save Test Preset", "Preset name:",
            text=default_name
        )
        if not ok or not name:
            return

        # Sanitize filename (cross-platform compatible, allow decimal points)
        safe_name = "".join(c for c in name if c.isalnum() or c in " -_.").strip()
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid preset name.")
            return

        data = {
            "discharge_type": self.type_combo.currentIndex(),
            "value": self.value_spin.value(),
            "voltage_cutoff": self.cutoff_spin.value(),
            "timed": self.timed_checkbox.isChecked(),
            "duration": self.duration_spin.value(),
        }

        preset_file = self._test_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_test_presets_list()
            # Select the newly saved preset
            index = self.test_presets_combo.findText(safe_name)
            if index >= 0:
                self.test_presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    @Slot()
    def _delete_test_preset(self) -> None:
        """Delete the currently selected test preset."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            QMessageBox.information(self, "No Selection", "Please select a preset to delete.")
            return

        # Check if this is a default preset
        if self._is_default_test_preset(preset_name):
            QMessageBox.warning(
                self, "Cannot Delete",
                "Default presets cannot be deleted. You can save a modified version as a new user preset."
            )
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete the preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            preset_file = self._test_presets_dir / f"{preset_name}.json"
            try:
                preset_file.unlink()
                self._load_test_presets_list()
            except Exception as e:
                QMessageBox.warning(self, "Delete Error", f"Failed to delete preset: {e}")

    # Methods for exporting test data

    def get_test_config(self) -> dict:
        """Get current test configuration as a dictionary.

        Returns:
            Dictionary with discharge_type, value, voltage_cutoff, timed, duration
        """
        type_names = ["CC", "CR"]
        type_units = ["A", "ohm"]
        discharge_type = self.type_combo.currentIndex()

        return {
            "discharge_type": type_names[discharge_type],
            "discharge_type_index": discharge_type,
            "value": self.value_spin.value(),
            "value_unit": type_units[discharge_type],
            "voltage_cutoff": self.cutoff_spin.value(),
            "timed": self.timed_checkbox.isChecked(),
            "duration_seconds": self.duration_spin.value() if self.timed_checkbox.isChecked() else 0,
        }

    def get_battery_info(self) -> dict:
        """Get current battery info as a dictionary.

        Returns:
            Dictionary with battery information
        """
        return self.battery_info_widget.get_battery_info()

    def generate_test_filename(self) -> str:
        """Generate a cross-platform compatible filename for test data.

        Format: BatteryCapacity_{Manufacturer}_{BatteryName}_{DischargeType}_{Value}_{Cutoff}V_{YYYYMMDD_HHMMSS}.json
        Example: BatteryCapacity_Canon_LP-E6NH_CC_0.5A_3.0V-cutoff_20260209_093000.json

        Returns:
            Filename string (without path)
        """
        battery_info = self.battery_info_widget.get_battery_info()
        manufacturer = battery_info.get("manufacturer", "").strip() or "Unknown"
        battery_name = battery_info.get("name", "").strip() or "Unknown"
        type_names = ["CC", "CR"]
        type_units = ["A", "ohm"]
        discharge_type = self.type_combo.currentIndex()
        value = self.value_spin.value()
        cutoff = self.cutoff_spin.value()

        # Create timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Sanitize manufacturer and battery name
        safe_manufacturer = "".join(c if c.isalnum() or c in "-" else "-" for c in manufacturer).strip("-")
        safe_battery_name = "".join(c if c.isalnum() or c in "-" else "-" for c in battery_name).strip("-")

        # Build filename parts
        parts = [
            "BatteryCapacity",
            safe_manufacturer,
            safe_battery_name,
            type_names[discharge_type],
            f"{value}{type_units[discharge_type]}",
            f"{cutoff}V-cutoff",
            timestamp,
        ]

        filename = "_".join(parts)
        return f"{filename}.json"

    # Session persistence methods

    def _connect_save_signals(self) -> None:
        """Connect all form fields to save settings when changed."""
        # Test Conditions fields
        self.type_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.value_spin.valueChanged.connect(self._on_settings_changed)
        self.cutoff_spin.valueChanged.connect(self._on_settings_changed)
        self.timed_checkbox.toggled.connect(self._on_settings_changed)
        self.hours_spin.valueChanged.connect(self._sync_duration)
        self.minutes_spin.valueChanged.connect(self._sync_duration)
        self.hours_spin.valueChanged.connect(self._on_settings_changed)
        self.minutes_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Battery Info fields (handled by widget's settings_changed signal)
        self.battery_info_widget.settings_changed.connect(self._on_settings_changed)

        # Auto Save settings
        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self) -> None:
        """Handle any settings change - save to file."""
        if not self._loading_settings:
            self._save_last_session()

    def _save_last_session(self) -> None:
        """Save current settings to file."""
        # Get battery info from widget
        battery_info = self.battery_info_widget.get_battery_info()
        battery_info["preset"] = self.battery_info_widget.presets_combo.currentText()

        settings = {
            "test_config": {
                "discharge_type": self.type_combo.currentIndex(),
                "value": self.value_spin.value(),
                "voltage_cutoff": self.cutoff_spin.value(),
                "timed": self.timed_checkbox.isChecked(),
                "duration": self.duration_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "battery_info": battery_info,
            "autosave": self.autosave_checkbox.isChecked(),
        }

        try:
            with open(self._last_session_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass  # Silently fail - not critical

    def _load_last_session(self) -> None:
        """Load settings from file on startup."""
        if not self._last_session_file.exists():
            return

        try:
            with open(self._last_session_file, 'r') as f:
                settings = json.load(f)
        except Exception:
            return  # Silently fail - use defaults

        self._loading_settings = True  # Prevent saves during load

        try:
            # Load Test Conditions
            test_config = settings.get("test_config", {})
            if "discharge_type" in test_config:
                self.type_combo.setCurrentIndex(test_config["discharge_type"])
            if "value" in test_config:
                self.value_spin.setValue(test_config["value"])
            if "voltage_cutoff" in test_config:
                self.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.timed_checkbox.setChecked(test_config["timed"])
            if "duration" in test_config:
                self.duration_spin.setValue(test_config["duration"])
                self._sync_hours_minutes()
            if "preset" in test_config and test_config["preset"]:
                index = self.test_presets_combo.findText(test_config["preset"])
                if index >= 0:
                    self.test_presets_combo.setCurrentIndex(index)

            # Load Battery Info
            battery_info = settings.get("battery_info", {})
            self.battery_info_widget.set_battery_info(battery_info)
            if "preset" in battery_info and battery_info["preset"]:
                index = self.battery_info_widget.presets_combo.findText(battery_info["preset"])
                if index >= 0:
                    self.battery_info_widget.presets_combo.setCurrentIndex(index)

            # Load Auto Save setting
            if "autosave" in settings:
                self.autosave_checkbox.setChecked(settings["autosave"])

        finally:
            self._loading_settings = False
            # Update filename after loading settings
            self._update_filename()

    def set_battery_info(self, info: dict):
        """Set battery info from a dictionary (compatible with BatteryInfoWidget format).

        Args:
            info: Dictionary containing battery information
        """
        # Set loading flag to prevent triggering save/update signals
        was_loading = self._loading_settings
        self._loading_settings = True

        try:
            self.battery_info_widget.set_battery_info(info)
        finally:
            self._loading_settings = was_loading
