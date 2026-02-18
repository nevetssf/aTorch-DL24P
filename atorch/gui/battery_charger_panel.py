"""Battery Charger test panel for CC-CV characteristic testing."""

import json
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QProgressBar, QCheckBox, QLineEdit, QTextEdit
)
from PySide6.QtCore import Signal, Slot, QTimer, Qt


# Chemistry voltage ranges (per cell unless noted)
CHEMISTRY_RANGES = {
    "Li-Ion (1S)": (2.5, 4.2),
    "Li-Ion (2S)": (5.0, 8.4),
    "NiMH": (0.9, 1.5),
    "NiCd": (0.9, 1.5),
    "LiFePO4": (2.5, 3.65),
    "Lead Acid": (1.75, 2.4),
}


class BatteryChargerPanel(QWidget):
    """Panel for battery charger testing using CV mode to simulate battery voltage levels."""

    # Signals
    manual_save_requested = Signal(str)  # filename
    session_loaded = Signal(list)  # readings
    export_csv_requested = Signal()
    test_initialized = Signal()  # Emitted when user clicks Start (before settle phase)
    test_started = Signal()  # Emitted when logging starts (after settle phase)
    test_stopped = Signal()  # Emitted when logging stops (after dwell phase or test complete)

    def __init__(self):
        super().__init__()

        # Load default charger presets from resources
        self._default_charger_presets = self._load_presets_file("battery_charger/presets_chargers.json")

        # Load default test presets
        self._default_test_presets = self._load_presets_file("battery_charger/presets_test.json")

        # User presets directory
        from ..config import get_data_dir
        self._atorch_dir = get_data_dir()
        self._charger_presets_dir = self._atorch_dir / "presets" / "battery_charger_presets"
        self._test_presets_dir = self._atorch_dir / "presets" / "battery_charger_test_presets"
        self._session_file = self._atorch_dir / "sessions" / "battery_charger_session.json"

        # Flag to prevent saving during load
        self._loading_settings = False

        # Test state
        self._test_running = False
        self._test_timer = QTimer()
        self._test_timer.timeout.connect(self._run_test_step)
        self._voltage_steps = []
        self._current_step = 0
        self._total_steps = 0
        self._current_value = 0.0
        self._test_start_time = 0
        self._device = None
        self._plot_panel = None
        self._in_settle_phase = False  # Track if we're in settle or dwell phase
        self._settle_start_time = 0
        self._dwell_start_time = 0

        # Confirmation state (for waiting for user to confirm on tester)
        self._waiting_for_confirmation = False
        self._confirmation_start_time = 0
        self._confirmation_timer = QTimer()
        self._confirmation_timer.timeout.connect(self._check_confirmation)
        self._confirmation_dialog = None  # Non-blocking dialog shown during confirmation
        self._last_device_status = None  # Store last device status for load checking

        self._create_ui()
        self._load_charger_presets_list()
        self._load_test_presets_list()
        self._connect_signals()
        self._connect_save_signals()
        self._load_session()
        self._update_filename()  # Initialize filename after loading settings

    def _create_ui(self):
        """Create the battery charger panel UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Left: Test Conditions
        conditions_group = QGroupBox("Test Conditions")
        conditions_group.setFixedWidth(350)
        conditions_layout = QVBoxLayout(conditions_group)

        # Test presets row
        test_presets_layout = QHBoxLayout()
        test_presets_layout.addWidget(QLabel("Presets"))
        self.test_presets_combo = QComboBox()
        self.test_presets_combo.setToolTip("Load saved test configuration presets")
        test_presets_layout.addWidget(self.test_presets_combo, 1)
        self.save_test_preset_btn = QPushButton("Save")
        self.save_test_preset_btn.setMaximumWidth(50)
        self.save_test_preset_btn.setToolTip("Save current test configuration as preset")
        test_presets_layout.addWidget(self.save_test_preset_btn)
        self.delete_test_preset_btn = QPushButton("Delete")
        self.delete_test_preset_btn.setMaximumWidth(50)
        self.delete_test_preset_btn.setEnabled(False)
        self.delete_test_preset_btn.setToolTip("Delete selected test preset")
        test_presets_layout.addWidget(self.delete_test_preset_btn)
        conditions_layout.addLayout(test_presets_layout)

        # Stage 1 group - Start, End, Steps on one line
        stage1_group = QGroupBox("Stage 1")
        stage1_layout = QHBoxLayout(stage1_group)
        stage1_layout.setContentsMargins(6, 6, 6, 6)

        # Start voltage
        stage1_layout.addWidget(QLabel("Start"))
        self.min_voltage_spin = QDoubleSpinBox()
        self.min_voltage_spin.setRange(0.0, 60.0)
        self.min_voltage_spin.setDecimals(2)
        self.min_voltage_spin.setSingleStep(0.1)
        self.min_voltage_spin.setValue(2.5)
        self.min_voltage_spin.setSuffix(" V")
        self.min_voltage_spin.setMaximumWidth(90)
        stage1_layout.addWidget(self.min_voltage_spin)

        # End voltage
        stage1_layout.addWidget(QLabel("End"))
        self.max_voltage_spin = QDoubleSpinBox()
        self.max_voltage_spin.setRange(0.0, 60.0)
        self.max_voltage_spin.setDecimals(2)
        self.max_voltage_spin.setSingleStep(0.1)
        self.max_voltage_spin.setValue(4.2)
        self.max_voltage_spin.setSuffix(" V")
        self.max_voltage_spin.setMaximumWidth(90)
        stage1_layout.addWidget(self.max_voltage_spin)

        # Number of steps
        stage1_layout.addWidget(QLabel("Steps"))
        self.num_steps_spin = QSpinBox()
        self.num_steps_spin.setRange(1, 999)
        self.num_steps_spin.setValue(10)
        self.num_steps_spin.setMaximumWidth(70)
        stage1_layout.addWidget(self.num_steps_spin)

        # Constrain Stage 1 End > Start
        self.min_voltage_spin.valueChanged.connect(
            lambda v: self.max_voltage_spin.setMinimum(v + 0.01)
        )

        conditions_layout.addWidget(stage1_group)

        # Stage 2 group - Start (read-only, linked to Stage 1 End), End, Steps
        self.stage2_group = QGroupBox("Stage 2")
        self.stage2_group.setCheckable(True)
        self.stage2_group.setChecked(False)
        stage2_layout = QHBoxLayout(self.stage2_group)
        stage2_layout.setContentsMargins(6, 6, 6, 6)

        # Start voltage (read-only, mirrors Stage 1 End)
        stage2_layout.addWidget(QLabel("Start"))
        self.stage2_start_label = QLineEdit()
        self.stage2_start_label.setReadOnly(True)
        self.stage2_start_label.setText(f"{self.max_voltage_spin.value():.2f} V")
        self.stage2_start_label.setMaximumWidth(90)
        self.stage2_start_label.setStyleSheet("background-color: palette(window);")
        stage2_layout.addWidget(self.stage2_start_label)

        # End voltage
        stage2_layout.addWidget(QLabel("End"))
        self.stage2_end_spin = QDoubleSpinBox()
        self.stage2_end_spin.setRange(0.0, 60.0)
        self.stage2_end_spin.setDecimals(2)
        self.stage2_end_spin.setSingleStep(0.1)
        self.stage2_end_spin.setValue(5.0)
        self.stage2_end_spin.setSuffix(" V")
        self.stage2_end_spin.setMaximumWidth(90)
        stage2_layout.addWidget(self.stage2_end_spin)

        # Number of steps
        stage2_layout.addWidget(QLabel("Steps"))
        self.stage2_steps_spin = QSpinBox()
        self.stage2_steps_spin.setRange(1, 999)
        self.stage2_steps_spin.setValue(10)
        self.stage2_steps_spin.setMaximumWidth(70)
        stage2_layout.addWidget(self.stage2_steps_spin)

        # Update Stage 2 Start when Stage 1 End changes, and constrain Stage 2 End > Start
        self.max_voltage_spin.valueChanged.connect(
            lambda v: self.stage2_start_label.setText(f"{v:.2f} V")
        )
        self.max_voltage_spin.valueChanged.connect(
            lambda v: self.stage2_end_spin.setMinimum(v + 0.01)
        )

        conditions_layout.addWidget(self.stage2_group)

        # Stage 3 group - Start (read-only, linked to Stage 2 End), End, Steps
        self.stage3_group = QGroupBox("Stage 3")
        self.stage3_group.setCheckable(True)
        self.stage3_group.setChecked(False)
        stage3_layout = QHBoxLayout(self.stage3_group)
        stage3_layout.setContentsMargins(6, 6, 6, 6)

        # Start voltage (read-only, mirrors Stage 2 End)
        stage3_layout.addWidget(QLabel("Start"))
        self.stage3_start_label = QLineEdit()
        self.stage3_start_label.setReadOnly(True)
        self.stage3_start_label.setText(f"{self.stage2_end_spin.value():.2f} V")
        self.stage3_start_label.setMaximumWidth(90)
        self.stage3_start_label.setStyleSheet("background-color: palette(window);")
        stage3_layout.addWidget(self.stage3_start_label)

        # End voltage
        stage3_layout.addWidget(QLabel("End"))
        self.stage3_end_spin = QDoubleSpinBox()
        self.stage3_end_spin.setRange(0.0, 60.0)
        self.stage3_end_spin.setDecimals(2)
        self.stage3_end_spin.setSingleStep(0.1)
        self.stage3_end_spin.setValue(6.0)
        self.stage3_end_spin.setSuffix(" V")
        self.stage3_end_spin.setMaximumWidth(90)
        stage3_layout.addWidget(self.stage3_end_spin)

        # Number of steps
        stage3_layout.addWidget(QLabel("Steps"))
        self.stage3_steps_spin = QSpinBox()
        self.stage3_steps_spin.setRange(1, 999)
        self.stage3_steps_spin.setValue(10)
        self.stage3_steps_spin.setMaximumWidth(70)
        stage3_layout.addWidget(self.stage3_steps_spin)

        # Update Stage 3 Start when Stage 2 End changes, and constrain Stage 3 End > Start
        self.stage2_end_spin.valueChanged.connect(
            lambda v: self.stage3_start_label.setText(f"{v:.2f} V")
        )
        self.stage2_end_spin.valueChanged.connect(
            lambda v: self.stage3_end_spin.setMinimum(v + 0.01)
        )

        # Stage 3 is only available when Stage 2 is checked
        self.stage3_group.setEnabled(False)
        self.stage2_group.toggled.connect(self._on_stage2_toggled)

        conditions_layout.addWidget(self.stage3_group)

        # Timing group - Settle and Dwell on one line
        timing_group = QGroupBox("Timing")
        timing_layout = QHBoxLayout(timing_group)
        timing_layout.setContentsMargins(6, 6, 6, 6)

        # Settle time
        timing_layout.addWidget(QLabel("Settle"))
        self.settle_time_spin = QSpinBox()
        self.settle_time_spin.setRange(0, 3600)
        self.settle_time_spin.setValue(2)
        self.settle_time_spin.setSuffix(" s")
        self.settle_time_spin.setMaximumWidth(80)
        timing_layout.addWidget(self.settle_time_spin)

        # Dwell time
        timing_layout.addWidget(QLabel("Dwell"))
        self.dwell_time_spin = QSpinBox()
        self.dwell_time_spin.setRange(0, 3600)
        self.dwell_time_spin.setValue(5)
        self.dwell_time_spin.setSuffix(" s")
        self.dwell_time_spin.setMaximumWidth(80)
        timing_layout.addWidget(self.dwell_time_spin)

        conditions_layout.addWidget(timing_group)
        conditions_layout.addStretch()

        layout.addWidget(conditions_group)

        # Middle: Battery Charger Info
        charger_info_group = QGroupBox("Battery Charger Info")
        charger_info_group.setFixedWidth(350)
        charger_info_layout = QVBoxLayout(charger_info_group)

        # Charger presets section
        charger_presets_layout = QHBoxLayout()
        charger_presets_layout.addWidget(QLabel("Presets"))
        self.charger_presets_combo = QComboBox()
        charger_presets_layout.addWidget(self.charger_presets_combo, 1)

        self.save_charger_preset_btn = QPushButton("Save")
        self.save_charger_preset_btn.setMaximumWidth(50)
        charger_presets_layout.addWidget(self.save_charger_preset_btn)

        self.delete_charger_preset_btn = QPushButton("Delete")
        self.delete_charger_preset_btn.setMaximumWidth(50)
        self.delete_charger_preset_btn.setEnabled(False)
        charger_presets_layout.addWidget(self.delete_charger_preset_btn)
        charger_info_layout.addLayout(charger_presets_layout)

        # Charger info fields
        charger_form = QGroupBox()
        charger_form_layout = QFormLayout(charger_form)
        charger_form_layout.setContentsMargins(6, 6, 6, 6)

        self.charger_name_edit = QLineEdit()
        self.charger_name_edit.setPlaceholderText("e.g., Anker PowerPort III")
        charger_form_layout.addRow("Name", self.charger_name_edit)

        self.charger_manufacturer_edit = QLineEdit()
        self.charger_manufacturer_edit.setPlaceholderText("e.g., Anker")
        charger_form_layout.addRow("Manufacturer", self.charger_manufacturer_edit)

        # Model and Chemistry on same row
        model_chem_layout = QHBoxLayout()
        self.charger_model_edit = QLineEdit()
        self.charger_model_edit.setPlaceholderText("e.g., A2017")
        model_chem_layout.addWidget(self.charger_model_edit)
        self.charger_chemistry_combo = QComboBox()
        self.charger_chemistry_combo.addItems(list(CHEMISTRY_RANGES.keys()))
        model_chem_layout.addWidget(self.charger_chemistry_combo)
        charger_form_layout.addRow("Model", model_chem_layout)

        # Rated Voltage and Current on same row
        rated_layout = QHBoxLayout()
        rated_layout.addWidget(QLabel("Voltage"))
        self.charger_rated_voltage_spin = QDoubleSpinBox()
        self.charger_rated_voltage_spin.setRange(0.0, 60.0)
        self.charger_rated_voltage_spin.setDecimals(2)
        self.charger_rated_voltage_spin.setValue(0.0)
        self.charger_rated_voltage_spin.setSuffix(" V")
        self.charger_rated_voltage_spin.setMaximumWidth(80)
        rated_layout.addWidget(self.charger_rated_voltage_spin)
        rated_layout.addWidget(QLabel("Current"))
        self.charger_rated_current_spin = QDoubleSpinBox()
        self.charger_rated_current_spin.setRange(0.0, 100.0)
        self.charger_rated_current_spin.setDecimals(2)
        self.charger_rated_current_spin.setValue(0.0)
        self.charger_rated_current_spin.setSuffix(" A")
        self.charger_rated_current_spin.setMaximumWidth(80)
        rated_layout.addWidget(self.charger_rated_current_spin)
        charger_form_layout.addRow(rated_layout)

        charger_info_layout.addWidget(charger_form)

        # Notes panel - entire panel is a text box
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        self.charger_notes_edit = QTextEdit()
        self.charger_notes_edit.setPlaceholderText("Additional notes...")
        notes_layout.addWidget(self.charger_notes_edit)
        charger_info_layout.addWidget(notes_group)
        charger_info_layout.addStretch()

        layout.addWidget(charger_info_group)

        # Right: Test Control
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Abort button
        self.start_btn = QPushButton("Start")
        # Start button always enabled (auto-connect handles connection)
        control_layout.addWidget(self.start_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        control_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Not Connected")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: red;")
        control_layout.addWidget(self.status_label)

        # Time label
        self.time_label = QLabel("0h 0m 0s")
        self.time_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.time_label)

        # Add stretch to push file-related controls to bottom
        control_layout.addStretch()

        # Auto Save section
        autosave_layout = QHBoxLayout()
        self.autosave_checkbox = QCheckBox("Auto Save")
        self.autosave_checkbox.setChecked(True)
        autosave_layout.addWidget(self.autosave_checkbox)
        self.save_btn = QPushButton("Save")
        self.save_btn.setMaximumWidth(50)
        autosave_layout.addWidget(self.save_btn)
        self.load_btn = QPushButton("Load")
        self.load_btn.setMaximumWidth(50)
        autosave_layout.addWidget(self.load_btn)
        self.export_btn = QPushButton("Export")
        self.export_btn.setMaximumWidth(60)
        autosave_layout.addWidget(self.export_btn)
        self.show_folder_btn = QPushButton("Show Folder")
        self.show_folder_btn.setMaximumWidth(80)
        autosave_layout.addWidget(self.show_folder_btn)
        control_layout.addLayout(autosave_layout)

        # Filename text field
        self.filename_edit = QLineEdit()
        self.filename_edit.setReadOnly(True)  # Read-only when Auto Save is checked
        self.filename_edit.setPlaceholderText("Test filename...")
        control_layout.addWidget(self.filename_edit)

        layout.addWidget(control_group, 1)  # Stretch factor 1 to expand and fill available space
        layout.addStretch()

    def _on_stage2_toggled(self, checked: bool):
        """Handle Stage 2 checkbox toggle."""
        if not checked:
            # Disable and uncheck Stage 3 when Stage 2 is unchecked
            self.stage3_group.setChecked(False)
            self.stage3_group.setEnabled(False)
        else:
            # Enable Stage 3 checkbox (but don't auto-check it)
            self.stage3_group.setEnabled(True)

    def _connect_signals(self):
        """Connect charger preset and test preset signals."""
        # Charger preset signals
        self.charger_presets_combo.currentIndexChanged.connect(self._on_charger_preset_selected)
        self.save_charger_preset_btn.clicked.connect(self._save_charger_preset)
        self.delete_charger_preset_btn.clicked.connect(self._delete_charger_preset)

        # Test preset signals
        self.test_presets_combo.currentIndexChanged.connect(self._on_test_preset_selected)
        self.save_test_preset_btn.clicked.connect(self._save_test_preset)
        self.delete_test_preset_btn.clicked.connect(self._delete_test_preset)

        # Test control signals
        self.start_btn.clicked.connect(self._on_start_abort_clicked)
        self.autosave_checkbox.toggled.connect(self._on_autosave_toggled)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.load_btn.clicked.connect(self._on_load_clicked)
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.show_folder_btn.clicked.connect(self._on_show_folder_clicked)

    def _load_presets_file(self, relative_path: str) -> dict:
        """Load a presets file from resources directory."""
        try:
            # Get the project root directory (three levels up from this file)
            module_dir = Path(__file__).parent.parent.parent
            preset_file = module_dir / "resources" / relative_path

            if preset_file.exists():
                with open(preset_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load presets from {relative_path}: {e}")
        return {}

    def _load_charger_presets_list(self):
        """Load charger presets into the combo box."""
        self.charger_presets_combo.clear()
        self.charger_presets_combo.addItem("")  # Empty option

        # Add Default Presets section
        if self._default_charger_presets:
            self.charger_presets_combo.addItem("─── Default Chargers ───")
            self.charger_presets_combo.model().item(self.charger_presets_combo.count() - 1).setEnabled(False)
            for name in sorted(self._default_charger_presets.keys()):
                self.charger_presets_combo.addItem(name)

        # Add User Presets section
        user_presets = []
        if self._charger_presets_dir.exists():
            for preset_file in sorted(self._charger_presets_dir.glob("*.json")):
                user_presets.append(preset_file.stem)

        if user_presets:
            self.charger_presets_combo.addItem("─── My Chargers ───")
            self.charger_presets_combo.model().item(self.charger_presets_combo.count() - 1).setEnabled(False)
            for name in user_presets:
                self.charger_presets_combo.addItem(name)

    def _on_charger_preset_selected(self, index: int):
        """Handle charger preset selection."""
        # Skip if we're loading settings from session file
        if self._loading_settings:
            return

        preset_name = self.charger_presets_combo.currentText()

        # Check if it's a separator
        if "───" in preset_name or not preset_name:
            self.delete_charger_preset_btn.setEnabled(False)
            return

        # Check if it's a user preset (enable delete button)
        preset_file = self._charger_presets_dir / f"{preset_name}.json"
        self.delete_charger_preset_btn.setEnabled(preset_file.exists())

        # Load preset data
        preset_data = None
        if preset_name in self._default_charger_presets:
            preset_data = self._default_charger_presets[preset_name]
        elif preset_file.exists():
            try:
                with open(preset_file, 'r') as f:
                    preset_data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        if preset_data:
            self._set_charger_info(preset_data)

    def _set_charger_info(self, data: dict):
        """Set charger info fields from dictionary."""
        self._loading_settings = True
        try:
            self.charger_name_edit.setText(data.get("name", ""))
            self.charger_manufacturer_edit.setText(data.get("manufacturer", ""))
            self.charger_model_edit.setText(data.get("model", ""))
            if "chemistry" in data:
                self.charger_chemistry_combo.setCurrentText(data["chemistry"])
            self.charger_rated_current_spin.setValue(data.get("rated_current", data.get("rated_output_current_a", 0.0)))
            self.charger_rated_voltage_spin.setValue(data.get("rated_voltage", data.get("rated_voltage_v", 0.0)))
            self.charger_notes_edit.setPlainText(data.get("notes", ""))
        finally:
            self._loading_settings = False

    def _get_charger_info(self) -> dict:
        """Get charger info fields as dictionary."""
        return {
            "name": self.charger_name_edit.text().strip(),
            "manufacturer": self.charger_manufacturer_edit.text().strip(),
            "model": self.charger_model_edit.text().strip(),
            "chemistry": self.charger_chemistry_combo.currentText(),
            "rated_current": self.charger_rated_current_spin.value(),
            "rated_voltage": self.charger_rated_voltage_spin.value(),
            "notes": self.charger_notes_edit.toPlainText().strip(),
        }

    def _save_charger_preset(self):
        """Save current charger info as a preset."""
        from PySide6.QtWidgets import QInputDialog

        name = self.charger_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Preset", "Please enter a charger name first.")
            return

        # Ask for preset name (default to charger name)
        preset_name, ok = QInputDialog.getText(
            self, "Save Charger Preset",
            "Preset name:", text=name
        )

        if not ok or not preset_name:
            return

        # Save preset
        data = self._get_charger_info()
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in (' ', '-', '_')).strip()

        preset_file = self._charger_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_charger_presets_list()
            # Select the newly saved preset
            index = self.charger_presets_combo.findText(safe_name)
            if index >= 0:
                self.charger_presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    def _delete_charger_preset(self):
        """Delete the selected user charger preset."""
        preset_name = self.charger_presets_combo.currentText()
        if not preset_name or "───" in preset_name:
            return

        preset_file = self._charger_presets_dir / f"{preset_name}.json"
        if not preset_file.exists():
            QMessageBox.warning(self, "Delete Preset", "Cannot delete built-in presets.")
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete charger preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                preset_file.unlink()
                self._load_charger_presets_list()
            except Exception as e:
                QMessageBox.warning(self, "Delete Error", f"Failed to delete preset: {e}")

    def _load_test_presets_list(self):
        """Load test presets into the combo box."""
        self.test_presets_combo.clear()
        self.test_presets_combo.addItem("")  # Empty option

        # Add default presets section
        if self._default_test_presets:
            self.test_presets_combo.addItem("--- Presets ---")
            model = self.test_presets_combo.model()
            item = model.item(self.test_presets_combo.count() - 1)
            item.setEnabled(False)

            for name in sorted(self._default_test_presets.keys()):
                self.test_presets_combo.addItem(name)

        # Add user presets section
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
        """Check if a test preset name is a default (read-only) preset."""
        return name in self._default_test_presets

    @Slot(int)
    def _on_test_preset_selected(self, index: int):
        """Handle test preset selection from combo box."""
        if self._loading_settings:
            return

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

        # Apply preset data to all test condition fields
        self._loading_settings = True
        try:
            if "stage1_start" in data:
                self.min_voltage_spin.setValue(data["stage1_start"])
            if "stage1_end" in data:
                self.max_voltage_spin.setValue(data["stage1_end"])
            if "stage1_steps" in data:
                self.num_steps_spin.setValue(data["stage1_steps"])
            if "stage2_enabled" in data:
                self.stage2_group.setChecked(data["stage2_enabled"])
            if "stage2_end" in data:
                self.stage2_end_spin.setValue(data["stage2_end"])
            if "stage2_steps" in data:
                self.stage2_steps_spin.setValue(data["stage2_steps"])
            if "stage3_enabled" in data:
                self.stage3_group.setChecked(data["stage3_enabled"])
            if "stage3_end" in data:
                self.stage3_end_spin.setValue(data["stage3_end"])
            if "stage3_steps" in data:
                self.stage3_steps_spin.setValue(data["stage3_steps"])
            if "settle_time" in data:
                self.settle_time_spin.setValue(data["settle_time"])
            if "dwell_time" in data:
                self.dwell_time_spin.setValue(data["dwell_time"])
        finally:
            self._loading_settings = False
            self._save_session()

    @Slot()
    def _save_test_preset(self):
        """Save current test configuration as a preset."""
        from PySide6.QtWidgets import QInputDialog

        # Build default name from current settings
        start = self.min_voltage_spin.value()
        end = self.max_voltage_spin.value()
        steps = self.num_steps_spin.value()
        default_name = f"{start}-{end}V {steps} steps"

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
            "load_type": "voltage",
            "stage1_start": self.min_voltage_spin.value(),
            "stage1_end": self.max_voltage_spin.value(),
            "stage1_steps": self.num_steps_spin.value(),
            "stage2_enabled": self.stage2_group.isChecked(),
            "stage2_end": self.stage2_end_spin.value(),
            "stage2_steps": self.stage2_steps_spin.value(),
            "stage3_enabled": self.stage3_group.isChecked(),
            "stage3_end": self.stage3_end_spin.value(),
            "stage3_steps": self.stage3_steps_spin.value(),
            "settle_time": self.settle_time_spin.value(),
            "dwell_time": self.dwell_time_spin.value(),
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
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    @Slot()
    def _delete_test_preset(self):
        """Delete the currently selected test preset."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or preset_name.startswith("---"):
            return

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

    def set_device_and_plot(self, device, plot_panel):
        """Set the device and plot panel references."""
        self._device = device
        self._plot_panel = plot_panel
        # Update UI based on connection status
        self.set_connected(device is not None)

    def _on_start_abort_clicked(self):
        """Handle Start/Abort button click."""
        if self._test_running:
            self._abort_test(reason="Test Aborted by User")
        else:
            self._start_test()

    def _start_test(self):
        """Start the stepped voltage test."""
        # Check if device is connected, try to auto-connect if not
        if not self._device or not self._device.is_connected:
            # Try to find and connect to main window for auto-connect
            main_window = self.window()
            if hasattr(main_window, '_try_auto_connect'):
                if not main_window._try_auto_connect():
                    # Auto-connect failed
                    QMessageBox.warning(
                        self,
                        "Not Connected",
                        "Please select a device from the dropdown and click Connect before starting the test."
                    )
                    return
                # Auto-connect succeeded, update device reference
                self._device = main_window.device
            else:
                # Can't auto-connect, show warning
                QMessageBox.warning(
                    self,
                    "Not Connected",
                    "Please connect to a device before starting the test."
                )
                return

        # Get test parameters
        min_voltage = self.min_voltage_spin.value()
        max_voltage = self.max_voltage_spin.value()
        num_steps = self.num_steps_spin.value()
        settle_time = self.settle_time_spin.value()
        dwell_time = self.dwell_time_spin.value()

        # Validate parameters
        if min_voltage >= max_voltage:
            QMessageBox.warning(self, "Invalid Parameters", "Min Voltage must be less than Max Voltage.")
            return
        if num_steps < 1:
            QMessageBox.warning(self, "Invalid Parameters", "Steps must be at least 1.")
            return

        # Emit signal that test is being initialized (before any device commands)
        # This tells main_window to clear accumulated data BEFORE the test begins
        self.test_initialized.emit()

        # Build flat list of voltage steps across all enabled stages
        voltage_steps = []

        # Stage 1: num_steps points from min_voltage to max_voltage
        if num_steps == 1:
            voltage_steps.append(min_voltage)
        else:
            step_size = (max_voltage - min_voltage) / (num_steps - 1)
            for i in range(num_steps):
                voltage_steps.append(min_voltage + i * step_size)

        # Stage 2: stage2_steps new points beyond Stage 1 End
        if self.stage2_group.isChecked():
            stage2_start = max_voltage
            stage2_end = self.stage2_end_spin.value()
            stage2_steps = self.stage2_steps_spin.value()
            step_size_2 = (stage2_end - stage2_start) / stage2_steps
            for i in range(1, stage2_steps + 1):
                voltage_steps.append(stage2_start + i * step_size_2)

            # Stage 3: stage3_steps new points beyond Stage 2 End
            if self.stage3_group.isChecked():
                stage3_start = stage2_end
                stage3_end = self.stage3_end_spin.value()
                stage3_steps = self.stage3_steps_spin.value()
                step_size_3 = (stage3_end - stage3_start) / stage3_steps
                for i in range(1, stage3_steps + 1):
                    voltage_steps.append(stage3_start + i * step_size_3)

        self._voltage_steps = voltage_steps
        self._total_steps = len(voltage_steps)
        self._current_step = 0
        self._current_value = voltage_steps[0]

        try:
            # Set CV mode with initial voltage (mode 2 = CV)
            if not self._device.set_mode(2, min_voltage):
                QMessageBox.critical(self, "Device Error", "Failed to set CV mode")
                return

            # Send turn_on command to device
            # Device will wait for user confirmation on tester before actually turning on
            if not self._device.turn_on():
                QMessageBox.critical(self, "Device Error", "Failed to send turn on command")
                return

        except Exception as e:
            QMessageBox.critical(self, "Device Error", f"Failed to configure device: {e}")
            return

        # Switch plot to show Voltage vs Current
        if self._plot_panel:
            self._plot_panel.x_axis_combo.setCurrentText("Voltage")
            # Enable Current on Y-axis
            if "Y" in self._plot_panel._axis_dropdowns:
                self._plot_panel._axis_dropdowns["Y"].setCurrentText("Current")
                self._plot_panel._axis_checkboxes["Y"].setChecked(True)

        # Update UI
        self.start_btn.setText("Abort")
        self.progress_bar.setValue(0)
        self._test_running = True
        self._test_start_time = time.time()

        # Enter "waiting for confirmation" state
        self._waiting_for_confirmation = True
        self._confirmation_start_time = time.time()
        self._logging_enabled = False

        # Show non-blocking dialog to user
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        self._confirmation_dialog = QDialog(self)
        self._confirmation_dialog.setWindowTitle("Confirm Test")
        self._confirmation_dialog.setModal(False)  # Non-blocking
        dialog_layout = QVBoxLayout(self._confirmation_dialog)
        dialog_layout.addWidget(QLabel(
            f"Test configured for {min_voltage:.2f}V in CV mode.\n\n"
            "Please CONFIRM the test on the tester.\n\n"
            "Waiting for confirmation... (10s)"
        ))
        self._confirmation_dialog.setFixedSize(350, 150)
        self._confirmation_dialog.show()  # Non-blocking show

        # Update status
        self.status_label.setText("Waiting for confirmation on tester (10s)")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        # Start confirmation timer (check every 0.5 seconds)
        self._confirmation_timer.start(500)

    def _check_confirmation(self):
        """Check if user has confirmed test on tester (load is on).

        Called every 0.5 seconds during confirmation waiting period.
        If load turns on → start settle phase
        If 10 seconds pass without confirmation → abort test
        """
        if not self._waiting_for_confirmation:
            return

        # Check if device is still connected
        if not self._device or not self._device.is_connected:
            self._confirmation_timer.stop()
            self._waiting_for_confirmation = False
            # Close dialog
            if self._confirmation_dialog:
                self._confirmation_dialog.close()
                self._confirmation_dialog = None
            self.status_label.setText("Connection Lost - Test Aborted")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self._abort_test(reason="Connection Lost")
            return

        elapsed = time.time() - self._confirmation_start_time
        remaining = max(0, 10 - int(elapsed))

        # Update countdown in status
        self.status_label.setText(f"Waiting for confirmation on tester ({remaining}s)")

        # Check if load is on (user confirmed on tester)
        # Check the actual device status from polling
        if self._last_device_status and self._last_device_status.load_on:
            # Load is on! User confirmed. Close dialog and start the settle phase.
            self._confirmation_timer.stop()
            self._waiting_for_confirmation = False
            # Close dialog
            if self._confirmation_dialog:
                self._confirmation_dialog.close()
                self._confirmation_dialog = None
            self._start_settle_phase()
            return

        # Check if timeout (10 seconds elapsed)
        if elapsed >= 10:
            self._confirmation_timer.stop()
            self._waiting_for_confirmation = False
            # Close dialog
            if self._confirmation_dialog:
                self._confirmation_dialog.close()
                self._confirmation_dialog = None
            # Show error in status line
            self.status_label.setText("Test not confirmed on tester - Test Aborted")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self._abort_test(reason="Confirmation Timeout")

    def _start_settle_phase(self):
        """Start the settle phase after user confirms test on tester."""
        settle_time = self.settle_time_spin.value()
        min_voltage = self.min_voltage_spin.value()

        # Enter settle phase for first step
        self._in_settle_phase = True
        self._settle_start_time = time.time()

        # Update UI
        self.status_label.setText(f"Step 1/{self._total_steps}: Settling ({settle_time}s) - {min_voltage:.2f}V")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        # Start timer to check phase transitions (every second)
        self._test_timer.start(1000)

    def _abort_test(self, reason: str = "Test Aborted"):
        """Abort the running test.

        Args:
            reason: Reason for abort (shown in status message)
        """
        self._test_timer.stop()
        self._confirmation_timer.stop()
        self._waiting_for_confirmation = False

        # Close confirmation dialog if open
        if self._confirmation_dialog:
            self._confirmation_dialog.close()
            self._confirmation_dialog = None

        # Turn off load (if device is still connected)
        if self._device and self._device.is_connected:
            try:
                self._device.turn_off()
            except Exception:
                pass  # Ignore errors during abort

        self._finish_test(status=reason)

    def _run_test_step(self):
        """Execute one step of the test - handles settle/dwell phase transitions."""
        # Check if device is still connected
        if not self._device or not self._device.is_connected:
            self._test_timer.stop()
            QMessageBox.critical(
                self,
                "Connection Lost",
                "Device disconnected during test.\n\nThe test has been aborted."
            )
            self._abort_test(reason="Connection Lost")
            return

        settle_time = self.settle_time_spin.value()
        dwell_time = self.dwell_time_spin.value()
        current_time = time.time()

        if self._in_settle_phase:
            # Calculate remaining settle time
            elapsed_settle = current_time - self._settle_start_time
            remaining_settle = max(0, settle_time - elapsed_settle)

            # Check if settle phase is complete
            if remaining_settle <= 0:
                # Settle phase complete - transition to dwell phase and START logging
                self._in_settle_phase = False
                self._dwell_start_time = current_time

                # Start/resume logging now that settle is complete
                self.test_started.emit()  # Tells main_window to start logging
                self._logging_enabled = True

                # Update UI
                self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: Logging... ({self._current_value:.2f}V)")
                self.status_label.setStyleSheet("color: blue; font-weight: bold;")
            else:
                # Update status with countdown
                self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: Settling ({int(remaining_settle)}s) - {self._current_value:.2f}V")
                self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        else:
            # In dwell phase - calculate remaining dwell time
            elapsed_dwell = current_time - self._dwell_start_time
            remaining_dwell = max(0, dwell_time - elapsed_dwell)

            # Check if dwell phase is complete
            if remaining_dwell <= 0:
                # Check if this is the last step
                if self._current_step + 1 >= self._total_steps:
                    # Last step complete - finish test (will stop logging, turn off load, save)
                    self._finish_test()
                    return

                # Not the last step - stop logging and move to next step
                if self._logging_enabled:
                    self.test_stopped.emit()  # Tells main_window to stop logging (but NOT turn off load)
                    self._logging_enabled = False

                # Move to next step
                self._current_step += 1

                # Get next voltage from pre-built list
                self._current_value = self._voltage_steps[self._current_step]

                # Set new voltage and ensure load stays on
                try:
                    self._device.set_voltage(self._current_value)
                    # Ensure load is still on after changing voltage (some devices may turn off)
                    time.sleep(0.1)  # Brief delay to let device process the command
                    if self._device.is_connected:
                        # Turn on load again to ensure it stays connected
                        self._device.turn_on()
                except Exception as e:
                    self.status_label.setText(f"Error: {str(e)}")
                    QMessageBox.critical(self, "Device Error", f"Failed to set voltage: {e}\n\nThe test has been aborted.")
                    self._abort_test(reason=f"Device Error: {str(e)}")
                    return

                # Enter settle phase for next step
                self._in_settle_phase = True
                self._settle_start_time = current_time

                # Update UI
                progress = int((self._current_step / self._total_steps) * 100)
                self.progress_bar.setValue(progress)
                self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: Settling ({int(settle_time)}s) - {self._current_value:.2f}V")
                self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            else:
                # Update status with countdown
                self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: Logging ({int(remaining_dwell)}s) - {self._current_value:.2f}V")
                self.status_label.setStyleSheet("color: blue; font-weight: bold;")

        # Update time display
        self._update_test_time()

    def _update_test_time(self):
        """Update the time label."""
        elapsed = time.time() - self._test_start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        self.time_label.setText(f"{hours}h {minutes}m {seconds}s")

    def _finish_test(self, status: str = "Test Complete"):
        """Clean up when test completes.

        Proper sequence: stop logging → turn off load → save data (via test_stopped signal)
        """
        # Stop the test timer
        self._test_timer.stop()

        # Mark test as not running BEFORE emitting signal
        # (so main_window can detect this is final stop and trigger auto-save)
        self._test_running = False

        # Stop logging if still enabled
        # Emit test_stopped BEFORE turning off load so main_window can save data
        # (main_window checks _logging_enabled to decide whether to save)
        if self._logging_enabled:
            self.test_stopped.emit()  # Triggers auto-save in main_window
            self._logging_enabled = False

        # Turn off load AFTER emitting signal (so logging completes first)
        if self._device:
            try:
                self._device.turn_off()
            except Exception:
                pass

        # Update UI
        self.start_btn.setText("Start")
        self.start_btn.setEnabled(True)  # Re-enable the button

        # Show status message briefly, then revert to normal status
        if not self.status_label.text().startswith("Error") and not self.status_label.text().startswith("Connection Lost"):
            self.status_label.setText(status)
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # After 2 seconds, revert to normal status based on connection state
            QTimer.singleShot(2000, self._restore_normal_status)

        self.progress_bar.setValue(100)
        self._update_test_time()

        # Play completion chime
        self._play_completion_chime()

    def _play_completion_chime(self):
        """Play a sound when test completes."""
        try:
            # Try macOS NSSound for a nice chime
            from AppKit import NSSound
            sound = NSSound.soundNamed_("Glass")  # System chime sound
            if sound:
                sound.play()
                return
        except ImportError:
            pass

        # Fallback to system beep
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
        except Exception:
            pass  # Silent failure if beep not available

    def _restore_normal_status(self):
        """Restore status label to normal state based on connection."""
        if not self._test_running:  # Only restore if test is still not running
            if self._device and self._device.is_connected:
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.status_label.setText("Not Connected")
                self.status_label.setStyleSheet("color: red;")

    def update_device_status(self, status) -> None:
        """Update with latest device status for load checking.

        Args:
            status: DeviceStatus object from device polling
        """
        self._last_device_status = status

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all input widgets during test."""
        self.min_voltage_spin.setEnabled(enabled)
        self.max_voltage_spin.setEnabled(enabled)
        self.num_steps_spin.setEnabled(enabled)
        self.stage2_group.setEnabled(enabled)
        self.stage2_end_spin.setEnabled(enabled)
        self.stage2_steps_spin.setEnabled(enabled)
        self.stage3_group.setEnabled(enabled)
        self.stage3_end_spin.setEnabled(enabled)
        self.stage3_steps_spin.setEnabled(enabled)
        self.settle_time_spin.setEnabled(enabled)
        self.dwell_time_spin.setEnabled(enabled)
        self.test_presets_combo.setEnabled(enabled)
        self.save_test_preset_btn.setEnabled(enabled)
        self.delete_test_preset_btn.setEnabled(enabled)
        self.charger_presets_combo.setEnabled(enabled)
        self.save_charger_preset_btn.setEnabled(enabled)
        self.delete_charger_preset_btn.setEnabled(enabled)
        self.charger_name_edit.setEnabled(enabled)
        self.charger_manufacturer_edit.setEnabled(enabled)
        self.charger_model_edit.setEnabled(enabled)
        self.charger_chemistry_combo.setEnabled(enabled)
        self.charger_rated_current_spin.setEnabled(enabled)
        self.charger_rated_voltage_spin.setEnabled(enabled)
        self.charger_notes_edit.setEnabled(enabled)
        self.autosave_checkbox.setEnabled(enabled)
        self.filename_edit.setEnabled(enabled)

    def set_connected(self, connected: bool):
        """Update UI based on connection status."""
        # Start button always enabled (auto-connect handles connection)
        # Only disable when test is running
        self.start_btn.setEnabled(not self._test_running)
        if not connected:
            self.status_label.setText("Not Connected")
            self.status_label.setStyleSheet("color: red;")
        elif not self._test_running:
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")

    def generate_test_filename(self) -> str:
        """Generate a test filename based on charger info and test conditions.

        Format: BatteryCharger_{Manufacturer}_{ChargerName}_{Chemistry}_{MinV}-{MaxV}_{NumSteps}-steps_{Timestamp}.json
        Example: BatteryCharger_Canon_LC-E6_Li-Ion-2S_5.0-8.4V_17-steps_20260210_143022.json
        """
        import datetime
        manufacturer = self.charger_manufacturer_edit.text().strip() or "Unknown"
        safe_manufacturer = "".join(c if c.isalnum() or c in "-" else "-" for c in manufacturer).strip("-")

        charger_name = self.charger_name_edit.text().strip()
        if not charger_name:
            charger_name = "Charger"
        # Sanitize charger name
        safe_name = "".join(c if c.isalnum() or c in "-" else "-" for c in charger_name).strip("-")

        chemistry = self.charger_chemistry_combo.currentText().replace(" ", "-").replace("(", "").replace(")", "")
        min_voltage = self.min_voltage_spin.value()
        max_voltage = self.max_voltage_spin.value()
        num_steps = self.num_steps_spin.value()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = [
            "BatteryCharger",
            safe_manufacturer,
            safe_name,
            chemistry,
            f"{min_voltage}-{max_voltage}V",
            f"{num_steps}-steps",
            timestamp,
        ]

        return "_".join(parts) + ".json"

    def _update_filename(self):
        """Update the filename field with auto-generated name."""
        # Don't update filename during loading to preserve loaded filename
        if not self._loading_settings and self.autosave_checkbox.isChecked():
            self.filename_edit.setText(self.generate_test_filename())

    @Slot(bool)
    def _on_autosave_toggled(self, checked: bool):
        """Handle Auto Save checkbox toggle."""
        self.filename_edit.setReadOnly(checked)
        if checked:
            # Reset to auto-generated filename
            self._update_filename()

    @Slot()
    def _on_save_clicked(self):
        """Handle manual Save button click."""
        filename = self.filename_edit.text().strip()
        if filename:
            # Ensure .json extension
            if not filename.endswith('.json'):
                filename += '.json'
            self.manual_save_requested.emit(filename)

    @Slot()
    def _on_load_clicked(self):
        """Handle Load button click."""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Test Data",
            str(self._atorch_dir / "test_data"),
            "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Update filename to show loaded file
                self.filename_edit.setText(Path(file_path).name)

                # Emit readings for display
                readings = data.get("readings", [])
                if readings:
                    self.session_loaded.emit(readings)

            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load file: {e}")

    @Slot()
    def _on_export_clicked(self):
        """Handle Export button click."""
        self.export_csv_requested.emit()

    @Slot()
    def _on_show_folder_clicked(self):
        """Handle Show Folder button click - open test_data folder in system file browser."""
        import platform
        import subprocess
        folder_path = self._atorch_dir / "test_data"
        folder_path.mkdir(parents=True, exist_ok=True)

        system = platform.system()
        if system == "Darwin":  # macOS
            subprocess.run(["open", str(folder_path)])
        elif system == "Windows":
            subprocess.run(["explorer", str(folder_path)])
        else:  # Linux and others
            subprocess.run(["xdg-open", str(folder_path)])

    def _connect_save_signals(self):
        """Connect all form fields to save settings when changed."""
        # Test Conditions fields
        self.min_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.max_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.num_steps_spin.valueChanged.connect(self._on_settings_changed)
        self.stage2_group.toggled.connect(self._on_settings_changed)
        self.stage2_end_spin.valueChanged.connect(self._on_settings_changed)
        self.stage2_steps_spin.valueChanged.connect(self._on_settings_changed)
        self.stage3_group.toggled.connect(self._on_settings_changed)
        self.stage3_end_spin.valueChanged.connect(self._on_settings_changed)
        self.stage3_steps_spin.valueChanged.connect(self._on_settings_changed)
        self.settle_time_spin.valueChanged.connect(self._on_settings_changed)
        self.dwell_time_spin.valueChanged.connect(self._on_settings_changed)

        # Test presets combo
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Charger Info fields
        self.charger_name_edit.textChanged.connect(self._on_settings_changed)
        self.charger_manufacturer_edit.textChanged.connect(self._on_settings_changed)
        self.charger_model_edit.textChanged.connect(self._on_settings_changed)
        self.charger_chemistry_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.charger_rated_current_spin.valueChanged.connect(self._on_settings_changed)
        self.charger_rated_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.charger_notes_edit.textChanged.connect(self._on_settings_changed)
        self.charger_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Filename update for manufacturer field
        self.charger_manufacturer_edit.textChanged.connect(self._update_filename)

        # Auto Save checkbox
        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self):
        """Handle any settings change - save to file."""
        if not self._loading_settings:
            self._save_session()

    def _save_session(self):
        """Save current settings to file."""
        charger_info = self._get_charger_info()
        charger_info["preset"] = self.charger_presets_combo.currentText()

        settings = {
            "test_config": {
                "preset": self.test_presets_combo.currentText(),
                "load_type": "voltage",
                "stage1_start": self.min_voltage_spin.value(),
                "stage1_end": self.max_voltage_spin.value(),
                "stage1_steps": self.num_steps_spin.value(),
                "stage2_enabled": self.stage2_group.isChecked(),
                "stage2_end": self.stage2_end_spin.value(),
                "stage2_steps": self.stage2_steps_spin.value(),
                "stage3_enabled": self.stage3_group.isChecked(),
                "stage3_end": self.stage3_end_spin.value(),
                "stage3_steps": self.stage3_steps_spin.value(),
                "settle_time": self.settle_time_spin.value(),
                "dwell_time": self.dwell_time_spin.value(),
            },
            "charger_info": charger_info,
            "autosave": self.autosave_checkbox.isChecked(),
        }

        try:
            with open(self._session_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass  # Silently fail - not critical

    def _load_session(self):
        """Load settings from file on startup."""
        if not self._session_file.exists():
            return

        try:
            with open(self._session_file, 'r') as f:
                settings = json.load(f)
        except Exception:
            return  # Silently fail - use defaults

        self._loading_settings = True

        try:
            # Load Test Conditions
            test_config = settings.get("test_config", {})

            # Restore test condition values
            if "stage1_start" in test_config:
                self.min_voltage_spin.setValue(test_config["stage1_start"])
            elif "min_voltage" in test_config:
                self.min_voltage_spin.setValue(test_config["min_voltage"])
            if "stage1_end" in test_config:
                self.max_voltage_spin.setValue(test_config["stage1_end"])
            elif "max_voltage" in test_config:
                self.max_voltage_spin.setValue(test_config["max_voltage"])
            if "stage1_steps" in test_config:
                self.num_steps_spin.setValue(test_config["stage1_steps"])
            elif "num_steps" in test_config:
                self.num_steps_spin.setValue(test_config["num_steps"])
            elif "num_divisions" in test_config:
                self.num_steps_spin.setValue(test_config["num_divisions"])
            if "stage2_enabled" in test_config:
                self.stage2_group.setChecked(test_config["stage2_enabled"])
            if "stage2_end" in test_config:
                self.stage2_end_spin.setValue(test_config["stage2_end"])
            if "stage2_steps" in test_config:
                self.stage2_steps_spin.setValue(test_config["stage2_steps"])
            if "stage3_enabled" in test_config:
                self.stage3_group.setChecked(test_config["stage3_enabled"])
            if "stage3_end" in test_config:
                self.stage3_end_spin.setValue(test_config["stage3_end"])
            if "stage3_steps" in test_config:
                self.stage3_steps_spin.setValue(test_config["stage3_steps"])
            if "settle_time" in test_config:
                self.settle_time_spin.setValue(test_config["settle_time"])
            if "dwell_time" in test_config:
                self.dwell_time_spin.setValue(test_config["dwell_time"])

            # Restore test preset selection
            if "preset" in test_config and test_config["preset"]:
                index = self.test_presets_combo.findText(test_config["preset"])
                if index >= 0:
                    self.test_presets_combo.setCurrentIndex(index)

            # Load Charger Info
            charger_info = settings.get("charger_info", {})
            if charger_info:
                # First restore charger preset selection (before setting values)
                if "preset" in charger_info and charger_info["preset"]:
                    index = self.charger_presets_combo.findText(charger_info["preset"])
                    if index >= 0:
                        self.charger_presets_combo.blockSignals(True)
                        self.charger_presets_combo.setCurrentIndex(index)
                        self.charger_presets_combo.blockSignals(False)

                # Then set the charger info values
                self._set_charger_info(charger_info)

            # Load Auto Save setting
            if "autosave" in settings:
                self.autosave_checkbox.setChecked(settings["autosave"])

        finally:
            self._loading_settings = False
            # Update filename after loading settings
            self._update_filename()

    def get_test_config(self) -> dict:
        """Get current test configuration as a dictionary.

        Returns:
            Dictionary with load_type, stage1_start, stage1_end, stage1_steps, settle_time, dwell_time
        """
        config = {
            "load_type": "voltage",
            "stage1_start": self.min_voltage_spin.value(),
            "stage1_end": self.max_voltage_spin.value(),
            "stage1_steps": self.num_steps_spin.value(),
            "stage2_enabled": self.stage2_group.isChecked(),
            "stage2_start": self.max_voltage_spin.value(),
            "stage2_end": self.stage2_end_spin.value(),
            "stage2_steps": self.stage2_steps_spin.value(),
            "stage3_enabled": self.stage3_group.isChecked(),
            "stage3_start": self.stage2_end_spin.value(),
            "stage3_end": self.stage3_end_spin.value(),
            "stage3_steps": self.stage3_steps_spin.value(),
            "settle_time": self.settle_time_spin.value(),
            "dwell_time": self.dwell_time_spin.value(),
        }
        return config

    def get_charger_info(self) -> dict:
        """Get current charger info as a dictionary.

        Returns:
            Dictionary with charger information
        """
        return self._get_charger_info()
