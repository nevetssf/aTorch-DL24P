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
from PySide6.QtCore import Qt, Slot, Signal

from ..automation.test_runner import TestRunner, TestProgress, TestState
from ..data.database import Database


class AutomationPanel(QWidget):
    """Panel for test automation control."""

    # Signal emitted when test should start: (discharge_type, value, voltage_cutoff, duration_s or 0)
    # discharge_type: 0=CC, 1=CP, 2=CR
    start_test_requested = Signal(int, float, float, int)
    # Signal emitted when pause is clicked (stops logging and load, keeps data)
    pause_test_requested = Signal()
    # Signal emitted when resume is clicked (continues logging and load)
    resume_test_requested = Signal()
    # Signal emitted when Apply is clicked: (discharge_type, value, voltage_cutoff, duration_s or 0)
    apply_settings_requested = Signal(int, float, float, int)
    # Signal emitted when manual Save is clicked (filename)
    manual_save_requested = Signal(str)
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
        config_group.setMaximumWidth(320)
        config_layout = QVBoxLayout(config_group)

        # Test presets row (at top)
        test_presets_layout = QHBoxLayout()
        test_presets_layout.addWidget(QLabel("Presets"))
        self.test_presets_combo = QComboBox()
        test_presets_layout.addWidget(self.test_presets_combo, 1)
        self.test_presets_combo.currentIndexChanged.connect(self._on_test_preset_selected)
        self.save_test_preset_btn = QPushButton("Save")
        self.save_test_preset_btn.setMaximumWidth(50)
        self.save_test_preset_btn.clicked.connect(self._save_test_preset)
        test_presets_layout.addWidget(self.save_test_preset_btn)
        self.delete_test_preset_btn = QPushButton("Delete")
        self.delete_test_preset_btn.setMaximumWidth(50)
        self.delete_test_preset_btn.setEnabled(False)
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
        self.type_combo.addItems(["CC", "CP", "CR"])
        self.type_combo.setToolTip("CC = Constant Current\nCP = Constant Power\nCR = Constant Resistance")
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
        time_limit_layout.addWidget(self.hours_spin)

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)
        self.minutes_spin.setValue(0)
        self.minutes_spin.setSuffix("m")
        self.minutes_spin.setEnabled(False)
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
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        params_panel_layout.addWidget(self.apply_btn)

        # Add parameters panel to config layout
        config_layout.addWidget(params_panel)

        # Load test presets into dropdown
        self._load_test_presets_list()

        layout.addWidget(config_group)

        # Middle: Battery info
        info_group = QGroupBox("Battery Info")
        info_group.setFixedWidth(350)
        info_main_layout = QVBoxLayout(info_group)

        # Presets row
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets"))
        self.presets_combo = QComboBox()
        self.presets_combo.setSizePolicy(self.presets_combo.sizePolicy().horizontalPolicy(), self.presets_combo.sizePolicy().verticalPolicy())
        presets_layout.addWidget(self.presets_combo, 1)  # Stretch to fill available space
        self.presets_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.save_preset_btn = QPushButton("Save")
        self.save_preset_btn.setMaximumWidth(50)
        self.save_preset_btn.clicked.connect(self._save_battery_preset)
        presets_layout.addWidget(self.save_preset_btn)
        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.setMaximumWidth(50)
        self.delete_preset_btn.setEnabled(False)  # Disabled until a user preset is selected
        self.delete_preset_btn.clicked.connect(self._delete_battery_preset)
        presets_layout.addWidget(self.delete_preset_btn)
        info_main_layout.addLayout(presets_layout)

        # Sub-panel for battery specs (outlined, no label)
        specs_group = QGroupBox()
        info_layout = QFormLayout(specs_group)
        info_layout.setContentsMargins(6, 6, 6, 6)

        self.battery_name_edit = QLineEdit()
        self.battery_name_edit.setPlaceholderText("e.g., INR18650-30Q")
        self.battery_name_edit.textChanged.connect(self._on_filename_field_changed)
        info_layout.addRow("Name", self.battery_name_edit)

        self.manufacturer_edit = QLineEdit()
        self.manufacturer_edit.setPlaceholderText("e.g., Samsung, LG, Panasonic")
        info_layout.addRow("Manufacturer", self.manufacturer_edit)

        self.oem_equiv_edit = QLineEdit()
        self.oem_equiv_edit.setPlaceholderText("e.g., 30Q, VTC6")
        info_layout.addRow("OEM Equivalent", self.oem_equiv_edit)

        voltage_tech_layout = QHBoxLayout()
        self.rated_voltage_spin = QDoubleSpinBox()
        self.rated_voltage_spin.setRange(0.0, 100.0)
        self.rated_voltage_spin.setDecimals(2)
        self.rated_voltage_spin.setValue(3.7)
        self.rated_voltage_spin.setSuffix(" V")
        voltage_tech_layout.addWidget(self.rated_voltage_spin)

        self.technology_combo = QComboBox()
        self.technology_combo.addItems(["Li-Ion", "LiPo", "NiMH", "NiCd", "LiFePO4", "Lead Acid"])
        self.technology_combo.setToolTip("Battery chemistry/technology")
        voltage_tech_layout.addWidget(self.technology_combo)
        info_layout.addRow("Rated Voltage", voltage_tech_layout)

        capacity_layout = QHBoxLayout()
        self.nominal_capacity_spin = QSpinBox()
        self.nominal_capacity_spin.setRange(0, 100000)
        self.nominal_capacity_spin.setValue(3000)
        self.nominal_capacity_spin.setSuffix(" mAh")
        capacity_layout.addWidget(self.nominal_capacity_spin)

        self.nominal_energy_spin = QDoubleSpinBox()
        self.nominal_energy_spin.setRange(0.0, 1000.0)
        self.nominal_energy_spin.setDecimals(2)
        self.nominal_energy_spin.setValue(11.1)
        self.nominal_energy_spin.setSuffix(" Wh")
        capacity_layout.addWidget(self.nominal_energy_spin)
        info_layout.addRow("Capacity (Nom)", capacity_layout)

        info_main_layout.addWidget(specs_group)

        # Sub-panel for Serial Number and Notes (outlined, no label)
        instance_group = QGroupBox()
        instance_layout = QFormLayout(instance_group)
        instance_layout.setContentsMargins(6, 6, 6, 6)

        self.serial_number_edit = QLineEdit()
        self.serial_number_edit.setPlaceholderText("e.g., SN123456")
        instance_layout.addRow("Serial Number", self.serial_number_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(50)
        self.notes_edit.setPlaceholderText("Test notes...")
        instance_layout.addRow("Notes", self.notes_edit)

        info_main_layout.addWidget(instance_group)
        layout.addWidget(info_group)

        # Load battery presets into dropdown
        self._load_battery_presets_list()

        # Right: Test control
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Abort button
        self.start_btn = QPushButton("Start")
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
        self.autosave_checkbox.toggled.connect(self._on_autosave_toggled)
        autosave_layout.addWidget(self.autosave_checkbox)
        self.save_btn = QPushButton("Save")
        self.save_btn.setMaximumWidth(50)
        self.save_btn.clicked.connect(self._on_save_clicked)
        autosave_layout.addWidget(self.save_btn)
        self.load_btn = QPushButton("Load")
        self.load_btn.setMaximumWidth(50)
        self.load_btn.clicked.connect(self._on_load_clicked)
        autosave_layout.addWidget(self.load_btn)
        self.export_btn = QPushButton("Export")
        self.export_btn.setMaximumWidth(60)
        self.export_btn.clicked.connect(self._on_export_clicked)
        autosave_layout.addWidget(self.export_btn)
        self.show_folder_btn = QPushButton("Show Folder")
        self.show_folder_btn.setMaximumWidth(80)
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
                type_map = {"CC": 0, "CP": 1, "CR": 2}
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
            if "name" in battery_info:
                self.battery_name_edit.setText(battery_info["name"])
            if "manufacturer" in battery_info:
                self.manufacturer_edit.setText(battery_info["manufacturer"])
            if "oem_equivalent" in battery_info:
                self.oem_equiv_edit.setText(battery_info["oem_equivalent"])
            if "serial_number" in battery_info:
                self.serial_number_edit.setText(battery_info["serial_number"])
            if "rated_voltage" in battery_info:
                self.rated_voltage_spin.setValue(battery_info["rated_voltage"])
            if "technology" in battery_info:
                tech_index = self.technology_combo.findText(battery_info["technology"])
                if tech_index >= 0:
                    self.technology_combo.setCurrentIndex(tech_index)
            if "nominal_capacity_mah" in battery_info:
                self.nominal_capacity_spin.setValue(battery_info["nominal_capacity_mah"])
            if "nominal_energy_wh" in battery_info:
                self.nominal_energy_spin.setValue(battery_info["nominal_energy_wh"])
            if "notes" in battery_info:
                self.notes_edit.setPlainText(battery_info["notes"])

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
        if self.autosave_checkbox.isChecked():
            self.filename_edit.setText(self.generate_test_filename())

    @Slot()
    def _on_filename_field_changed(self) -> None:
        """Handle changes to fields that affect the filename."""
        self._update_filename()

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
        elif index == 1:  # CP - Constant Power
            self.value_label.setText("Power (W):")
            self.value_spin.setToolTip("Discharge power in Watts")
            self.value_spin.setRange(0.0, 200.0)
            self.value_spin.setDecimals(2)
            self.value_spin.setSingleStep(1.0)
            self.value_spin.setValue(5.0)
        elif index == 2:  # CR - Constant Resistance
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
            self._update_ui_stopped()
            # Emit with zeros to signal stop
            self.start_test_requested.emit(0, 0, 0, 0)
        else:
            # Get test parameters (connection check will happen in main_window)
            discharge_type = self.type_combo.currentIndex()  # 0=CC, 1=CP, 2=CR
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
        discharge_type = self.type_combo.currentIndex()  # 0=CC, 1=CP, 2=CR
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

    def _update_ui_stopped(self) -> None:
        """Update UI for stopped state."""
        self.start_btn.setText("Start")
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
        nominal_capacity = self.nominal_capacity_spin.value()
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
        self.presets_combo.clear()
        self.presets_combo.addItem("")  # Empty option

        # Add Camera Presets section
        if self._camera_battery_presets:
            self.presets_combo.addItem("--- Camera Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._camera_battery_presets.keys()):
                self.presets_combo.addItem(preset_name)

        # Add Household Presets section
        if self._household_battery_presets:
            self.presets_combo.insertSeparator(self.presets_combo.count())
            self.presets_combo.addItem("--- Household Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._household_battery_presets.keys()):
                self.presets_combo.addItem(preset_name)

        # Get user presets from files
        user_presets = sorted(self._battery_presets_dir.glob("*.json"))
        if user_presets:
            # Add separator and header
            self.presets_combo.insertSeparator(self.presets_combo.count())
            self.presets_combo.addItem("--- User Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            # Add user presets
            for preset_file in user_presets:
                self.presets_combo.addItem(preset_file.stem)

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
        preset_name = self.presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            # Empty or separator - disable delete
            self.delete_preset_btn.setEnabled(False)
            return

        # Check if this is a default preset
        is_default = self._is_default_battery_preset(preset_name)

        # Enable/disable delete button (can't delete defaults)
        self.delete_preset_btn.setEnabled(not is_default)

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
        self.battery_name_edit.setText(data.get("name", ""))
        self.manufacturer_edit.setText(data.get("manufacturer", ""))
        self.oem_equiv_edit.setText(data.get("oem_equivalent", ""))
        self.serial_number_edit.setText(data.get("serial_number", ""))
        self.rated_voltage_spin.setValue(data.get("rated_voltage", 3.7))
        self.nominal_capacity_spin.setValue(data.get("nominal_capacity", 3000))
        self.nominal_energy_spin.setValue(data.get("nominal_energy", 11.1))
        self.notes_edit.setPlainText(data.get("notes", ""))
        # Set technology if available
        technology = data.get("technology", "Li-Ion")
        tech_index = self.technology_combo.findText(technology)
        if tech_index >= 0:
            self.technology_combo.setCurrentIndex(tech_index)

    @Slot()
    def _save_battery_preset(self) -> None:
        """Save current battery info as a preset."""
        # Build default name from manufacturer and battery name
        manufacturer = self.manufacturer_edit.text().strip()
        battery_name = self.battery_name_edit.text().strip()
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

        data = {
            "name": self.battery_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "oem_equivalent": self.oem_equiv_edit.text(),
            "serial_number": self.serial_number_edit.text(),
            "rated_voltage": self.rated_voltage_spin.value(),
            "nominal_capacity": self.nominal_capacity_spin.value(),
            "nominal_energy": self.nominal_energy_spin.value(),
            "technology": self.technology_combo.currentText(),
            "notes": self.notes_edit.toPlainText(),
        }

        preset_file = self._battery_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_battery_presets_list()
            # Select the newly saved preset
            index = self.presets_combo.findText(safe_name)
            if index >= 0:
                self.presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    @Slot()
    def _delete_battery_preset(self) -> None:
        """Delete the currently selected preset."""
        preset_name = self.presets_combo.currentText()
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
        type_names = ["CC", "CP", "CR"]
        type_units = ["A", "W", "ohm"]
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
        type_names = ["CC", "CP", "CR"]
        type_units = ["A", "W", "ohm"]
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
        return {
            "name": self.battery_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "oem_equivalent": self.oem_equiv_edit.text(),
            "serial_number": self.serial_number_edit.text(),
            "rated_voltage": self.rated_voltage_spin.value(),
            "technology": self.technology_combo.currentText(),
            "nominal_capacity_mah": self.nominal_capacity_spin.value(),
            "nominal_energy_wh": self.nominal_energy_spin.value(),
            "notes": self.notes_edit.toPlainText(),
        }

    def generate_test_filename(self) -> str:
        """Generate a cross-platform compatible filename for test data.

        Format: BatteryName_DischargeType_Value_YYYYMMDD_HHMMSS.json
        Example: Canon_LP-E6NH_CC_0.5A_20260209_093000.json

        Returns:
            Filename string (without path)
        """
        battery_name = self.battery_name_edit.text().strip() or "Unknown"
        type_names = ["CC", "CP", "CR"]
        type_units = ["A", "W", "ohm"]
        discharge_type = self.type_combo.currentIndex()
        value = self.value_spin.value()

        # Create timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build filename parts
        parts = [
            battery_name,
            type_names[discharge_type],
            f"{value}{type_units[discharge_type]}",
            timestamp,
        ]

        # Join and sanitize (allow alphanumeric, spaces, hyphens, underscores, periods)
        filename = "_".join(parts)
        safe_filename = "".join(c for c in filename if c.isalnum() or c in " -_.").strip()

        return f"{safe_filename}.json"

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

        # Battery Info fields
        self.battery_name_edit.textChanged.connect(self._on_settings_changed)
        self.manufacturer_edit.textChanged.connect(self._on_settings_changed)
        self.oem_equiv_edit.textChanged.connect(self._on_settings_changed)
        self.serial_number_edit.textChanged.connect(self._on_settings_changed)
        self.rated_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.nominal_capacity_spin.valueChanged.connect(self._on_settings_changed)
        self.nominal_energy_spin.valueChanged.connect(self._on_settings_changed)
        self.technology_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.notes_edit.textChanged.connect(self._on_settings_changed)
        self.presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Auto Save settings
        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self) -> None:
        """Handle any settings change - save to file."""
        if not self._loading_settings:
            self._save_last_session()

    def _save_last_session(self) -> None:
        """Save current settings to file."""
        settings = {
            "test_config": {
                "discharge_type": self.type_combo.currentIndex(),
                "value": self.value_spin.value(),
                "voltage_cutoff": self.cutoff_spin.value(),
                "timed": self.timed_checkbox.isChecked(),
                "duration": self.duration_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "battery_info": {
                "name": self.battery_name_edit.text(),
                "manufacturer": self.manufacturer_edit.text(),
                "oem_equivalent": self.oem_equiv_edit.text(),
                "serial_number": self.serial_number_edit.text(),
                "rated_voltage": self.rated_voltage_spin.value(),
                "technology": self.technology_combo.currentText(),
                "nominal_capacity": self.nominal_capacity_spin.value(),
                "nominal_energy": self.nominal_energy_spin.value(),
                "notes": self.notes_edit.toPlainText(),
                "preset": self.presets_combo.currentText(),
            },
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
            if "name" in battery_info:
                self.battery_name_edit.setText(battery_info["name"])
            if "manufacturer" in battery_info:
                self.manufacturer_edit.setText(battery_info["manufacturer"])
            if "oem_equivalent" in battery_info:
                self.oem_equiv_edit.setText(battery_info["oem_equivalent"])
            if "serial_number" in battery_info:
                self.serial_number_edit.setText(battery_info["serial_number"])
            if "rated_voltage" in battery_info:
                self.rated_voltage_spin.setValue(battery_info["rated_voltage"])
            if "technology" in battery_info:
                tech_index = self.technology_combo.findText(battery_info["technology"])
                if tech_index >= 0:
                    self.technology_combo.setCurrentIndex(tech_index)
            if "nominal_capacity" in battery_info:
                self.nominal_capacity_spin.setValue(battery_info["nominal_capacity"])
            if "nominal_energy" in battery_info:
                self.nominal_energy_spin.setValue(battery_info["nominal_energy"])
            if "notes" in battery_info:
                self.notes_edit.setPlainText(battery_info["notes"])
            if "preset" in battery_info and battery_info["preset"]:
                index = self.presets_combo.findText(battery_info["preset"])
                if index >= 0:
                    self.presets_combo.setCurrentIndex(index)

            # Load Auto Save setting
            if "autosave" in settings:
                self.autosave_checkbox.setChecked(settings["autosave"])

        finally:
            self._loading_settings = False
            # Update filename after loading settings
            self._update_filename()
