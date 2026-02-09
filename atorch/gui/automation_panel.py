"""Test automation panel."""

import json
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
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

    def __init__(self, test_runner: TestRunner, database: Database):
        super().__init__()

        self.test_runner = test_runner
        self.database = database
        self._current_profile: Optional[TestProfile] = None

        # Load default presets from resources directory
        self._default_battery_presets = self._load_default_battery_presets()
        self._default_test_presets = self._load_default_test_presets()

        # User presets directories
        self._battery_presets_dir = Path.home() / ".atorch" / "battery_presets"
        self._battery_presets_dir.mkdir(parents=True, exist_ok=True)
        self._test_presets_dir = Path.home() / ".atorch" / "test_presets"
        self._test_presets_dir.mkdir(parents=True, exist_ok=True)

        self._create_ui()

    def _load_default_battery_presets(self) -> dict:
        """Load default battery presets from the resources directory."""
        module_dir = Path(__file__).parent.parent.parent
        presets_file = module_dir / "resources" / "default_battery_presets.json"

        try:
            with open(presets_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_default_test_presets(self) -> dict:
        """Load default test presets from the resources directory."""
        module_dir = Path(__file__).parent.parent.parent
        presets_file = module_dir / "resources" / "default_test_presets.json"

        try:
            with open(presets_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _create_ui(self) -> None:
        """Create the automation panel UI."""
        layout = QHBoxLayout(self)

        # Left: Test configuration
        config_group = QGroupBox("Test Configuration")
        config_group.setMaximumWidth(320)
        config_layout = QVBoxLayout(config_group)

        # Test presets row (at top)
        test_presets_layout = QHBoxLayout()
        test_presets_layout.addWidget(QLabel("Presets:"))
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

        # Discharge type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Discharge Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["CC", "CP", "CR"])
        self.type_combo.setToolTip("CC = Constant Current\nCP = Constant Power\nCR = Constant Resistance")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        config_layout.addLayout(type_layout)

        # Parameters form
        self.params_form = QFormLayout()

        # Value spinbox (Current/Power/Resistance depending on type)
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 24.0)
        self.value_spin.setDecimals(3)
        self.value_spin.setSingleStep(0.1)
        self.value_spin.setValue(0.5)
        self.value_label = QLabel("Current (A):")
        self.value_label.setMinimumWidth(85)  # Fixed width to prevent layout jumping
        self.params_form.addRow(self.value_label, self.value_spin)

        # Voltage cutoff
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.0, 200.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.1)
        self.cutoff_spin.setValue(3.0)
        self.params_form.addRow("V Cutoff:", self.cutoff_spin)

        # Timed (optional duration limit)
        timed_layout = QHBoxLayout()
        self.timed_checkbox = QCheckBox()
        self.timed_checkbox.setChecked(False)
        self.timed_checkbox.setToolTip("Enable timed test with duration limit")
        self.timed_checkbox.toggled.connect(self._on_timed_toggled)
        timed_layout.addWidget(self.timed_checkbox)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 86400)
        self.duration_spin.setValue(3600)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setEnabled(False)
        self.duration_spin.setToolTip("Test duration in seconds")
        timed_layout.addWidget(self.duration_spin)
        self.params_form.addRow("Timed:", timed_layout)

        config_layout.addLayout(self.params_form)

        # Apply button
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        config_layout.addWidget(self.apply_btn)

        # Load test presets into dropdown
        self._load_test_presets_list()

        layout.addWidget(config_group)

        # Middle: Battery info
        info_group = QGroupBox("Battery Info")
        info_group.setFixedWidth(350)
        info_main_layout = QVBoxLayout(info_group)

        # Presets row
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets:"))
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
        info_layout.addRow("Name:", self.battery_name_edit)

        self.manufacturer_edit = QLineEdit()
        self.manufacturer_edit.setPlaceholderText("e.g., Samsung, LG, Panasonic")
        info_layout.addRow("Manufacturer:", self.manufacturer_edit)

        self.oem_equiv_edit = QLineEdit()
        self.oem_equiv_edit.setPlaceholderText("e.g., 30Q, VTC6")
        info_layout.addRow("OEM Equivalent:", self.oem_equiv_edit)

        self.rated_voltage_spin = QDoubleSpinBox()
        self.rated_voltage_spin.setRange(0.0, 100.0)
        self.rated_voltage_spin.setDecimals(2)
        self.rated_voltage_spin.setValue(3.7)
        self.rated_voltage_spin.setSuffix(" V")
        info_layout.addRow("Rated Voltage:", self.rated_voltage_spin)

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
        info_layout.addRow("Nominal Capacity:", capacity_layout)

        info_main_layout.addWidget(specs_group)

        # Sub-panel for Serial Number and Notes (outlined, no label)
        instance_group = QGroupBox()
        instance_layout = QFormLayout(instance_group)
        instance_layout.setContentsMargins(6, 6, 6, 6)

        self.serial_number_edit = QLineEdit()
        self.serial_number_edit.setPlaceholderText("e.g., SN123456")
        instance_layout.addRow("Serial Number:", self.serial_number_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(50)
        self.notes_edit.setPlaceholderText("Test notes...")
        instance_layout.addRow("Notes:", self.notes_edit)

        info_main_layout.addWidget(instance_group)
        layout.addWidget(info_group)

        # Load battery presets into dropdown
        self._load_battery_presets_list()

        # Right: Test control
        control_group = QGroupBox("Test Control")
        control_layout = QVBoxLayout(control_group)

        # Start/Stop button
        self.start_btn = QPushButton("Start Test")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self._on_start_clicked)
        control_layout.addWidget(self.start_btn)

        # Pause/Resume button
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        control_layout.addWidget(self.pause_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        control_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.status_label)

        # Elapsed time
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        font = self.elapsed_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.elapsed_label.setFont(font)
        control_layout.addWidget(self.elapsed_label)

        control_layout.addStretch()
        layout.addWidget(control_group)

    @Slot(bool)
    def _on_timed_toggled(self, checked: bool) -> None:
        """Handle timed checkbox toggle."""
        self.duration_spin.setEnabled(checked)

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
        """Handle start/stop button click."""
        if self.start_btn.text() == "Stop Test":
            # Stop test - this will be handled by main window turning off logging
            self._update_ui_stopped()
            # Emit with zeros to signal stop
            self.start_test_requested.emit(0, 0, 0, 0)
        else:
            # Check if device is connected
            if not self.test_runner or not self.test_runner.device or not self.test_runner.device.is_connected:
                QMessageBox.warning(
                    self,
                    "Not Connected",
                    "Please connect to the device first.",
                )
                return

            # Start test - emit signal with parameters
            discharge_type = self.type_combo.currentIndex()  # 0=CC, 1=CP, 2=CR
            value = self.value_spin.value()
            cutoff = self.cutoff_spin.value()
            duration = self.duration_spin.value() if self.timed_checkbox.isChecked() else 0

            self.start_test_requested.emit(discharge_type, value, cutoff, duration)
            self._update_ui_running()

    @Slot()
    def _on_pause_clicked(self) -> None:
        """Handle pause/resume button click - toggles between pause and resume."""
        if self.pause_btn.text() == "Pause":
            # Pause the test
            self.pause_btn.setText("Resume")
            self.pause_test_requested.emit()
        else:
            # Resume the test
            self.pause_btn.setText("Pause")
            self.resume_test_requested.emit()

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
        # Update status label
        self.status_label.setText(progress.message or progress.state.name)

        # Update elapsed time
        h = progress.elapsed_seconds // 3600
        m = (progress.elapsed_seconds % 3600) // 60
        s = progress.elapsed_seconds % 60
        self.elapsed_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

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
        self.start_btn.setText("Stop Test")
        self.pause_btn.setEnabled(True)
        self.type_combo.setEnabled(False)
        self.value_spin.setEnabled(False)
        self.cutoff_spin.setEnabled(False)
        self.timed_checkbox.setEnabled(False)
        self.duration_spin.setEnabled(False)

    def _update_ui_stopped(self) -> None:
        """Update UI for stopped state."""
        self.start_btn.setText("Start Test")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")  # Reset pause button text
        self.type_combo.setEnabled(True)
        self.value_spin.setEnabled(True)
        self.cutoff_spin.setEnabled(True)
        self.timed_checkbox.setEnabled(True)
        self.duration_spin.setEnabled(self.timed_checkbox.isChecked())
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")

    def _load_battery_presets_list(self) -> None:
        """Load the list of battery presets into the combo box."""
        self.presets_combo.clear()
        self.presets_combo.addItem("")  # Empty option

        # Add default presets section header
        if self._default_battery_presets:
            self.presets_combo.addItem("--- Default Presets ---")
            model = self.presets_combo.model()
            item = model.item(self.presets_combo.count() - 1)
            item.setEnabled(False)

            # Add default presets (sorted alphabetically)
            for preset_name in sorted(self._default_battery_presets.keys()):
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
        return name in self._default_battery_presets

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
            data = self._default_battery_presets[preset_name]
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
            self.test_presets_combo.addItem("--- Default Presets ---")
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
