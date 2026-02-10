"""Battery Load test panel for stepped load testing."""

import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox
)
from PySide6.QtCore import Signal, Slot

from .battery_info_widget import BatteryInfoWidget


class BatteryLoadPanel(QWidget):
    """Panel for battery load testing with stepped current/power/resistance."""

    def __init__(self):
        super().__init__()

        # Load default battery presets from resources
        self._camera_battery_presets = self._load_presets_file("battery_capacity/presets_camera.json")
        self._household_battery_presets = self._load_presets_file("battery_capacity/presets_household.json")

        # Load default test presets
        self._default_test_presets = self._load_presets_file("battery_load/presets_test.json")

        # User presets directory
        self._atorch_dir = Path.home() / ".atorch"
        self._atorch_dir.mkdir(parents=True, exist_ok=True)
        self._battery_presets_dir = self._atorch_dir / "battery_presets"
        self._battery_presets_dir.mkdir(parents=True, exist_ok=True)
        self._test_presets_dir = self._atorch_dir / "battery_load_presets"
        self._test_presets_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self._atorch_dir / "battery_load_session.json"

        # Flag to prevent saving during load
        self._loading_settings = False

        self._create_ui()
        self._load_battery_presets_list()
        self._load_test_presets_list()
        self._connect_signals()
        self._connect_save_signals()
        self._load_session()

    def _create_ui(self):
        """Create the battery load panel UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Left: Test Conditions
        conditions_group = QGroupBox("Test Conditions")
        conditions_group.setFixedWidth(350)
        conditions_layout = QVBoxLayout(conditions_group)

        # Presets section
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets:"))
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

        # Load Type dropdown
        self.load_type_combo = QComboBox()
        self.load_type_combo.addItems(["Current", "Power", "Resistance"])
        self.load_type_combo.currentTextChanged.connect(self._on_load_type_changed)
        params_layout.addRow("Load Type:", self.load_type_combo)

        # Min value
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(0.0, 100000.0)
        self.min_spin.setDecimals(3)
        self.min_spin.setValue(10.0)
        self.min_spin.setSuffix(" mA")
        params_layout.addRow("Min:", self.min_spin)

        # Max value
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(0.0, 100000.0)
        self.max_spin.setDecimals(3)
        self.max_spin.setValue(100.0)
        self.max_spin.setSuffix(" mA")
        params_layout.addRow("Max:", self.max_spin)

        # Step value
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 10000.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setValue(10.0)
        self.step_spin.setSuffix(" mA")
        params_layout.addRow("Step:", self.step_spin)

        # Settle time
        self.settle_time_spin = QSpinBox()
        self.settle_time_spin.setRange(0, 3600)
        self.settle_time_spin.setValue(5)
        self.settle_time_spin.setSuffix(" s")
        params_layout.addRow("Settle Time:", self.settle_time_spin)

        conditions_layout.addWidget(params_group)
        conditions_layout.addStretch()

        layout.addWidget(conditions_group)

        # Middle: Battery Info (reusable widget)
        self.battery_info_widget = BatteryInfoWidget("Battery Info", 350)
        layout.addWidget(self.battery_info_widget)

        # Right: Test Control
        control_group = QGroupBox("Test Control")
        control_group.setFixedWidth(200)
        control_layout = QVBoxLayout(control_group)

        # Placeholder buttons for now (will be defined later)
        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)  # Disabled until implemented
        control_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)

        self.abort_btn = QPushButton("Abort")
        self.abort_btn.setEnabled(False)
        control_layout.addWidget(self.abort_btn)

        control_layout.addStretch()

        layout.addWidget(control_group)
        layout.addStretch()

    def _on_load_type_changed(self, load_type: str):
        """Update units based on selected load type."""
        if load_type == "Current":
            suffix = " mA"
            self.min_spin.setRange(0.0, 25000.0)
            self.max_spin.setRange(0.0, 25000.0)
            self.step_spin.setRange(0.001, 5000.0)
            # Reset to current defaults
            self.min_spin.setValue(10.0)
            self.max_spin.setValue(100.0)
            self.step_spin.setValue(10.0)
        elif load_type == "Power":
            suffix = " mW"
            self.min_spin.setRange(0.0, 100000.0)
            self.max_spin.setRange(0.0, 100000.0)
            self.step_spin.setRange(0.001, 10000.0)
            # Reset to power defaults
            self.min_spin.setValue(100.0)
            self.max_spin.setValue(1000.0)
            self.step_spin.setValue(100.0)
        elif load_type == "Resistance":
            suffix = " Ω"
            self.min_spin.setRange(0.1, 10000.0)
            self.max_spin.setRange(0.1, 10000.0)
            self.step_spin.setRange(0.1, 1000.0)
            # Reset to resistance defaults
            self.min_spin.setValue(1.0)
            self.max_spin.setValue(10.0)
            self.step_spin.setValue(1.0)

        self.min_spin.setSuffix(suffix)
        self.max_spin.setSuffix(suffix)
        self.step_spin.setSuffix(suffix)

    def _connect_signals(self):
        """Connect battery preset and test preset signals."""
        # Battery preset signals
        self.battery_info_widget.presets_combo.currentIndexChanged.connect(self._on_battery_preset_selected)
        self.battery_info_widget.save_preset_btn.clicked.connect(self._save_battery_preset)
        self.battery_info_widget.delete_preset_btn.clicked.connect(self._delete_battery_preset)

        # Test preset signals
        self.test_presets_combo.currentIndexChanged.connect(self._on_test_preset_selected)
        self.save_test_preset_btn.clicked.connect(self._save_test_preset)
        self.delete_test_preset_btn.clicked.connect(self._delete_test_preset)

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

    def _load_battery_presets_list(self):
        """Load battery presets into the combo box."""
        combo = self.battery_info_widget.presets_combo
        combo.clear()
        combo.addItem("")  # Empty option

        # Add Camera Presets section
        if self._camera_battery_presets:
            combo.addItem("─── Camera Batteries ───")
            combo.model().item(combo.count() - 1).setEnabled(False)  # Make separator unselectable
            for name in sorted(self._camera_battery_presets.keys()):
                combo.addItem(name)

        # Add Household Presets section
        if self._household_battery_presets:
            combo.addItem("─── Household Batteries ───")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for name in sorted(self._household_battery_presets.keys()):
                combo.addItem(name)

        # Add User Presets section
        user_presets = []
        if self._battery_presets_dir.exists():
            for preset_file in sorted(self._battery_presets_dir.glob("*.json")):
                user_presets.append(preset_file.stem)

        if user_presets:
            combo.addItem("─── My Batteries ───")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for name in user_presets:
                combo.addItem(name)

    def _on_battery_preset_selected(self, index: int):
        """Handle battery preset selection."""
        # Skip if we're loading settings from session file
        if self._loading_settings:
            return

        combo = self.battery_info_widget.presets_combo
        preset_name = combo.currentText()

        # Check if it's a separator
        if "───" in preset_name or not preset_name:
            self.battery_info_widget.delete_preset_btn.setEnabled(False)
            return

        # Check if it's a user preset (enable delete button)
        preset_file = self._battery_presets_dir / f"{preset_name}.json"
        self.battery_info_widget.delete_preset_btn.setEnabled(preset_file.exists())

        # Load preset data
        preset_data = None
        if preset_name in self._camera_battery_presets:
            preset_data = self._camera_battery_presets[preset_name]
        elif preset_name in self._household_battery_presets:
            preset_data = self._household_battery_presets[preset_name]
        elif preset_file.exists():
            try:
                with open(preset_file, 'r') as f:
                    preset_data = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load preset: {e}")
                return

        if preset_data:
            self.battery_info_widget.set_battery_info(preset_data)

    def _save_battery_preset(self):
        """Save current battery info as a preset."""
        from PySide6.QtWidgets import QInputDialog

        name = self.battery_info_widget.battery_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Save Preset", "Please enter a battery name first.")
            return

        # Ask for preset name (default to battery name)
        preset_name, ok = QInputDialog.getText(
            self, "Save Battery Preset",
            "Preset name:", text=name
        )

        if not ok or not preset_name:
            return

        # Save preset
        data = self.battery_info_widget.get_battery_info()
        safe_name = "".join(c for c in preset_name if c.isalnum() or c in (' ', '-', '_')).strip()

        preset_file = self._battery_presets_dir / f"{safe_name}.json"
        try:
            with open(preset_file, 'w') as f:
                json.dump(data, f, indent=2)
            self._load_battery_presets_list()
            # Select the newly saved preset
            index = self.battery_info_widget.presets_combo.findText(safe_name)
            if index >= 0:
                self.battery_info_widget.presets_combo.setCurrentIndex(index)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save preset: {e}")

    def _delete_battery_preset(self):
        """Delete the selected user battery preset."""
        preset_name = self.battery_info_widget.presets_combo.currentText()
        if not preset_name or "───" in preset_name:
            return

        preset_file = self._battery_presets_dir / f"{preset_name}.json"
        if not preset_file.exists():
            QMessageBox.warning(self, "Delete Preset", "Cannot delete built-in presets.")
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete battery preset '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                preset_file.unlink()
                self._load_battery_presets_list()
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
            load_type = preset_data.get("load_type", "Current")
            self.load_type_combo.setCurrentText(load_type)
            self.min_spin.setValue(preset_data.get("min", 10.0))
            self.max_spin.setValue(preset_data.get("max", 100.0))
            self.step_spin.setValue(preset_data.get("step", 10.0))
            self.settle_time_spin.setValue(preset_data.get("settle_time", 5))

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
            "load_type": self.load_type_combo.currentText(),
            "min": self.min_spin.value(),
            "max": self.max_spin.value(),
            "step": self.step_spin.value(),
            "settle_time": self.settle_time_spin.value()
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

    def _connect_save_signals(self):
        """Connect all form fields to save settings when changed."""
        # Test Conditions fields
        self.load_type_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.min_spin.valueChanged.connect(self._on_settings_changed)
        self.max_spin.valueChanged.connect(self._on_settings_changed)
        self.step_spin.valueChanged.connect(self._on_settings_changed)
        self.settle_time_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Battery Info fields (via widget signal)
        self.battery_info_widget.settings_changed.connect(self._on_settings_changed)

    @Slot()
    def _on_settings_changed(self):
        """Handle any settings change - save to file."""
        if not self._loading_settings:
            self._save_session()

    def _save_session(self):
        """Save current settings to file."""
        battery_info = self.battery_info_widget.get_battery_info()
        battery_info["preset"] = self.battery_info_widget.presets_combo.currentText()

        settings = {
            "test_config": {
                "load_type": self.load_type_combo.currentText(),
                "min": self.min_spin.value(),
                "max": self.max_spin.value(),
                "step": self.step_spin.value(),
                "settle_time": self.settle_time_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "battery_info": battery_info,
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
            if "load_type" in test_config:
                self.load_type_combo.setCurrentText(test_config["load_type"])
            if "min" in test_config:
                self.min_spin.setValue(test_config["min"])
            if "max" in test_config:
                self.max_spin.setValue(test_config["max"])
            if "step" in test_config:
                self.step_spin.setValue(test_config["step"])
            if "settle_time" in test_config:
                self.settle_time_spin.setValue(test_config["settle_time"])

            # Load Battery Info
            battery_info = settings.get("battery_info", {})
            if battery_info:
                # First restore battery preset selection (before setting values)
                if "preset" in battery_info and battery_info["preset"]:
                    index = self.battery_info_widget.presets_combo.findText(battery_info["preset"])
                    if index >= 0:
                        self.battery_info_widget.presets_combo.blockSignals(True)
                        self.battery_info_widget.presets_combo.setCurrentIndex(index)
                        self.battery_info_widget.presets_combo.blockSignals(False)

                # Then set the battery info values
                self.battery_info_widget.set_battery_info(battery_info)

        finally:
            self._loading_settings = False
