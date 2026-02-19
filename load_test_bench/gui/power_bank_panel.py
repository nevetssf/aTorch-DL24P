"""Power Bank test panel for capacity testing at USB output voltages."""

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


class PowerBankPanel(QWidget):
    """Panel for power bank capacity testing at USB output voltages."""

    # Signal emitted when test should start: (discharge_type, value, voltage_cutoff, duration_s or 0)
    # For power banks, typically CC mode at the chosen output voltage
    start_test_requested = Signal(int, float, float, int)
    # Signal emitted when Apply is clicked
    apply_settings_requested = Signal(int, float, float, int)
    # Signal emitted when manual Save is clicked (filename)
    manual_save_requested = Signal(str)
    # Signal emitted when session is loaded from file (readings list)
    session_loaded = Signal(list)
    # Signal emitted when Export CSV is clicked
    export_csv_requested = Signal()
    # Signal emitted when test starts/stops
    test_started = Signal()
    test_stopped = Signal()

    def __init__(self, test_runner: TestRunner, database: Database):
        super().__init__()

        self.test_runner = test_runner
        self.database = database
        self._loading_settings = False  # Flag to prevent save during load

        # Load default presets from resources/power_bank directory
        self._default_power_bank_presets = self._load_presets_file("power_bank/presets_power_banks.json")
        self._default_test_presets = self._load_presets_file("power_bank/presets_test.json")

        # User presets directories and settings file
        from ..config import get_data_dir
        self._atorch_dir = get_data_dir()
        self._power_bank_presets_dir = self._atorch_dir / "presets" / "power_bank_presets"
        self._test_presets_dir = self._atorch_dir / "presets" / "power_bank_test_presets"
        self._last_session_file = self._atorch_dir / "sessions" / "power_bank_session.json"

        self._create_ui()
        self._connect_save_signals()
        self._load_last_session()

    def _load_presets_file(self, filename: str) -> dict:
        """Load presets from a file in the resources directory."""
        module_dir = Path(__file__).parent.parent.parent
        presets_file = module_dir / "resources" / filename

        try:
            with open(presets_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _create_ui(self) -> None:
        """Create the power bank panel UI."""
        layout = QHBoxLayout(self)

        # Left: Test configuration
        config_group = QGroupBox("Test Conditions")
        config_group.setFixedWidth(350)
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

        # Load settings panel
        load_group = QGroupBox()
        load_layout = QFormLayout(load_group)
        load_layout.setContentsMargins(6, 6, 6, 6)

        # Load type selection (CC, CR, CP)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Current", "Resistance", "Power"])
        self.type_combo.setToolTip("CC = Constant Current\nCR = Constant Resistance\nCP = Constant Power")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.type_combo.currentIndexChanged.connect(self._on_filename_field_changed)
        load_layout.addRow("Load Type", self.type_combo)

        # Test value (current/resistance/power depending on type)
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 24.0)
        self.value_spin.setDecimals(3)
        self.value_spin.setSingleStep(0.1)
        self.value_spin.setValue(1.0)
        self.value_spin.setSuffix(" A")
        self.value_spin.setToolTip("Discharge value (current/resistance/power depending on type)")
        self.value_spin.valueChanged.connect(self._on_filename_field_changed)
        self.value_label = QLabel("Current")
        self.value_label.setMinimumWidth(85)
        load_layout.addRow(self.value_label, self.value_spin)

        # Voltage cutoff
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(2.5, 20.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(4.0)
        self.cutoff_spin.setSuffix(" V")
        self.cutoff_spin.setToolTip("Safety cutoff voltage (power bank will shut down automatically)")
        load_layout.addRow("V Cutoff", self.cutoff_spin)

        config_layout.addWidget(load_group)

        # Time Limit panel
        time_limit_group = QGroupBox()
        time_limit_layout = QFormLayout(time_limit_group)
        time_limit_layout.setContentsMargins(6, 6, 6, 6)

        time_row = QHBoxLayout()
        self.timed_checkbox = QCheckBox()
        self.timed_checkbox.setChecked(False)
        self.timed_checkbox.setToolTip("Enable time limit for test")
        self.timed_checkbox.toggled.connect(self._on_timed_toggled)
        time_row.addWidget(self.timed_checkbox)

        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 99)
        self.hours_spin.setValue(4)
        self.hours_spin.setSuffix("h")
        self.hours_spin.setEnabled(False)
        time_row.addWidget(self.hours_spin)

        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)
        self.minutes_spin.setValue(0)
        self.minutes_spin.setSuffix("m")
        self.minutes_spin.setEnabled(False)
        time_row.addWidget(self.minutes_spin)

        # Keep duration_spin for backwards compatibility
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 86400)
        self.duration_spin.setValue(14400)  # 4 hours default
        self.duration_spin.setVisible(False)

        # Start Delay
        time_row.addSpacing(10)
        time_row.addWidget(QLabel("Delay"))
        self.start_delay_spin = QSpinBox()
        self.start_delay_spin.setRange(0, 60)
        self.start_delay_spin.setValue(5)
        self.start_delay_spin.setSuffix("s")
        self.start_delay_spin.setToolTip("Delay before turning on load (captures unloaded voltage)")
        time_row.addWidget(self.start_delay_spin)

        time_limit_layout.addRow("Time Limit", time_row)

        config_layout.addWidget(time_limit_group)

        # Apply button
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        config_layout.addWidget(self.apply_btn)

        # Keep params_form reference for compatibility
        self.params_form = load_layout
        self._load_test_presets_list()

        # Power Supply Setting
        ps_group = QGroupBox("Power Supply Setting")
        ps_layout = QFormLayout(ps_group)
        ps_layout.setContentsMargins(6, 6, 6, 6)

        self.ps_voltage_spin = QDoubleSpinBox()
        self.ps_voltage_spin.setRange(0.0, 60.0)
        self.ps_voltage_spin.setDecimals(2)
        self.ps_voltage_spin.setSingleStep(0.1)
        self.ps_voltage_spin.setValue(5.0)
        self.ps_voltage_spin.setSuffix(" V")

        self.ps_voltage_preset_combo = QComboBox()
        self.ps_voltage_preset_combo.addItems(["5V", "9V", "12V", "15V", "20V"])
        self.ps_voltage_preset_combo.currentTextChanged.connect(
            lambda text: self.ps_voltage_spin.setValue(float(text.replace("V", "")))
        )

        self.ps_auto_checkbox = QCheckBox("Auto")
        self.ps_auto_checkbox.setChecked(True)
        self.ps_auto_checkbox.setToolTip("Auto-detect voltage from device at test start")
        self.ps_auto_checkbox.toggled.connect(self._on_ps_auto_toggled)

        ps_voltage_row = QHBoxLayout()
        ps_voltage_row.addWidget(self.ps_voltage_spin)
        ps_voltage_row.addWidget(self.ps_voltage_preset_combo)
        ps_voltage_row.addWidget(self.ps_auto_checkbox)
        ps_layout.addRow("Set Voltage", ps_voltage_row)

        # Start with fields disabled since Auto is checked by default
        self.ps_voltage_spin.setEnabled(False)
        self.ps_voltage_preset_combo.setEnabled(False)

        config_layout.addWidget(ps_group)
        config_layout.addStretch()

        layout.addWidget(config_group)

        # Middle: Power Bank info
        info_group = QGroupBox("Power Bank Info")
        info_group.setFixedWidth(350)
        info_main_layout = QVBoxLayout(info_group)

        # Presets row
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets"))
        self.presets_combo = QComboBox()
        presets_layout.addWidget(self.presets_combo, 1)
        self.presets_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.save_preset_btn = QPushButton("Save")
        self.save_preset_btn.setMaximumWidth(50)
        self.save_preset_btn.clicked.connect(self._save_power_bank_preset)
        presets_layout.addWidget(self.save_preset_btn)
        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.setMaximumWidth(50)
        self.delete_preset_btn.setEnabled(False)
        self.delete_preset_btn.clicked.connect(self._delete_power_bank_preset)
        presets_layout.addWidget(self.delete_preset_btn)
        info_main_layout.addLayout(presets_layout)

        # Sub-panel for power bank specs (outlined, no label)
        specs_group = QGroupBox()
        info_layout = QFormLayout(specs_group)
        info_layout.setContentsMargins(6, 6, 6, 6)

        self.power_bank_name_edit = QLineEdit()
        self.power_bank_name_edit.setPlaceholderText("e.g., Anker PowerCore 20000")
        self.power_bank_name_edit.textChanged.connect(self._on_filename_field_changed)
        info_layout.addRow("Name", self.power_bank_name_edit)

        self.manufacturer_edit = QLineEdit()
        self.manufacturer_edit.setPlaceholderText("e.g., Anker, RAVPower, Aukey")
        info_layout.addRow("Manufacturer", self.manufacturer_edit)

        model_pd_layout = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("e.g., A1271")
        model_pd_layout.addWidget(self.model_edit)

        self.pd_checkbox = QCheckBox("PD")
        self.pd_checkbox.setToolTip("USB Power Delivery device")
        model_pd_layout.addWidget(self.pd_checkbox)

        info_layout.addRow("Model", model_pd_layout)

        info_main_layout.addWidget(specs_group)

        # Rated Specs panel
        self.rated_group = QGroupBox("Rated")
        rated_layout = QFormLayout(self.rated_group)
        rated_layout.setContentsMargins(6, 6, 6, 6)

        # Rated capacity
        capacity_layout = QHBoxLayout()
        self.rated_capacity_spin = QSpinBox()
        self.rated_capacity_spin.setRange(0, 100000)
        self.rated_capacity_spin.setValue(20000)
        self.rated_capacity_spin.setSuffix(" mAh")
        self.rated_capacity_spin.setToolTip("Rated capacity at 3.7V (as printed on power bank)")
        capacity_layout.addWidget(self.rated_capacity_spin)

        self.rated_energy_spin = QDoubleSpinBox()
        self.rated_energy_spin.setRange(0.0, 1000.0)
        self.rated_energy_spin.setDecimals(2)
        self.rated_energy_spin.setValue(74.0)
        self.rated_energy_spin.setSuffix(" Wh")
        self.rated_energy_spin.setToolTip("Rated energy (capacity × 3.7V)")
        capacity_layout.addWidget(self.rated_energy_spin)
        rated_layout.addRow("Capacity", capacity_layout)

        # Rated output: Power, Voltage, Current
        rated_output_layout = QHBoxLayout()

        self.max_output_power_spin = QDoubleSpinBox()
        self.max_output_power_spin.setRange(0.0, 500.0)
        self.max_output_power_spin.setDecimals(1)
        self.max_output_power_spin.setValue(30.0)
        self.max_output_power_spin.setSuffix(" W")
        self.max_output_power_spin.setToolTip("Rated output power")
        rated_output_layout.addWidget(self.max_output_power_spin)

        self.rated_voltage_spin = QDoubleSpinBox()
        self.rated_voltage_spin.setRange(0.0, 100.0)
        self.rated_voltage_spin.setDecimals(1)
        self.rated_voltage_spin.setValue(5.0)
        self.rated_voltage_spin.setSuffix(" V")
        self.rated_voltage_spin.setToolTip("Rated output voltage")
        rated_output_layout.addWidget(self.rated_voltage_spin)

        self.rated_current_spin = QDoubleSpinBox()
        self.rated_current_spin.setRange(0.0, 20.0)
        self.rated_current_spin.setDecimals(1)
        self.rated_current_spin.setValue(3.0)
        self.rated_current_spin.setSuffix(" A")
        self.rated_current_spin.setToolTip("Rated output current")
        rated_output_layout.addWidget(self.rated_current_spin)

        rated_layout.addRow("Output", rated_output_layout)

        info_main_layout.addWidget(self.rated_group)

        # Sub-panel for Serial Number and Notes (outlined, no label)
        instance_group = QGroupBox()
        instance_layout = QFormLayout(instance_group)
        instance_layout.setContentsMargins(6, 6, 6, 6)

        self.serial_number_edit = QLineEdit()
        self.serial_number_edit.setPlaceholderText("e.g., SN123456")
        instance_layout.addRow("SN", self.serial_number_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(34)
        self.notes_edit.setPlaceholderText("Notes...")
        instance_layout.addRow(self.notes_edit)

        info_main_layout.addWidget(instance_group)
        layout.addWidget(info_group)

        # Load power bank presets into dropdown
        self._load_power_bank_presets_list()

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
        font.setBold(False)
        self.elapsed_label.setFont(font)
        control_layout.addWidget(self.elapsed_label)

        # Remaining time estimate
        self.remaining_label = QLabel("")
        self.remaining_label.setAlignment(Qt.AlignCenter)
        self.remaining_label.setStyleSheet("color: #666;")
        control_layout.addWidget(self.remaining_label)

        control_layout.addSpacing(-5)

        # Test Summary table (adapted for power banks)
        summary_group = QGroupBox("Test Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(6, 0, 6, 6)

        self.summary_table = QTableWidget(2, 4)
        self.summary_table.setHorizontalHeaderLabels(["Capacity", "Energy", "Avg V", "Avg I"])
        self.summary_table.setVerticalHeaderLabels(["Output", "Output vs Rated"])
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.NoSelection)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Set columns to stretch equally
        for col in range(4):
            self.summary_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)

        # Make rows taller
        for row in range(2):
            self.summary_table.setRowHeight(row, 35)

        # Create value items
        self.summary_capacity_item = QTableWidgetItem("--")
        self.summary_energy_item = QTableWidgetItem("--")
        self.summary_avg_voltage_item = QTableWidgetItem("--")
        self.summary_avg_current_item = QTableWidgetItem("--")
        self.summary_efficiency_capacity_item = QTableWidgetItem("--")
        self.summary_efficiency_energy_item = QTableWidgetItem("--")

        # Center align all values
        for item in [self.summary_capacity_item, self.summary_energy_item,
                     self.summary_avg_voltage_item, self.summary_avg_current_item,
                     self.summary_efficiency_capacity_item, self.summary_efficiency_energy_item]:
            item.setTextAlignment(Qt.AlignCenter)

        self.summary_table.setItem(0, 0, self.summary_capacity_item)
        self.summary_table.setItem(0, 1, self.summary_energy_item)
        self.summary_table.setItem(0, 2, self.summary_avg_voltage_item)
        self.summary_table.setItem(0, 3, self.summary_avg_current_item)
        self.summary_table.setItem(1, 0, self.summary_efficiency_capacity_item)
        self.summary_table.setItem(1, 1, self.summary_efficiency_energy_item)
        # Row 1, cols 2-3: Avg V % vs Set Voltage, Avg I % vs set current
        self.summary_avg_voltage_pct_item = QTableWidgetItem("--")
        self.summary_avg_voltage_pct_item.setTextAlignment(Qt.AlignCenter)
        self.summary_table.setItem(1, 2, self.summary_avg_voltage_pct_item)
        self.summary_avg_current_pct_item = QTableWidgetItem("--")
        self.summary_avg_current_pct_item.setTextAlignment(Qt.AlignCenter)
        self.summary_table.setItem(1, 3, self.summary_avg_current_pct_item)

        # Set fixed height
        table_height = (self.summary_table.horizontalHeader().height() +
                       self.summary_table.verticalHeader().sectionSize(0) * 2 +
                       self.summary_table.rowHeight(0) + 2)
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
        self.filename_edit.setReadOnly(True)
        self.filename_edit.setPlaceholderText("Test filename...")
        self._update_filename()
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
            self._update_filename()

    @Slot()
    def _on_save_clicked(self) -> None:
        """Handle manual Save button click."""
        filename = self.filename_edit.text().strip()
        if filename:
            if not filename.endswith('.json'):
                filename += '.json'
            self.manual_save_requested.emit(filename)

    @Slot()
    def _on_load_clicked(self) -> None:
        """Handle Load button click."""
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

        self._loading_settings = True

        try:
            # Load test configuration
            test_config = data.get("test_config", {})
            if "load_type_index" in test_config:
                self.type_combo.setCurrentIndex(test_config["load_type_index"])
            if "value" in test_config:
                self.value_spin.setValue(test_config["value"])
            elif "current" in test_config:
                self.value_spin.setValue(test_config["current"])
            if "voltage_cutoff" in test_config:
                self.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.timed_checkbox.setChecked(test_config["timed"])
            if "duration_seconds" in test_config:
                self.duration_spin.setValue(test_config["duration_seconds"])
                self._sync_hours_minutes()
            if "start_delay" in test_config:
                self.start_delay_spin.setValue(test_config["start_delay"])

            # Load power bank info
            power_bank_info = data.get("power_bank_info", {})
            if "name" in power_bank_info:
                self.power_bank_name_edit.setText(power_bank_info["name"])
            if "manufacturer" in power_bank_info:
                self.manufacturer_edit.setText(power_bank_info["manufacturer"])
            if "model" in power_bank_info:
                self.model_edit.setText(power_bank_info["model"])
            if "serial_number" in power_bank_info:
                self.serial_number_edit.setText(power_bank_info["serial_number"])
            if "rated_capacity_mah" in power_bank_info:
                self.rated_capacity_spin.setValue(power_bank_info["rated_capacity_mah"])
            if "rated_energy_wh" in power_bank_info:
                self.rated_energy_spin.setValue(power_bank_info["rated_energy_wh"])
            if "max_output_power_w" in power_bank_info:
                self.max_output_power_spin.setValue(power_bank_info["max_output_power_w"])
            if "rated_voltage_v" in power_bank_info:
                self.rated_voltage_spin.setValue(power_bank_info["rated_voltage_v"])
            if "rated_current_a" in power_bank_info:
                self.rated_current_spin.setValue(power_bank_info["rated_current_a"])
            if "pd" in power_bank_info:
                self.pd_checkbox.setChecked(power_bank_info["pd"])
            if "notes" in power_bank_info:
                self.notes_edit.setPlainText(power_bank_info["notes"])

            self.filename_edit.setText(Path(file_path).name)

            # Emit readings for display
            readings = data.get("readings", [])
            if readings:
                self.session_loaded.emit(readings)
                self._update_summary_from_readings(readings)

        finally:
            self._loading_settings = False

    @Slot()
    def _on_export_clicked(self) -> None:
        """Handle Export button click."""
        self.export_csv_requested.emit()

    @Slot()
    def _on_show_folder_clicked(self) -> None:
        """Handle Show Folder button click."""
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
        # Don't update filename during loading to preserve loaded filename
        if not self._loading_settings and self.autosave_checkbox.isChecked():
            self.filename_edit.setText(self.generate_test_filename())

    @Slot()
    def _on_filename_field_changed(self) -> None:
        """Handle changes to fields that affect the filename."""
        self._update_filename()

    def _on_ps_auto_toggled(self, checked: bool) -> None:
        """Enable/disable PS voltage fields based on Auto checkbox."""
        self.ps_voltage_spin.setEnabled(not checked)
        self.ps_voltage_preset_combo.setEnabled(not checked)

    def _on_type_changed(self, index: int) -> None:
        """Handle load type selection change."""
        if index == 0:  # CC - Constant Current
            self.value_label.setText("Current")
            self.value_spin.setSuffix(" A")
            self.value_spin.setToolTip("Discharge current in Amps")
            self.value_spin.setRange(0.0, 24.0)
            self.value_spin.setDecimals(3)
            self.value_spin.setSingleStep(0.1)
            self.value_spin.setValue(1.0)
        elif index == 1:  # CR - Constant Resistance
            self.value_label.setText("Resistance")
            self.value_spin.setSuffix(" \u03a9")
            self.value_spin.setToolTip("Load resistance in Ohms")
            self.value_spin.setRange(0.1, 9999.0)
            self.value_spin.setDecimals(1)
            self.value_spin.setSingleStep(1.0)
            self.value_spin.setValue(10.0)
        elif index == 2:  # CP - Constant Power
            self.value_label.setText("Power")
            self.value_spin.setSuffix(" W")
            self.value_spin.setToolTip("Discharge power in Watts")
            self.value_spin.setRange(0.0, 200.0)
            self.value_spin.setDecimals(1)
            self.value_spin.setSingleStep(1.0)
            self.value_spin.setValue(5.0)

    @Slot()
    def _on_start_clicked(self) -> None:
        """Handle start/abort button click."""
        if self.start_btn.text() == "Abort":
            self._update_ui_stopped()
            self.start_test_requested.emit(0, 0, 0, 0)
            self.test_stopped.emit()
        else:
            # Map combo index to discharge type: 0=CC, 1=CR, 2=CP
            type_map = [0, 2, 1]  # combo index 0→CC(0), 1→CR(2), 2→CP(1)
            discharge_type = type_map[self.type_combo.currentIndex()]
            value = self.value_spin.value()
            cutoff = self.cutoff_spin.value()
            duration = self.duration_spin.value() if self.timed_checkbox.isChecked() else 0

            # Refresh filename if autosave is enabled
            if self.autosave_checkbox.isChecked():
                new_filename = self.generate_test_filename()
                self.filename_edit.setText(new_filename)

            # Apply settings first, then start test (connection check in main_window)
            self.apply_settings_requested.emit(discharge_type, value, cutoff, duration)
            self.start_test_requested.emit(discharge_type, value, cutoff, duration)
            self._update_ui_running()
            self.test_started.emit()

    @Slot()
    def _on_apply_clicked(self) -> None:
        """Handle Apply button click - sends settings to device."""
        type_map = [0, 2, 1]  # combo index 0→CC(0), 1→CR(2), 2→CP(1)
        discharge_type = type_map[self.type_combo.currentIndex()]
        value = self.value_spin.value()
        cutoff = self.cutoff_spin.value()
        duration = self.duration_spin.value() if self.timed_checkbox.isChecked() else 0

        self.apply_settings_requested.emit(discharge_type, value, cutoff, duration)

    def update_progress(self, progress: TestProgress) -> None:
        """Update UI with test progress."""
        self.status_label.setText(progress.message or progress.state.name)
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        h = progress.elapsed_seconds // 3600
        m = (progress.elapsed_seconds % 3600) // 60
        s = progress.elapsed_seconds % 60
        self.elapsed_label.setText(f"{h}h {m}m {s}s")

        if progress.state in (
            TestState.COMPLETED,
            TestState.VOLTAGE_CUTOFF,
            TestState.TIMEOUT,
            TestState.ERROR,
        ):
            self._update_ui_stopped()

    def update_start_delay_countdown(self, remaining: int) -> None:
        """Update status label with start delay countdown.

        Args:
            remaining: Seconds remaining in start delay
        """
        self.status_label.setText(f"Starting in {remaining} seconds")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

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
        self.start_delay_spin.setEnabled(False)

        # Reset tracking lists and summary for new test
        self._voltage_readings = []
        self._current_readings = []
        self.summary_capacity_item.setText("--")
        self.summary_energy_item.setText("--")
        self.summary_avg_voltage_item.setText("--")
        self.summary_avg_current_item.setText("--")
        self.summary_efficiency_capacity_item.setText("--")
        self.summary_efficiency_energy_item.setText("--")
        self.summary_avg_voltage_pct_item.setText("--")
        self.summary_avg_current_pct_item.setText("--")

    def _update_ui_stopped(self) -> None:
        """Update UI for stopped state."""
        self.start_btn.setText("Start")
        if self.test_runner and self.test_runner.device and self.test_runner.device.is_connected:
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.start_btn.setEnabled(True)
        else:
            self.status_label.setText("Not Connected")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.start_btn.setEnabled(True)  # Allow auto-connect
        self.type_combo.setEnabled(True)
        self.value_spin.setEnabled(True)
        self.cutoff_spin.setEnabled(True)
        self.timed_checkbox.setEnabled(True)
        self.hours_spin.setEnabled(self.timed_checkbox.isChecked())
        self.minutes_spin.setEnabled(self.timed_checkbox.isChecked())
        self.start_delay_spin.setEnabled(True)
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
        self.ps_voltage_spin.setEnabled(enabled and not self.ps_auto_checkbox.isChecked())
        self.ps_voltage_preset_combo.setEnabled(enabled and not self.ps_auto_checkbox.isChecked())
        self.timed_checkbox.setEnabled(enabled)
        self.hours_spin.setEnabled(enabled and self.timed_checkbox.isChecked())
        self.minutes_spin.setEnabled(enabled and self.timed_checkbox.isChecked())
        self.start_delay_spin.setEnabled(enabled)
        self.presets_combo.setEnabled(enabled)
        self.save_preset_btn.setEnabled(enabled)
        self.delete_preset_btn.setEnabled(enabled)
        self.power_bank_name_edit.setEnabled(enabled)
        self.manufacturer_edit.setEnabled(enabled)
        self.model_edit.setEnabled(enabled)
        self.rated_capacity_spin.setEnabled(enabled)
        self.rated_energy_spin.setEnabled(enabled)
        self.max_output_power_spin.setEnabled(enabled)
        self.rated_voltage_spin.setEnabled(enabled)
        self.rated_current_spin.setEnabled(enabled)
        self.pd_checkbox.setEnabled(enabled)
        self.serial_number_edit.setEnabled(enabled)
        self.notes_edit.setEnabled(enabled)
        self.autosave_checkbox.setEnabled(enabled)
        self.filename_edit.setEnabled(enabled)

    def set_connected(self, connected: bool) -> None:
        """Update status based on connection state."""
        if self.start_btn.text() != "Abort":
            if connected:
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.start_btn.setEnabled(True)
            else:
                self.status_label.setText("Not Connected")
                self.status_label.setStyleSheet("color: red; font-weight: bold;")
                self.start_btn.setEnabled(True)  # Allow auto-connect

    def update_test_progress(self, elapsed_seconds: float, capacity_mah: float, voltage: float = 0.0, energy_wh: float = 0.0, current_a: float = 0.0) -> None:
        """Update progress and summary during test."""
        if self.start_btn.text() != "Abort":
            return

        # Always show "Running" while test is active (clears countdown text)
        self.status_label.setText("Running")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        h = int(elapsed_seconds) // 3600
        m = (int(elapsed_seconds) % 3600) // 60
        s = int(elapsed_seconds) % 60
        self.elapsed_label.setText(f"{h}h {m}m {s}s")

        # Track voltage and current readings for averages
        if voltage > 0:
            if not hasattr(self, '_voltage_readings'):
                self._voltage_readings = []
            self._voltage_readings.append(voltage)
        if current_a > 0:
            if not hasattr(self, '_current_readings'):
                self._current_readings = []
            self._current_readings.append(current_a)

        self._update_test_summary(elapsed_seconds, capacity_mah, energy_wh)

        # Progress based on time or capacity
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

        rated_capacity = self.rated_capacity_spin.value()
        if rated_capacity > 0 and capacity_mah > 0:
            # Estimate based on typical 85% efficiency
            expected_output = rated_capacity * 0.85
            progress = min(100, int(100 * capacity_mah / expected_output))
            self.progress_bar.setValue(progress)
            self.progress_bar.setFormat(f"{progress}% ({capacity_mah:.0f} / ~{expected_output:.0f} mAh)")

            if elapsed_seconds > 10:
                discharge_rate = capacity_mah / elapsed_seconds
                if discharge_rate > 0:
                    remaining_mah = expected_output - capacity_mah
                    remaining_secs = remaining_mah / discharge_rate
                    if remaining_secs > 0:
                        mins, secs = divmod(int(remaining_secs), 60)
                        hours, mins = divmod(mins, 60)
                        self.remaining_label.setText(f"~{hours}h {mins}m {secs}s remaining")
                        return

        self.remaining_label.setText("")

    def _update_test_summary(self, elapsed_seconds: float, capacity_mah: float, energy_wh: float) -> None:
        """Update test summary with output capacity, efficiency, and averages."""
        # Output capacity with auto-scaling
        if capacity_mah >= 1000:
            self.summary_capacity_item.setText(f"{capacity_mah/1000:.3f} Ah")
        else:
            self.summary_capacity_item.setText(f"{capacity_mah:.1f} mAh")

        # Output energy
        self.summary_energy_item.setText(f"{energy_wh:.2f} Wh")

        # Average voltage and current
        voltage_readings = getattr(self, '_voltage_readings', [])
        current_readings = getattr(self, '_current_readings', [])
        if voltage_readings:
            avg_v = sum(voltage_readings) / len(voltage_readings)
            self.summary_avg_voltage_item.setText(f"{avg_v:.3f} V")
        if current_readings:
            avg_i = sum(current_readings) / len(current_readings)
            self.summary_avg_current_item.setText(f"{avg_i:.3f} A")

        # Calculate efficiency (output vs rated)
        rated_capacity = self.rated_capacity_spin.value()
        rated_energy = self.rated_energy_spin.value()

        if rated_capacity > 0 and capacity_mah > 0:
            efficiency = (capacity_mah / rated_capacity) * 100
            self.summary_efficiency_capacity_item.setText(f"{efficiency:.1f}%")
        else:
            self.summary_efficiency_capacity_item.setText("--")

        if rated_energy > 0 and energy_wh > 0:
            efficiency = (energy_wh / rated_energy) * 100
            self.summary_efficiency_energy_item.setText(f"{efficiency:.1f}%")
        else:
            self.summary_efficiency_energy_item.setText("--")

        # Avg V % vs Set Voltage
        set_voltage = self.ps_voltage_spin.value()
        if voltage_readings and set_voltage > 0:
            avg_v = sum(voltage_readings) / len(voltage_readings)
            pct = (avg_v / set_voltage) * 100
            self.summary_avg_voltage_pct_item.setText(f"{pct:.1f}%")
        else:
            self.summary_avg_voltage_pct_item.setText("--")

        # Avg I % vs set current (only meaningful for CC mode)
        if current_readings and self.type_combo.currentIndex() == 0:
            set_current = self.value_spin.value()
            if set_current > 0:
                avg_i = sum(current_readings) / len(current_readings)
                pct = (avg_i / set_current) * 100
                self.summary_avg_current_pct_item.setText(f"{pct:.1f}%")
            else:
                self.summary_avg_current_pct_item.setText("--")
        else:
            self.summary_avg_current_pct_item.setText("--")

    def _update_summary_from_readings(self, readings: list) -> None:
        """Update test summary from loaded readings."""
        if not readings:
            return

        # Get final capacity and energy
        final_capacity = readings[-1].get("capacity_mah", 0)
        final_energy = readings[-1].get("energy_wh", 0)

        # Update output values
        if final_capacity >= 1000:
            self.summary_capacity_item.setText(f"{final_capacity/1000:.3f} Ah")
        else:
            self.summary_capacity_item.setText(f"{final_capacity:.1f} mAh")

        self.summary_energy_item.setText(f"{final_energy:.2f} Wh")

        # Compute average voltage and current from readings
        voltages = [r.get("voltage_v", 0) for r in readings if r.get("voltage_v", 0) > 0]
        currents = [r.get("current_a", 0) for r in readings if r.get("current_a", 0) > 0]
        if voltages:
            avg_v = sum(voltages) / len(voltages)
            self.summary_avg_voltage_item.setText(f"{avg_v:.3f} V")
        if currents:
            avg_i = sum(currents) / len(currents)
            self.summary_avg_current_item.setText(f"{avg_i:.3f} A")

        # Calculate efficiency
        rated_capacity = self.rated_capacity_spin.value()
        rated_energy = self.rated_energy_spin.value()

        if rated_capacity > 0:
            efficiency = (final_capacity / rated_capacity) * 100
            self.summary_efficiency_capacity_item.setText(f"{efficiency:.1f}%")

        if rated_energy > 0:
            efficiency = (final_energy / rated_energy) * 100
            self.summary_efficiency_energy_item.setText(f"{efficiency:.1f}%")

        # Avg V % vs Set Voltage
        set_voltage = self.ps_voltage_spin.value()
        if voltages and set_voltage > 0:
            avg_v = sum(voltages) / len(voltages)
            pct = (avg_v / set_voltage) * 100
            self.summary_avg_voltage_pct_item.setText(f"{pct:.1f}%")

        # Avg I % vs set current (only meaningful for CC mode)
        if currents and self.type_combo.currentIndex() == 0:
            set_current = self.value_spin.value()
            if set_current > 0:
                avg_i = sum(currents) / len(currents)
                pct = (avg_i / set_current) * 100
                self.summary_avg_current_pct_item.setText(f"{pct:.1f}%")

    # Preset methods

    def _load_power_bank_presets_list(self) -> None:
        """Load the list of power bank presets."""
        self.presets_combo.clear()
        self.presets_combo.addItem("")

        if self._default_power_bank_presets:
            self.presets_combo.addItem("--- Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._default_power_bank_presets.keys()):
                self.presets_combo.addItem(preset_name)

        user_presets = sorted(self._power_bank_presets_dir.glob("*.json"))
        if user_presets:
            self.presets_combo.insertSeparator(self.presets_combo.count())
            self.presets_combo.addItem("--- User Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_file in user_presets:
                self.presets_combo.addItem(preset_file.stem)

    def _is_default_power_bank_preset(self, name: str) -> bool:
        """Check if preset is default."""
        return name in self._default_power_bank_presets

    @Slot(int)
    def _on_preset_selected(self, index: int) -> None:
        """Handle power bank preset selection."""
        preset_name = self.presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            self.delete_preset_btn.setEnabled(False)
            return

        is_default = self._is_default_power_bank_preset(preset_name)
        self.delete_preset_btn.setEnabled(not is_default)

        if is_default:
            data = self._default_power_bank_presets[preset_name]
        else:
            preset_file = self._power_bank_presets_dir / f"{preset_name}.json"
            if not preset_file.exists():
                return
            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        # Apply preset
        self.power_bank_name_edit.setText(data.get("name", ""))
        self.manufacturer_edit.setText(data.get("manufacturer", ""))
        self.model_edit.setText(data.get("model", ""))
        self.serial_number_edit.setText(data.get("serial_number", ""))
        self.rated_capacity_spin.setValue(data.get("rated_capacity_mah", 20000))
        self.rated_energy_spin.setValue(data.get("rated_energy_wh", 74.0))
        self.max_output_power_spin.setValue(data.get("max_output_power_w", 30.0))
        self.rated_voltage_spin.setValue(data.get("rated_voltage_v", 5.0))
        self.rated_current_spin.setValue(data.get("rated_current_a", 3.0))
        self.pd_checkbox.setChecked(data.get("pd", False))
        self.notes_edit.setPlainText(data.get("notes", ""))

    @Slot()
    def _save_power_bank_preset(self) -> None:
        """Save current power bank info as preset."""
        manufacturer = self.manufacturer_edit.text().strip()
        name = self.power_bank_name_edit.text().strip()
        if manufacturer and name:
            default_name = f"{manufacturer} {name}"
        elif manufacturer:
            default_name = manufacturer
        elif name:
            default_name = name
        else:
            default_name = "New Preset"

        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:",
            text=default_name
        )
        if not ok or not name:
            return

        safe_name = "".join(c for c in name if c.isalnum() or c in " -_.").strip()
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid preset name.")
            return

        data = {
            "name": self.power_bank_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "model": self.model_edit.text(),
            "serial_number": self.serial_number_edit.text(),
            "rated_capacity_mah": self.rated_capacity_spin.value(),
            "rated_energy_wh": self.rated_energy_spin.value(),
            "max_output_power_w": self.max_output_power_spin.value(),
            "rated_voltage_v": self.rated_voltage_spin.value(),
            "rated_current_a": self.rated_current_spin.value(),
            "pd": self.pd_checkbox.isChecked(),
            "notes": self.notes_edit.toPlainText(),
        }

        preset_file = self._power_bank_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_power_bank_presets_list()
            index = self.presets_combo.findText(safe_name)
            if index >= 0:
                self.presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    @Slot()
    def _delete_power_bank_preset(self) -> None:
        """Delete the selected preset."""
        preset_name = self.presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            QMessageBox.information(self, "No Selection", "Please select a preset to delete.")
            return

        if self._is_default_power_bank_preset(preset_name):
            QMessageBox.warning(
                self, "Cannot Delete",
                "Default presets cannot be deleted."
            )
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            preset_file = self._power_bank_presets_dir / f"{preset_name}.json"
            try:
                preset_file.unlink()
                self._load_power_bank_presets_list()
            except Exception as e:
                QMessageBox.warning(self, "Delete Error", f"Failed to delete: {e}")

    # Test preset methods

    def _load_test_presets_list(self) -> None:
        """Load test presets."""
        self.test_presets_combo.clear()
        self.test_presets_combo.addItem("")

        if self._default_test_presets:
            self.test_presets_combo.addItem("--- Presets ---")
            model = self.test_presets_combo.model()
            item = model.item(self.test_presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_name in sorted(self._default_test_presets.keys()):
                self.test_presets_combo.addItem(preset_name)

        user_presets = sorted(self._test_presets_dir.glob("*.json"))
        if user_presets:
            self.test_presets_combo.insertSeparator(self.test_presets_combo.count())
            self.test_presets_combo.addItem("--- User Presets ---")
            model = self.test_presets_combo.model()
            item = model.item(self.test_presets_combo.count() - 1)
            item.setEnabled(False)

            for preset_file in user_presets:
                self.test_presets_combo.addItem(preset_file.stem)

    def _is_default_test_preset(self, name: str) -> bool:
        """Check if test preset is default."""
        return name in self._default_test_presets

    @Slot(int)
    def _on_test_preset_selected(self, index: int) -> None:
        """Handle test preset selection."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            self.delete_test_preset_btn.setEnabled(False)
            return

        is_default = self._is_default_test_preset(preset_name)
        self.delete_test_preset_btn.setEnabled(not is_default)

        if is_default:
            data = self._default_test_presets[preset_name]
        else:
            preset_file = self._test_presets_dir / f"{preset_name}.json"
            if not preset_file.exists():
                return
            try:
                with open(preset_file, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        # Apply test preset
        if "load_type_index" in data:
            self.type_combo.setCurrentIndex(data["load_type_index"])
        if "value" in data:
            self.value_spin.setValue(data["value"])
        elif "current" in data:
            self.value_spin.setValue(data["current"])
        if "voltage_cutoff" in data:
            self.cutoff_spin.setValue(data["voltage_cutoff"])
        if "timed" in data:
            self.timed_checkbox.setChecked(data["timed"])
        if "duration" in data:
            self.duration_spin.setValue(data["duration"])
            self._sync_hours_minutes()

    @Slot()
    def _save_test_preset(self) -> None:
        """Save test configuration as preset."""
        load_type = self.type_combo.currentText()
        value = self.value_spin.value()
        units = {"Current": "A", "Resistance": "\u03a9", "Power": "W"}
        default_name = f"{load_type} {value}{units.get(load_type, '')}"

        name, ok = QInputDialog.getText(
            self, "Save Test Preset", "Preset name:",
            text=default_name
        )
        if not ok or not name:
            return

        safe_name = "".join(c for c in name if c.isalnum() or c in " -_.").strip()
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid preset name.")
            return

        data = {
            "load_type_index": self.type_combo.currentIndex(),
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
            index = self.test_presets_combo.findText(safe_name)
            if index >= 0:
                self.test_presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save: {e}")

    @Slot()
    def _delete_test_preset(self) -> None:
        """Delete test preset."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            QMessageBox.information(self, "No Selection", "Please select a preset to delete.")
            return

        if self._is_default_test_preset(preset_name):
            QMessageBox.warning(
                self, "Cannot Delete",
                "Default presets cannot be deleted."
            )
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            preset_file = self._test_presets_dir / f"{preset_name}.json"
            try:
                preset_file.unlink()
                self._load_test_presets_list()
            except Exception as e:
                QMessageBox.warning(self, "Delete Error", f"Failed to delete: {e}")

    # Export methods

    def get_test_config(self) -> dict:
        """Get test configuration."""
        load_types = ["Current", "Resistance", "Power"]
        load_type_index = self.type_combo.currentIndex()

        return {
            "test_type": "power_bank",
            "load_type": load_types[load_type_index],
            "load_type_index": load_type_index,
            "value": self.value_spin.value(),
            "voltage_cutoff": self.cutoff_spin.value(),
            "timed": self.timed_checkbox.isChecked(),
            "duration_seconds": self.duration_spin.value() if self.timed_checkbox.isChecked() else 0,
            "start_delay": self.start_delay_spin.value(),
        }

    def get_power_bank_info(self) -> dict:
        """Get power bank info."""
        return {
            "name": self.power_bank_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "model": self.model_edit.text(),
            "serial_number": self.serial_number_edit.text(),
            "rated_capacity_mah": self.rated_capacity_spin.value(),
            "rated_energy_wh": self.rated_energy_spin.value(),
            "max_output_power_w": self.max_output_power_spin.value(),
            "rated_voltage_v": self.rated_voltage_spin.value(),
            "rated_current_a": self.rated_current_spin.value(),
            "pd": self.pd_checkbox.isChecked(),
            "notes": self.notes_edit.toPlainText(),
        }

    def generate_test_filename(self) -> str:
        """Generate filename for test data.

        Format: PowerBank_{Manufacturer}_{PowerBankName}_{OutputV}_{CurrentA}_{CutoffV}_{Timestamp}.json
        Example: PowerBank_Anker_10000mAh_5V_2.0A_3.0V-cutoff_20260210_143022.json
        """
        manufacturer = self.manufacturer_edit.text().strip() or "Unknown"
        safe_manufacturer = "".join(c if c.isalnum() or c in "-" else "-" for c in manufacturer).strip("-")

        name = self.power_bank_name_edit.text().strip() or "Unknown"
        # Sanitize power bank name
        safe_name = "".join(c if c.isalnum() or c in "-" else "-" for c in name).strip("-")

        load_type = self.type_combo.currentText()
        value = self.value_spin.value()
        units = {"Current": "A", "Resistance": "ohm", "Power": "W"}
        cutoff = self.cutoff_spin.value()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = [
            "PowerBank",
            safe_manufacturer,
            safe_name,
            f"{value}{units.get(load_type, '')}",
            f"{cutoff}V-cutoff",
            timestamp,
        ]

        return "_".join(parts) + ".json"

    # Session persistence

    def _connect_save_signals(self) -> None:
        """Connect signals for auto-save."""
        self.type_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.value_spin.valueChanged.connect(self._on_settings_changed)
        self.cutoff_spin.valueChanged.connect(self._on_settings_changed)
        self.ps_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.ps_auto_checkbox.toggled.connect(self._on_settings_changed)
        self.timed_checkbox.toggled.connect(self._on_settings_changed)
        self.hours_spin.valueChanged.connect(self._sync_duration)
        self.minutes_spin.valueChanged.connect(self._sync_duration)
        self.hours_spin.valueChanged.connect(self._on_settings_changed)
        self.minutes_spin.valueChanged.connect(self._on_settings_changed)
        self.start_delay_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        self.power_bank_name_edit.textChanged.connect(self._on_settings_changed)
        self.manufacturer_edit.textChanged.connect(self._on_settings_changed)
        self.model_edit.textChanged.connect(self._on_settings_changed)
        self.serial_number_edit.textChanged.connect(self._on_settings_changed)
        self.rated_capacity_spin.valueChanged.connect(self._on_settings_changed)
        self.rated_energy_spin.valueChanged.connect(self._on_settings_changed)
        self.max_output_power_spin.valueChanged.connect(self._on_settings_changed)
        self.rated_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.rated_current_spin.valueChanged.connect(self._on_settings_changed)
        self.pd_checkbox.toggled.connect(self._on_settings_changed)
        self.notes_edit.textChanged.connect(self._on_settings_changed)
        self.presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Filename update for manufacturer field
        self.manufacturer_edit.textChanged.connect(self._on_filename_field_changed)

        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self) -> None:
        """Handle settings change."""
        if not self._loading_settings:
            self._save_last_session()

    def _save_last_session(self) -> None:
        """Save session to file."""
        settings = {
            "test_config": {
                "load_type_index": self.type_combo.currentIndex(),
                "value": self.value_spin.value(),
                "voltage_cutoff": self.cutoff_spin.value(),
                "timed": self.timed_checkbox.isChecked(),
                "duration": self.duration_spin.value(),
                "start_delay": self.start_delay_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "ps_voltage": self.ps_voltage_spin.value(),
            "ps_auto": self.ps_auto_checkbox.isChecked(),
            "power_bank_info": {
                "name": self.power_bank_name_edit.text(),
                "manufacturer": self.manufacturer_edit.text(),
                "model": self.model_edit.text(),
                "serial_number": self.serial_number_edit.text(),
                "rated_capacity_mah": self.rated_capacity_spin.value(),
                "rated_energy_wh": self.rated_energy_spin.value(),
                "max_output_power_w": self.max_output_power_spin.value(),
                "rated_voltage_v": self.rated_voltage_spin.value(),
                "rated_current_a": self.rated_current_spin.value(),
                "pd": self.pd_checkbox.isChecked(),
                "notes": self.notes_edit.toPlainText(),
                "preset": self.presets_combo.currentText(),
            },
            "autosave": self.autosave_checkbox.isChecked(),
        }

        try:
            self._last_session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._last_session_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"ERROR saving power bank session: {e}")

    def _load_last_session(self) -> None:
        """Load session from file."""
        if not self._last_session_file.exists():
            return

        try:
            with open(self._last_session_file, 'r') as f:
                settings = json.load(f)
        except Exception:
            return

        self._loading_settings = True

        try:
            test_config = settings.get("test_config", {})
            if "load_type_index" in test_config:
                self.type_combo.setCurrentIndex(test_config["load_type_index"])
            if "value" in test_config:
                self.value_spin.setValue(test_config["value"])
            elif "current" in test_config:
                self.value_spin.setValue(test_config["current"])
            if "voltage_cutoff" in test_config:
                self.cutoff_spin.setValue(test_config["voltage_cutoff"])
            if "timed" in test_config:
                self.timed_checkbox.setChecked(test_config["timed"])
            if "duration" in test_config:
                self.duration_spin.setValue(test_config["duration"])
                self._sync_hours_minutes()
            if "start_delay" in test_config:
                self.start_delay_spin.setValue(test_config["start_delay"])
            if "preset" in test_config and test_config["preset"]:
                index = self.test_presets_combo.findText(test_config["preset"])
                if index >= 0:
                    self.test_presets_combo.blockSignals(True)
                    self.test_presets_combo.setCurrentIndex(index)
                    self.test_presets_combo.blockSignals(False)

            # Power Supply Setting
            if "ps_voltage" in settings:
                self.ps_voltage_spin.setValue(settings["ps_voltage"])
            if "ps_auto" in settings:
                self.ps_auto_checkbox.setChecked(settings["ps_auto"])

            power_bank_info = settings.get("power_bank_info", {})
            if "name" in power_bank_info:
                self.power_bank_name_edit.setText(power_bank_info["name"])
            if "manufacturer" in power_bank_info:
                self.manufacturer_edit.setText(power_bank_info["manufacturer"])
            if "model" in power_bank_info:
                self.model_edit.setText(power_bank_info["model"])
            if "serial_number" in power_bank_info:
                self.serial_number_edit.setText(power_bank_info["serial_number"])
            if "rated_capacity_mah" in power_bank_info:
                self.rated_capacity_spin.setValue(power_bank_info["rated_capacity_mah"])
            if "rated_energy_wh" in power_bank_info:
                self.rated_energy_spin.setValue(power_bank_info["rated_energy_wh"])
            if "max_output_power_w" in power_bank_info:
                self.max_output_power_spin.setValue(power_bank_info["max_output_power_w"])
            if "rated_voltage_v" in power_bank_info:
                self.rated_voltage_spin.setValue(power_bank_info["rated_voltage_v"])
            if "rated_current_a" in power_bank_info:
                self.rated_current_spin.setValue(power_bank_info["rated_current_a"])
            if "pd" in power_bank_info:
                self.pd_checkbox.setChecked(power_bank_info["pd"])
            if "notes" in power_bank_info:
                self.notes_edit.setPlainText(power_bank_info["notes"])
            if "preset" in power_bank_info and power_bank_info["preset"]:
                index = self.presets_combo.findText(power_bank_info["preset"])
                if index >= 0:
                    self.presets_combo.blockSignals(True)
                    self.presets_combo.setCurrentIndex(index)
                    self.presets_combo.blockSignals(False)

            if "autosave" in settings:
                self.autosave_checkbox.setChecked(settings["autosave"])

        finally:
            self._loading_settings = False
            self._update_filename()
