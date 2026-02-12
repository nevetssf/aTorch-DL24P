"""Cable Resistance test panel for USB cable testing."""

import json
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QProgressBar, QCheckBox, QLineEdit, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Signal, Slot, QTimer, Qt
from PySide6.QtGui import QColor


class CableResistancePanel(QWidget):
    """Panel for cable resistance testing by stepping through current levels."""

    # Signals
    manual_save_requested = Signal(str)  # filename
    session_loaded = Signal(list)  # readings
    export_csv_requested = Signal()
    test_started = Signal()  # Emitted when test starts
    test_stopped = Signal()  # Emitted when test stops (complete or aborted)

    def __init__(self):
        super().__init__()

        # Load default cable presets from resources
        self._default_cable_presets = self._load_presets_file("cable_resistance/presets_cables.json")

        # Load default test presets
        self._default_test_presets = self._load_presets_file("cable_resistance/presets_test.json")

        # User presets directory
        self._atorch_dir = Path.home() / ".atorch"
        self._atorch_dir.mkdir(parents=True, exist_ok=True)
        self._cable_presets_dir = self._atorch_dir / "cable_presets"
        self._cable_presets_dir.mkdir(parents=True, exist_ok=True)
        self._test_presets_dir = self._atorch_dir / "cable_resistance_presets"
        self._test_presets_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self._atorch_dir / "cable_resistance_session.json"

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

        # Test results storage
        self._test_results = []  # List of dicts with {current, voltage_measured, voltage_drop, resistance}

        self._create_ui()
        self._load_cable_presets_list()
        self._load_test_presets_list()
        self._connect_signals()
        self._connect_save_signals()
        self._load_session()
        self._update_filename()  # Initialize filename after loading settings

    def _create_ui(self):
        """Create the cable resistance panel UI."""
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

        # Source voltage
        self.source_voltage_combo = QComboBox()
        self.source_voltage_combo.setEditable(True)
        self.source_voltage_combo.addItems(["5.0", "9.0", "12.0", "15.0", "20.0"])
        self.source_voltage_combo.setCurrentText("5.0")
        self.source_voltage_combo.currentTextChanged.connect(lambda: self._update_filename())
        params_layout.addRow("Source Voltage (V)", self.source_voltage_combo)

        # Min current
        self.min_current_spin = QDoubleSpinBox()
        self.min_current_spin.setRange(0.1, 10.0)
        self.min_current_spin.setDecimals(2)
        self.min_current_spin.setValue(0.5)
        self.min_current_spin.setSingleStep(0.1)
        self.min_current_spin.setSuffix(" A")
        self.min_current_spin.valueChanged.connect(lambda: self._update_filename())
        params_layout.addRow("Min Current", self.min_current_spin)

        # Max current
        self.max_current_spin = QDoubleSpinBox()
        self.max_current_spin.setRange(0.1, 10.0)
        self.max_current_spin.setDecimals(2)
        self.max_current_spin.setValue(3.0)
        self.max_current_spin.setSingleStep(0.1)
        self.max_current_spin.setSuffix(" A")
        self.max_current_spin.valueChanged.connect(lambda: self._update_filename())
        params_layout.addRow("Max Current", self.max_current_spin)

        # Number of steps with preset dropdown
        num_steps_layout = QHBoxLayout()
        self.num_steps_spin = QSpinBox()
        self.num_steps_spin.setRange(3, 20)
        self.num_steps_spin.setValue(5)
        self.num_steps_spin.valueChanged.connect(lambda: self._update_filename())
        num_steps_layout.addWidget(self.num_steps_spin)

        self.num_steps_preset_combo = QComboBox()
        self.num_steps_preset_combo.addItem("Presets...")  # Placeholder
        self.num_steps_preset_combo.addItems(["3", "5", "10", "15", "20"])
        self.num_steps_preset_combo.setCurrentIndex(0)  # Show placeholder
        self.num_steps_preset_combo.currentTextChanged.connect(self._on_num_steps_preset_changed)
        num_steps_layout.addWidget(self.num_steps_preset_combo)

        params_layout.addRow("Steps", num_steps_layout)

        # Dwell time
        self.dwell_time_spin = QSpinBox()
        self.dwell_time_spin.setRange(1, 60)
        self.dwell_time_spin.setValue(5)
        self.dwell_time_spin.setSuffix(" s")
        params_layout.addRow("Dwell Time", self.dwell_time_spin)

        conditions_layout.addWidget(params_group)
        conditions_layout.addStretch()

        layout.addWidget(conditions_group)

        # Middle: Cable Info
        cable_info_group = QGroupBox("Cable Info")
        cable_info_group.setFixedWidth(350)
        cable_info_layout = QVBoxLayout(cable_info_group)

        # Presets section
        cable_presets_layout = QHBoxLayout()
        cable_presets_layout.addWidget(QLabel("Presets"))
        self.cable_presets_combo = QComboBox()
        cable_presets_layout.addWidget(self.cable_presets_combo, 1)

        self.save_cable_preset_btn = QPushButton("Save")
        self.save_cable_preset_btn.setMaximumWidth(50)
        cable_presets_layout.addWidget(self.save_cable_preset_btn)

        self.delete_cable_preset_btn = QPushButton("Delete")
        self.delete_cable_preset_btn.setMaximumWidth(50)
        self.delete_cable_preset_btn.setEnabled(False)
        cable_presets_layout.addWidget(self.delete_cable_preset_btn)
        cable_info_layout.addLayout(cable_presets_layout)

        # Cable info fields
        cable_specs_group = QGroupBox()
        cable_specs_layout = QFormLayout(cable_specs_group)
        cable_specs_layout.setContentsMargins(6, 6, 6, 6)

        self.cable_name_edit = QLineEdit()
        self.cable_name_edit.setPlaceholderText("e.g., Anker PowerLine USB-C")
        self.cable_name_edit.textChanged.connect(lambda: self._update_filename())
        cable_specs_layout.addRow("Name", self.cable_name_edit)

        self.cable_type_combo = QComboBox()
        self.cable_type_combo.addItems([
            "USB-A to USB-C",
            "USB-C to USB-C",
            "USB-A to Micro-USB",
            "Lightning to USB-C",
            "USB-A to Lightning",
            "DC Barrel",
            "Other"
        ])
        cable_specs_layout.addRow("Cable Type", self.cable_type_combo)

        self.rated_current_combo = QComboBox()
        self.rated_current_combo.addItems(["1A", "2A", "3A", "5A"])
        self.rated_current_combo.setCurrentText("3A")
        cable_specs_layout.addRow("Rated Current", self.rated_current_combo)

        self.cable_length_spin = QDoubleSpinBox()
        self.cable_length_spin.setRange(0.1, 5.0)
        self.cable_length_spin.setDecimals(1)
        self.cable_length_spin.setValue(1.0)
        self.cable_length_spin.setSingleStep(0.1)
        self.cable_length_spin.setSuffix(" m")
        cable_specs_layout.addRow("Cable Length", self.cable_length_spin)

        self.wire_gauge_combo = QComboBox()
        self.wire_gauge_combo.addItems(["20 AWG", "22 AWG", "24 AWG", "26 AWG", "28 AWG", "Unknown"])
        self.wire_gauge_combo.setCurrentText("Unknown")
        cable_specs_layout.addRow("Wire Gauge", self.wire_gauge_combo)

        cable_info_layout.addWidget(cable_specs_group)

        # Notes field
        notes_group = QGroupBox()
        notes_layout = QFormLayout(notes_group)
        notes_layout.setContentsMargins(6, 6, 6, 6)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)
        self.notes_edit.setPlaceholderText("Test notes...")
        notes_layout.addRow("Notes", self.notes_edit)

        cable_info_layout.addWidget(notes_group)

        layout.addWidget(cable_info_group)

        # Right: Test Control and Results
        right_layout = QVBoxLayout()

        # Test Control group
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Abort button
        self.start_btn = QPushButton("Start")
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

        right_layout.addWidget(control_group)

        # Results group
        results_group = QGroupBox("Test Results")
        results_layout = QVBoxLayout(results_group)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Current (A)", "Voltage (V)", "Drop (mV)", "R (mΩ)"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setMaximumHeight(150)
        results_layout.addWidget(self.results_table)

        # Summary labels
        summary_layout = QFormLayout()
        self.avg_resistance_label = QLabel("--")
        summary_layout.addRow("Avg Resistance:", self.avg_resistance_label)

        self.quality_label = QLabel("--")
        summary_layout.addRow("Quality:", self.quality_label)

        self.max_drop_label = QLabel("--")
        summary_layout.addRow("Max Voltage Drop:", self.max_drop_label)

        self.power_loss_label = QLabel("--")
        summary_layout.addRow("Power Loss @ Rated:", self.power_loss_label)

        results_layout.addLayout(summary_layout)

        right_layout.addWidget(results_group)

        layout.addLayout(right_layout, 1)

    def _on_num_steps_preset_changed(self, value: str):
        """Update spinbox when preset is selected from dropdown."""
        if value and value.isdigit():
            self.num_steps_spin.setValue(int(value))
            # Reset combo to placeholder after applying
            self.num_steps_preset_combo.setCurrentIndex(0)

    def _connect_signals(self):
        """Connect cable preset and test preset signals."""
        # Cable preset signals
        self.cable_presets_combo.currentIndexChanged.connect(self._on_cable_preset_selected)
        self.save_cable_preset_btn.clicked.connect(self._save_cable_preset)
        self.delete_cable_preset_btn.clicked.connect(self._delete_cable_preset)

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

    def _load_cable_presets_list(self):
        """Load cable presets into the combo box."""
        self.cable_presets_combo.clear()
        self.cable_presets_combo.addItem("")  # Empty option

        # Add Default Presets section
        if self._default_cable_presets:
            self.cable_presets_combo.addItem("─── Default Cables ───")
            self.cable_presets_combo.model().item(self.cable_presets_combo.count() - 1).setEnabled(False)
            for name in sorted(self._default_cable_presets.keys()):
                self.cable_presets_combo.addItem(name)

        # Add User Presets section
        user_presets = []
        if self._cable_presets_dir.exists():
            for preset_file in sorted(self._cable_presets_dir.glob("*.json")):
                user_presets.append(preset_file.stem)

        if user_presets:
            self.cable_presets_combo.addItem("─── My Cables ───")
            self.cable_presets_combo.model().item(self.cable_presets_combo.count() - 1).setEnabled(False)
            for name in user_presets:
                self.cable_presets_combo.addItem(name)

    def _on_cable_preset_selected(self, index: int):
        """Handle cable preset selection."""
        # Skip if we're loading settings from session file
        if self._loading_settings:
            return

        preset_name = self.cable_presets_combo.currentText()

        # Check if it's a separator
        if "───" in preset_name or not preset_name:
            self.delete_cable_preset_btn.setEnabled(False)
            return

        # Check if it's a user preset (enable delete button)
        preset_file = self._cable_presets_dir / f"{preset_name}.json"
        self.delete_cable_preset_btn.setEnabled(preset_file.exists())

        # Load preset data
        preset_data = None
        if preset_name in self._default_cable_presets:
            preset_data = self._default_cable_presets[preset_name]
        elif preset_file.exists():
            try:
                with open(preset_file, 'r') as f:
                    preset_data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        if preset_data:
            self._set_cable_info(preset_data)

    def _set_cable_info(self, info: dict):
        """Set cable info from a dictionary."""
        if "name" in info:
            self.cable_name_edit.setText(info["name"])
        if "cable_type" in info:
            index = self.cable_type_combo.findText(info["cable_type"])
            if index >= 0:
                self.cable_type_combo.setCurrentIndex(index)
        if "rated_current" in info:
            # Handle both float (3.0) and string ("3A") formats
            rated_str = str(info["rated_current"])
            if "A" not in rated_str:
                rated_str = f"{float(rated_str):.0f}A"
            index = self.rated_current_combo.findText(rated_str)
            if index >= 0:
                self.rated_current_combo.setCurrentIndex(index)
        if "length_m" in info:
            self.cable_length_spin.setValue(float(info["length_m"]))
        if "wire_gauge" in info:
            gauge_str = info["wire_gauge"]
            # Try to match with or without " AWG" suffix
            if "AWG" not in gauge_str and gauge_str != "Unknown":
                gauge_str = f"{gauge_str} AWG"
            index = self.wire_gauge_combo.findText(gauge_str)
            if index >= 0:
                self.wire_gauge_combo.setCurrentIndex(index)
        if "notes" in info:
            self.notes_edit.setPlainText(info["notes"])

    def _get_cable_info(self) -> dict:
        """Get cable info as a dictionary."""
        return {
            "name": self.cable_name_edit.text(),
            "cable_type": self.cable_type_combo.currentText(),
            "rated_current": float(self.rated_current_combo.currentText().replace("A", "")),
            "length_m": self.cable_length_spin.value(),
            "wire_gauge": self.wire_gauge_combo.currentText(),
            "notes": self.notes_edit.toPlainText(),
        }

    def _save_cable_preset(self):
        """Save current cable info as a preset."""
        from PySide6.QtWidgets import QInputDialog

        name = self.cable_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Preset", "Please enter a cable name first.")
            return

        # Ask for preset name (default to cable name)
        preset_name, ok = QInputDialog.getText(
            self, "Save Cable Preset",
            "Preset name:", text=name
        )

        if not ok or not preset_name:
            return

        # Save preset
        data = self._get_cable_info()
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in (' ', '-', '_')).strip()

        preset_file = self._cable_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_cable_presets_list()
            # Select the newly saved preset
            index = self.cable_presets_combo.findText(safe_name)
            if index >= 0:
                self.cable_presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    def _delete_cable_preset(self):
        """Delete the selected user cable preset."""
        preset_name = self.cable_presets_combo.currentText()
        if not preset_name or "───" in preset_name:
            return

        preset_file = self._cable_presets_dir / f"{preset_name}.json"
        if not preset_file.exists():
            QMessageBox.warning(self, "Delete Preset", "Cannot delete built-in presets.")
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete cable preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                preset_file.unlink()
                self._load_cable_presets_list()
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
        if self._test_presets_dir.exists():
            for preset_file in sorted(self._test_presets_dir.glob("*.json")):
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
        preset_file = self._test_presets_dir / f"{preset_name}.json"
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
            self.source_voltage_combo.setCurrentText(str(preset_data.get("source_voltage", 5.0)))
            self.min_current_spin.setValue(preset_data.get("min_current", 0.5))
            self.max_current_spin.setValue(preset_data.get("max_current", 3.0))
            self.num_steps_spin.setValue(preset_data.get("num_steps", 5))
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
            "source_voltage": float(self.source_voltage_combo.currentText()),
            "min_current": self.min_current_spin.value(),
            "max_current": self.max_current_spin.value(),
            "num_steps": self.num_steps_spin.value(),
            "dwell_time": self.dwell_time_spin.value()
        }
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in (' ', '-', '_')).strip()

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

    def _delete_test_preset(self):
        """Delete the selected user test preset."""
        preset_name = self.test_presets_combo.currentText()
        if not preset_name or "───" in preset_name:
            return

        preset_file = self._test_presets_dir / f"{preset_name}.json"
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
        """Start the cable resistance test."""
        # Update filename if autosave is enabled
        if self.autosave_checkbox.isChecked():
            self._update_filename()

        # Get test parameters
        try:
            source_voltage = float(self.source_voltage_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Invalid source voltage value.")
            return

        min_current = self.min_current_spin.value()
        max_current = self.max_current_spin.value()
        num_steps = self.num_steps_spin.value()
        dwell_time = self.dwell_time_spin.value()

        # Validate parameters
        if min_current >= max_current:
            QMessageBox.warning(self, "Invalid Parameters", "Min current must be less than Max current.")
            return
        if num_steps < 3:
            QMessageBox.warning(self, "Invalid Parameters", "Number of steps must be at least 3.")
            return

        # Store source voltage for calculations
        self._source_voltage = source_voltage

        # Clear previous results
        self._test_results = []
        self.results_table.setRowCount(0)
        self._clear_results_summary()

        # Emit signal that test is starting (triggers logging in main window)
        self.test_started.emit()

        # Calculate test steps
        self._total_steps = num_steps
        self._step_size = (max_current - min_current) / (num_steps - 1)
        self._current_step = 0
        self._current_value = min_current

        try:
            # Set device to CC mode and initial current
            self._device.set_current(min_current)

            # Turn on load
            self._device.turn_on()

        except Exception as e:
            QMessageBox.critical(self, "Device Error", f"Failed to configure device: {e}")
            return

        # Switch plot to show Current vs Voltage
        if self._plot_panel:
            self._plot_panel.x_axis_combo.setCurrentText("Current")
            # Enable Voltage on Y-axis
            if "Y" in self._plot_panel._axis_dropdowns:
                self._plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self._plot_panel._axis_checkboxes["Y"].setChecked(True)

        # Update UI
        self.start_btn.setText("Abort")
        self.status_label.setText(f"Step 1/{self._total_steps}: {min_current:.2f}A")
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

        self._finish_test("Test Aborted")

    def _run_test_step(self):
        """Execute one step of the test."""
        self._test_timer.stop()

        # Check if device is still connected
        if not self._device or not self._device.is_connected:
            QMessageBox.critical(self, "Connection Lost", "Device disconnected during test.")
            self._abort_test()
            return

        # Record measurement at current step
        if self._device.last_status:
            status = self._device.last_status
            voltage_measured = status.voltage_v
            current = status.current_a
            voltage_drop = self._source_voltage - voltage_measured

            # Calculate resistance: R = V_drop / I (in mΩ)
            if current > 0.001:  # Avoid division by zero
                resistance_mohm = (voltage_drop / current) * 1000.0
            else:
                resistance_mohm = 0.0

            # Store result
            result = {
                "current": current,
                "voltage_measured": voltage_measured,
                "voltage_drop": voltage_drop,
                "resistance": resistance_mohm
            }
            self._test_results.append(result)

            # Add to table
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(f"{current:.3f}"))
            self.results_table.setItem(row, 1, QTableWidgetItem(f"{voltage_measured:.3f}"))
            self.results_table.setItem(row, 2, QTableWidgetItem(f"{voltage_drop * 1000:.1f}"))
            self.results_table.setItem(row, 3, QTableWidgetItem(f"{resistance_mohm:.1f}"))

        # Move to next step
        self._current_step += 1

        # Check if test is complete
        if self._current_step >= self._total_steps:
            self._finish_test()
            return

        # Calculate next current value
        self._current_value = self.min_current_spin.value() + (self._current_step * self._step_size)

        # Set new current
        try:
            self._device.set_current(self._current_value)
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Device Error", f"Failed to set current: {e}")
            self._abort_test()
            return

        # Update UI
        progress = int((self._current_step / self._total_steps) * 100)
        self.progress_bar.setValue(progress)
        self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: {self._current_value:.2f}A")
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

        # Calculate and display results summary
        self._calculate_results_summary()

        # Update UI
        self.start_btn.setText("Start")
        # Only update status if not already showing an error
        if not self.status_label.text().startswith("Error") and not self.status_label.text().startswith("Connection Lost"):
            self.status_label.setText(status)
        self.progress_bar.setValue(100)
        self._update_test_time()
        self._test_running = False

    def _calculate_results_summary(self):
        """Calculate and display results summary."""
        if not self._test_results:
            return

        # Calculate average resistance (excluding zero readings)
        valid_readings = [r["resistance"] for r in self._test_results if r["resistance"] > 0]
        if valid_readings:
            avg_resistance = sum(valid_readings) / len(valid_readings)
        else:
            avg_resistance = 0.0

        # Determine quality rating
        quality_text, quality_color = self._get_quality_rating(avg_resistance)

        # Calculate max voltage drop
        max_drop = max(r["voltage_drop"] for r in self._test_results) if self._test_results else 0.0

        # Calculate power loss at rated current
        rated_current_str = self.rated_current_combo.currentText().replace("A", "")
        rated_current = float(rated_current_str)
        power_loss = (avg_resistance / 1000.0) * (rated_current ** 2)  # P = I²R

        # Update labels
        self.avg_resistance_label.setText(f"{avg_resistance:.1f} mΩ")
        self.quality_label.setText(quality_text)
        self.quality_label.setStyleSheet(f"color: {quality_color}; font-weight: bold;")
        self.max_drop_label.setText(f"{max_drop * 1000:.1f} mV")
        self.power_loss_label.setText(f"{power_loss:.2f} W @ {rated_current:.0f}A")

    def _get_quality_rating(self, resistance_mohm: float) -> tuple[str, str]:
        """Get quality rating based on resistance.

        Returns:
            Tuple of (quality_text, color)
        """
        if resistance_mohm < 200:
            return ("Excellent", "green")
        elif resistance_mohm < 300:
            return ("Good", "#90EE90")  # Light green
        elif resistance_mohm < 500:
            return ("Acceptable", "orange")
        elif resistance_mohm < 800:
            return ("Marginal", "#FF8C00")  # Dark orange
        else:
            return ("Fail", "red")

    def _clear_results_summary(self):
        """Clear the results summary display."""
        self.avg_resistance_label.setText("--")
        self.quality_label.setText("--")
        self.quality_label.setStyleSheet("")
        self.max_drop_label.setText("--")
        self.power_loss_label.setText("--")

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
        """Generate a test filename based on cable info and test conditions.

        Format: CableResistance_{CableName}_{SourceV}_{MinI}-{MaxI}_{NumSteps}-steps_{Timestamp}.json
        Example: CableResistance_Anker-PowerLine_5.0V_0.5-3.0A_5-steps_20260210_143022.json

        Note: Cable info doesn't have a dedicated manufacturer field, so manufacturer
        is typically part of the cable name (e.g., "Anker PowerLine USB-C").
        """
        import datetime
        cable_name = self.cable_name_edit.text().strip()
        if not cable_name:
            cable_name = "Cable"
        # Sanitize cable name
        safe_name = "".join(c if c.isalnum() or c in "-" else "-" for c in cable_name).strip("-")

        source_voltage = float(self.source_voltage_combo.currentText())
        min_current = self.min_current_spin.value()
        max_current = self.max_current_spin.value()
        num_steps = self.num_steps_spin.value()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = [
            "CableResistance",
            safe_name,
            f"{source_voltage}V",
            f"{min_current}-{max_current}A",
            f"{num_steps}-steps",
            timestamp,
        ]

        return "_".join(parts) + ".json"

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
        self.source_voltage_combo.currentTextChanged.connect(self._on_settings_changed)
        self.min_current_spin.valueChanged.connect(self._on_settings_changed)
        self.max_current_spin.valueChanged.connect(self._on_settings_changed)
        self.num_steps_spin.valueChanged.connect(self._on_settings_changed)
        self.dwell_time_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Cable Info fields
        self.cable_name_edit.textChanged.connect(self._on_settings_changed)
        self.cable_type_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.rated_current_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.cable_length_spin.valueChanged.connect(self._on_settings_changed)
        self.wire_gauge_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.notes_edit.textChanged.connect(self._on_settings_changed)
        self.cable_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Auto Save checkbox
        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self):
        """Handle any settings change - save to file."""
        if not self._loading_settings:
            self._save_session()

    def _save_session(self):
        """Save current settings to file."""
        cable_info = self._get_cable_info()
        cable_info["preset"] = self.cable_presets_combo.currentText()

        settings = {
            "test_config": {
                "source_voltage": self.source_voltage_combo.currentText(),
                "min_current": self.min_current_spin.value(),
                "max_current": self.max_current_spin.value(),
                "num_steps": self.num_steps_spin.value(),
                "dwell_time": self.dwell_time_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "cable_info": cable_info,
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
            if "source_voltage" in test_config:
                self.source_voltage_combo.setCurrentText(str(test_config["source_voltage"]))
            if "min_current" in test_config:
                self.min_current_spin.setValue(test_config["min_current"])
            if "max_current" in test_config:
                self.max_current_spin.setValue(test_config["max_current"])
            if "num_steps" in test_config:
                self.num_steps_spin.setValue(test_config["num_steps"])
            if "dwell_time" in test_config:
                self.dwell_time_spin.setValue(test_config["dwell_time"])

            # Load Cable Info
            cable_info = settings.get("cable_info", {})
            if cable_info:
                # First restore cable preset selection (before setting values)
                if "preset" in cable_info and cable_info["preset"]:
                    index = self.cable_presets_combo.findText(cable_info["preset"])
                    if index >= 0:
                        self.cable_presets_combo.blockSignals(True)
                        self.cable_presets_combo.setCurrentIndex(index)
                        self.cable_presets_combo.blockSignals(False)

                # Then set the cable info values
                self._set_cable_info(cable_info)

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
            Dictionary with source_voltage, min_current, max_current, num_steps, dwell_time
        """
        return {
            "source_voltage": float(self.source_voltage_combo.currentText()),
            "min_current": self.min_current_spin.value(),
            "max_current": self.max_current_spin.value(),
            "num_steps": self.num_steps_spin.value(),
            "dwell_time": self.dwell_time_spin.value(),
        }

    def get_cable_info(self) -> dict:
        """Get current cable info as a dictionary.

        Returns:
            Dictionary with cable information
        """
        return self._get_cable_info()

    def get_test_results(self) -> list:
        """Get test results.

        Returns:
            List of dicts with {current, voltage_measured, voltage_drop, resistance}
        """
        return self._test_results
