"""Battery Charger test panel for CC-CV characteristic testing."""

import json
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QProgressBar, QCheckBox, QLineEdit
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
    test_started = Signal()  # Emitted when test starts
    test_stopped = Signal()  # Emitted when test stops (complete or aborted)

    def __init__(self):
        super().__init__()

        # Load default charger presets from resources
        self._default_charger_presets = self._load_presets_file("battery_charger/presets_chargers.json")

        # Load default test presets
        self._default_test_presets = self._load_presets_file("battery_charger/presets_test.json")

        # User presets directory
        self._atorch_dir = Path.home() / ".atorch"
        self._atorch_dir.mkdir(parents=True, exist_ok=True)
        self._charger_presets_dir = self._atorch_dir / "battery_charger_presets"
        self._charger_presets_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self._atorch_dir / "battery_charger_session.json"

        # Flag to prevent saving during load
        self._loading_settings = False

        # Test state
        self._test_running = False
        self._test_timer = QTimer()
        self._test_timer.timeout.connect(self._run_test_step)
        self._current_step = 0
        self._total_steps = 0
        self._step_size = 0.0
        self._current_value = 0.0
        self._test_start_time = 0
        self._device = None
        self._plot_panel = None

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

        # Presets section
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets"))
        self.test_presets_combo = QComboBox()
        presets_layout.addWidget(self.test_presets_combo, 1)

        self.save_test_preset_btn = QPushButton("Save")
        self.save_test_preset_btn.setMaximumWidth(50)
        presets_layout.addWidget(self.save_test_preset_btn)

        self.delete_test_preset_btn = QPushButton("Delete")
        self.delete_test_preset_btn.setMaximumWidth(50)
        self.delete_test_preset_btn.setEnabled(False)
        presets_layout.addWidget(self.delete_test_preset_btn)
        conditions_layout.addLayout(presets_layout)

        # Test parameters
        params_group = QGroupBox()
        params_layout = QFormLayout(params_group)
        params_layout.setContentsMargins(6, 6, 6, 6)

        # Chemistry dropdown
        self.chemistry_combo = QComboBox()
        self.chemistry_combo.addItems(list(CHEMISTRY_RANGES.keys()))
        self.chemistry_combo.currentTextChanged.connect(self._on_chemistry_changed)
        params_layout.addRow("Chemistry", self.chemistry_combo)

        # Min Voltage
        self.min_voltage_spin = QDoubleSpinBox()
        self.min_voltage_spin.setRange(0.0, 60.0)
        self.min_voltage_spin.setDecimals(2)
        self.min_voltage_spin.setValue(2.5)
        self.min_voltage_spin.setSuffix(" V")
        params_layout.addRow("Min Voltage", self.min_voltage_spin)

        # Max Voltage
        self.max_voltage_spin = QDoubleSpinBox()
        self.max_voltage_spin.setRange(0.0, 60.0)
        self.max_voltage_spin.setDecimals(2)
        self.max_voltage_spin.setValue(4.2)
        self.max_voltage_spin.setSuffix(" V")
        params_layout.addRow("Max Voltage", self.max_voltage_spin)

        # Number of divisions with preset dropdown
        num_divisions_layout = QHBoxLayout()
        self.num_divisions_spin = QSpinBox()
        self.num_divisions_spin.setRange(1, 999)
        self.num_divisions_spin.setValue(10)  # 10 divisions = 11 measurement points
        num_divisions_layout.addWidget(self.num_divisions_spin)

        self.num_divisions_preset_combo = QComboBox()
        self.num_divisions_preset_combo.addItem("Presets...")  # Placeholder
        self.num_divisions_preset_combo.addItems(["5", "10", "20", "30", "40", "50"])
        self.num_divisions_preset_combo.setCurrentIndex(0)  # Show placeholder
        self.num_divisions_preset_combo.currentTextChanged.connect(self._on_num_divisions_preset_changed)
        num_divisions_layout.addWidget(self.num_divisions_preset_combo)

        params_layout.addRow("Divisions", num_divisions_layout)

        # Dwell time
        self.dwell_time_spin = QSpinBox()
        self.dwell_time_spin.setRange(0, 3600)
        self.dwell_time_spin.setValue(5)
        self.dwell_time_spin.setSuffix(" s")
        params_layout.addRow("Dwell Time", self.dwell_time_spin)

        conditions_layout.addWidget(params_group)
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

        self.charger_model_edit = QLineEdit()
        self.charger_model_edit.setPlaceholderText("e.g., A2017")
        charger_form_layout.addRow("Model", self.charger_model_edit)

        self.charger_chemistry_combo = QComboBox()
        self.charger_chemistry_combo.addItems(list(CHEMISTRY_RANGES.keys()))
        charger_form_layout.addRow("Chemistry", self.charger_chemistry_combo)

        self.charger_rated_current_spin = QDoubleSpinBox()
        self.charger_rated_current_spin.setRange(0.0, 100.0)
        self.charger_rated_current_spin.setDecimals(2)
        self.charger_rated_current_spin.setValue(0.0)
        self.charger_rated_current_spin.setSuffix(" A")
        charger_form_layout.addRow("Rated Current", self.charger_rated_current_spin)

        self.charger_rated_voltage_spin = QDoubleSpinBox()
        self.charger_rated_voltage_spin.setRange(0.0, 60.0)
        self.charger_rated_voltage_spin.setDecimals(2)
        self.charger_rated_voltage_spin.setValue(0.0)
        self.charger_rated_voltage_spin.setSuffix(" V")
        charger_form_layout.addRow("Rated Voltage", self.charger_rated_voltage_spin)

        self.charger_num_cells_spin = QSpinBox()
        self.charger_num_cells_spin.setRange(1, 20)
        self.charger_num_cells_spin.setValue(1)
        charger_form_layout.addRow("Number of Cells", self.charger_num_cells_spin)

        self.charger_notes_edit = QLineEdit()
        self.charger_notes_edit.setPlaceholderText("Additional notes...")
        charger_form_layout.addRow("Notes", self.charger_notes_edit)

        charger_info_layout.addWidget(charger_form)
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
        self.save_btn.setEnabled(False)  # Disabled when Auto Save is checked
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

    def _on_chemistry_changed(self, chemistry: str):
        """Update voltage ranges based on selected chemistry."""
        if chemistry in CHEMISTRY_RANGES:
            min_v, max_v = CHEMISTRY_RANGES[chemistry]
            self.min_voltage_spin.setValue(min_v)
            self.max_voltage_spin.setValue(max_v)

    def _on_num_divisions_preset_changed(self, value: str):
        """Update spinbox when preset is selected from dropdown."""
        if value and value.isdigit():
            self.num_divisions_spin.setValue(int(value))
            # Reset combo to placeholder after applying
            self.num_divisions_preset_combo.setCurrentIndex(0)

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
            self.charger_rated_current_spin.setValue(data.get("rated_current", 0.0))
            self.charger_rated_voltage_spin.setValue(data.get("rated_voltage", 0.0))
            self.charger_num_cells_spin.setValue(data.get("num_cells", 1))
            self.charger_notes_edit.setText(data.get("notes", ""))
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
            "num_cells": self.charger_num_cells_spin.value(),
            "notes": self.charger_notes_edit.text().strip(),
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

        # Add Default Presets section
        if self._default_test_presets:
            self.test_presets_combo.addItem("─── Default Tests ───")
            self.test_presets_combo.model().item(self.test_presets_combo.count() - 1).setEnabled(False)
            for name in sorted(self._default_test_presets.keys()):
                self.test_presets_combo.addItem(name)

        # Add User Presets section
        user_presets = []
        if self._charger_presets_dir.exists():
            # Note: Test presets are stored in charger_presets_dir
            for preset_file in sorted(self._charger_presets_dir.glob("test_*.json")):
                user_presets.append(preset_file.stem)

        if user_presets:
            self.test_presets_combo.addItem("─── My Tests ───")
            self.test_presets_combo.model().item(self.test_presets_combo.count() - 1).setEnabled(False)
            for name in user_presets:
                self.test_presets_combo.addItem(name)

    def _on_test_preset_selected(self, index: int):
        """Handle test preset selection."""
        # Skip if we're loading settings from session file
        if self._loading_settings:
            return

        preset_name = self.test_presets_combo.currentText()

        # Check if it's a separator
        if "───" in preset_name or not preset_name:
            self.delete_test_preset_btn.setEnabled(False)
            return

        # Check if it's a user preset (enable delete button)
        preset_file = self._charger_presets_dir / f"{preset_name}.json"
        self.delete_test_preset_btn.setEnabled(preset_file.exists())

        # Load preset data
        preset_data = None
        if preset_name in self._default_test_presets:
            preset_data = self._default_test_presets[preset_name]
        elif preset_file.exists():
            try:
                with open(preset_file, 'r') as f:
                    preset_data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        if preset_data:
            # Load test conditions from preset
            chemistry = preset_data.get("chemistry", "Li-Ion (1S)")
            self.chemistry_combo.setCurrentText(chemistry)
            self.min_voltage_spin.setValue(preset_data.get("min_voltage", 2.5))
            self.max_voltage_spin.setValue(preset_data.get("max_voltage", 4.2))
            self.num_divisions_spin.setValue(preset_data.get("num_divisions", 10))
            self.dwell_time_spin.setValue(preset_data.get("dwell_time", 5))

    def _save_test_preset(self):
        """Save current test conditions as a preset."""
        from PySide6.QtWidgets import QInputDialog

        # Ask for preset name
        preset_name, ok = QInputDialog.getText(
            self, "Save Test Preset",
            "Preset name:"
        )

        if not ok or not preset_name:
            return

        # Save preset
        data = {
            "chemistry": self.chemistry_combo.currentText(),
            "min_voltage": self.min_voltage_spin.value(),
            "max_voltage": self.max_voltage_spin.value(),
            "num_divisions": self.num_divisions_spin.value(),
            "dwell_time": self.dwell_time_spin.value()
        }
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in (' ', '-', '_')).strip()

        preset_file = self._charger_presets_dir / f"test_{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_test_presets_list()
            # Select the newly saved preset
            index = self.test_presets_combo.findText(f"test_{safe_name}")
            if index >= 0:
                self.test_presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    def _delete_test_preset(self):
        """Delete the selected user test preset."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or "───" in preset_name:
            return

        preset_file = self._charger_presets_dir / f"{preset_name}.json"
        if not preset_file.exists():
            QMessageBox.warning(self, "Delete Preset", "Cannot delete built-in presets.")
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete test preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
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
            self._abort_test()
        else:
            self._start_test()

    def _start_test(self):
        """Start the stepped voltage test."""
        # Get test parameters (connection check will happen in main_window)
        min_voltage = self.min_voltage_spin.value()
        max_voltage = self.max_voltage_spin.value()
        num_divisions = self.num_divisions_spin.value()
        dwell_time = self.dwell_time_spin.value()

        # Validate parameters
        if min_voltage >= max_voltage:
            QMessageBox.warning(self, "Invalid Parameters", "Min Voltage must be less than Max Voltage.")
            return
        if num_divisions < 1:
            QMessageBox.warning(self, "Invalid Parameters", "Divisions must be at least 1.")
            return

        # Emit signal that test is starting (triggers logging in main window)
        self.test_started.emit()

        # Calculate actual number of steps (divisions + 1)
        self._total_steps = num_divisions + 1
        self._step_size = (max_voltage - min_voltage) / num_divisions
        self._current_step = 0
        self._current_value = min_voltage

        try:
            # Set CV mode and initial voltage
            self._device.set_voltage(min_voltage)

            # Turn on load
            self._device.turn_on()

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
        self.status_label.setText(f"Step 1/{self._total_steps}: {min_voltage:.2f}V")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.progress_bar.setValue(0)
        self._test_running = True
        self._test_start_time = time.time()

        # Start timer for first dwell period
        self._test_timer.start(dwell_time * 1000)  # Convert seconds to milliseconds

    def _abort_test(self):
        """Abort the running test."""
        self._test_timer.stop()

        # Turn off load
        if self._device:
            try:
                self._device.turn_off()
            except Exception:
                pass  # Ignore errors during abort

        self._finish_test()

    def _run_test_step(self):
        """Execute one step of the test."""
        self._test_timer.stop()

        # Check if device is still connected
        if not self._device or not self._device.is_connected:
            QMessageBox.critical(self, "Connection Lost", "Device disconnected during test.")
            self._abort_test()
            return

        # Move to next step
        self._current_step += 1

        # Check if test is complete
        if self._current_step >= self._total_steps:
            self._finish_test()
            return

        # Calculate next voltage
        self._current_value = self.min_voltage_spin.value() + (self._current_step * self._step_size)

        # Set new voltage
        try:
            self._device.set_voltage(self._current_value)
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Device Error", f"Failed to set voltage: {e}")
            self._abort_test()
            return

        # Update UI
        progress = int((self._current_step / self._total_steps) * 100)
        self.progress_bar.setValue(progress)
        self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: {self._current_value:.2f}V")
        self._update_test_time()

        # Start timer for next dwell period
        dwell_time = self.dwell_time_spin.value()
        self._test_timer.start(dwell_time * 1000)

    def _update_test_time(self):
        """Update the time label."""
        elapsed = time.time() - self._test_start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        self.time_label.setText(f"{hours}h {minutes}m {seconds}s")

    def _finish_test(self, status: str = "Test Complete"):
        """Clean up when test completes."""
        # Emit signal that test is stopping (triggers auto-save in main window)
        self.test_stopped.emit()

        # Turn off load
        if self._device:
            try:
                self._device.turn_off()
            except Exception:
                pass

        # Update UI
        self.start_btn.setText("Start")
        # Only update status if not already showing an error
        if not self.status_label.text().startswith("Error") and not self.status_label.text().startswith("Connection Lost"):
            self.status_label.setText(status)
        self.progress_bar.setValue(100)
        self._update_test_time()
        self._test_running = False

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
        """Generate a test filename based on charger info and test conditions."""
        import datetime
        charger_name = self.charger_name_edit.text().strip()
        if not charger_name:
            charger_name = "Charger"
        # Replace spaces and special chars with underscores
        safe_name = "".join(c if c.isalnum() else "_" for c in charger_name)
        chemistry = self.chemistry_combo.currentText().replace(" ", "_")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{safe_name}_{chemistry}_{timestamp}.json"

    def _update_filename(self):
        """Update the filename field with auto-generated name."""
        if self.autosave_checkbox.isChecked():
            self.filename_edit.setText(self.generate_test_filename())

    @Slot(bool)
    def _on_autosave_toggled(self, checked: bool):
        """Handle Auto Save checkbox toggle."""
        self.filename_edit.setReadOnly(checked)
        self.save_btn.setEnabled(not checked)
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
        self.chemistry_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.min_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.max_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.num_divisions_spin.valueChanged.connect(self._on_settings_changed)
        self.dwell_time_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Charger Info fields
        self.charger_name_edit.textChanged.connect(self._on_settings_changed)
        self.charger_manufacturer_edit.textChanged.connect(self._on_settings_changed)
        self.charger_model_edit.textChanged.connect(self._on_settings_changed)
        self.charger_chemistry_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.charger_rated_current_spin.valueChanged.connect(self._on_settings_changed)
        self.charger_rated_voltage_spin.valueChanged.connect(self._on_settings_changed)
        self.charger_num_cells_spin.valueChanged.connect(self._on_settings_changed)
        self.charger_notes_edit.textChanged.connect(self._on_settings_changed)
        self.charger_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

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
                "chemistry": self.chemistry_combo.currentText(),
                "min_voltage": self.min_voltage_spin.value(),
                "max_voltage": self.max_voltage_spin.value(),
                "num_divisions": self.num_divisions_spin.value(),
                "dwell_time": self.dwell_time_spin.value(),
                "preset": self.test_presets_combo.currentText(),
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

            # First, restore the test preset selection (before other values)
            if "preset" in test_config and test_config["preset"]:
                preset_name = test_config["preset"]
                index = self.test_presets_combo.findText(preset_name)
                if index >= 0:
                    self.test_presets_combo.blockSignals(True)
                    self.test_presets_combo.setCurrentIndex(index)
                    self.test_presets_combo.blockSignals(False)

            # Then restore other test condition values
            if "chemistry" in test_config:
                self.chemistry_combo.setCurrentText(test_config["chemistry"])
            if "min_voltage" in test_config:
                self.min_voltage_spin.setValue(test_config["min_voltage"])
            if "max_voltage" in test_config:
                self.max_voltage_spin.setValue(test_config["max_voltage"])
            if "num_divisions" in test_config:
                self.num_divisions_spin.setValue(test_config["num_divisions"])
            if "dwell_time" in test_config:
                self.dwell_time_spin.setValue(test_config["dwell_time"])

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
            Dictionary with chemistry, min_voltage, max_voltage, num_divisions, dwell_time
        """
        return {
            "chemistry": self.chemistry_combo.currentText(),
            "min_voltage": self.min_voltage_spin.value(),
            "max_voltage": self.max_voltage_spin.value(),
            "num_divisions": self.num_divisions_spin.value(),  # Now represents divisions (actual steps = divisions + 1)
            "dwell_time": self.dwell_time_spin.value(),
        }

    def get_charger_info(self) -> dict:
        """Get current charger info as a dictionary.

        Returns:
            Dictionary with charger information
        """
        return self._get_charger_info()
