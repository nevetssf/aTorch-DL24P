"""Battery Load test panel for stepped load testing."""

import json
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QFormLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QProgressBar, QCheckBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Signal, Slot, QTimer, Qt

from .battery_info_widget import BatteryInfoWidget


class BatteryLoadPanel(QWidget):
    """Panel for battery load testing with stepped current/power/resistance."""

    # Signals
    manual_save_requested = Signal(str)  # filename
    session_loaded = Signal(list)  # readings
    export_csv_requested = Signal()
    test_started = Signal()  # Emitted when test starts
    test_stopped = Signal()  # Emitted when test stops (complete or aborted)

    def __init__(self):
        super().__init__()

        # Load default battery presets from resources
        self._camera_battery_presets = self._load_presets_file("battery_capacity/presets_camera.json")
        self._household_battery_presets = self._load_presets_file("battery_capacity/presets_household.json")

        # Load default test presets
        self._default_test_presets = self._load_presets_file("battery_load/presets_test.json")

        # User presets directory
        from ..config import get_data_dir
        self._atorch_dir = get_data_dir()
        self._battery_presets_dir = self._atorch_dir / "presets" / "battery_presets"
        self._test_presets_dir = self._atorch_dir / "presets" / "battery_load_presets"
        self._session_file = self._atorch_dir / "sessions" / "battery_load_session.json"

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
        self._load_battery_presets_list()
        self._load_test_presets_list()
        self._connect_signals()
        self._connect_save_signals()
        self._load_session()
        self._update_filename()  # Initialize filename after loading settings

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

        # Load Type dropdown
        self.load_type_combo = QComboBox()
        self.load_type_combo.addItems(["Current", "Resistance"])
        self.load_type_combo.currentTextChanged.connect(self._on_load_type_changed)
        self.load_type_combo.currentTextChanged.connect(lambda: self._update_filename())
        params_layout.addRow("Load Type", self.load_type_combo)

        # Start, End, Steps on one row
        range_layout = QHBoxLayout()

        range_layout.addWidget(QLabel("Start"))
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(0.0, 25.0)
        self.min_spin.setDecimals(2)
        self.min_spin.setSingleStep(0.1)
        self.min_spin.setValue(0.0)
        self.min_spin.setSuffix(" A")
        self.min_spin.valueChanged.connect(lambda: self._update_filename())
        range_layout.addWidget(self.min_spin)

        range_layout.addWidget(QLabel("End"))
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(0.0, 25.0)
        self.max_spin.setDecimals(2)
        self.max_spin.setSingleStep(0.1)
        self.max_spin.setValue(0.10)
        self.max_spin.setSuffix(" A")
        self.max_spin.valueChanged.connect(lambda: self._update_filename())
        range_layout.addWidget(self.max_spin)

        range_layout.addWidget(QLabel("Steps"))
        self.num_steps_spin = QSpinBox()
        self.num_steps_spin.setRange(1, 999)
        self.num_steps_spin.setValue(10)
        self.num_steps_spin.valueChanged.connect(lambda: self._update_filename())
        range_layout.addWidget(self.num_steps_spin)

        params_layout.addRow(range_layout)

        # Dwell time and V Cutoff on one row
        dwell_cutoff_layout = QHBoxLayout()

        self.dwell_time_spin = QSpinBox()
        self.dwell_time_spin.setRange(0, 3600)
        self.dwell_time_spin.setValue(5)
        self.dwell_time_spin.setSuffix(" s")
        dwell_cutoff_layout.addWidget(self.dwell_time_spin)

        dwell_cutoff_layout.addWidget(QLabel("V Cutoff"))

        self.v_cutoff_spin = QDoubleSpinBox()
        self.v_cutoff_spin.setRange(0.0, 60.0)
        self.v_cutoff_spin.setDecimals(2)
        self.v_cutoff_spin.setValue(3.0)
        self.v_cutoff_spin.setSuffix(" V")
        dwell_cutoff_layout.addWidget(self.v_cutoff_spin)

        params_layout.addRow("Dwell Time", dwell_cutoff_layout)

        conditions_layout.addWidget(params_group)
        conditions_layout.addStretch()

        layout.addWidget(conditions_group)

        # Middle: Battery Info (reusable widget)
        self.battery_info_widget = BatteryInfoWidget("Battery Info", 350)
        layout.addWidget(self.battery_info_widget)

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

        # Reduce spacing before Test Summary
        control_layout.addSpacing(-5)

        # Test Summary table
        summary_group = QGroupBox("Test Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(6, 0, 6, 6)

        self.summary_table = QTableWidget(1, 5)
        self.summary_table.setHorizontalHeaderLabels(["Run Time", "Load Type", "Load Range", "Resistance", "R²"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.NoSelection)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Set all columns to stretch equally
        header = self.summary_table.horizontalHeader()
        for col in range(5):
            header.setSectionResizeMode(col, QHeaderView.Stretch)

        # Make the single row taller
        self.summary_table.setRowHeight(0, 35)

        # Create value items (store references for updates)
        self.summary_runtime_item = QTableWidgetItem("--")
        self.summary_loadtype_item = QTableWidgetItem("--")
        self.summary_loadrange_item = QTableWidgetItem("--")
        self.summary_resistance_item = QTableWidgetItem("--")
        self.summary_rsquared_item = QTableWidgetItem("--")

        # Center align all values
        for item in [self.summary_runtime_item, self.summary_loadtype_item,
                     self.summary_loadrange_item, self.summary_resistance_item,
                     self.summary_rsquared_item]:
            item.setTextAlignment(Qt.AlignCenter)

        self.summary_table.setItem(0, 0, self.summary_runtime_item)
        self.summary_table.setItem(0, 1, self.summary_loadtype_item)
        self.summary_table.setItem(0, 2, self.summary_loadrange_item)
        self.summary_table.setItem(0, 3, self.summary_resistance_item)
        self.summary_table.setItem(0, 4, self.summary_rsquared_item)

        # Set fixed height to prevent scrolling
        table_height = self.summary_table.horizontalHeader().height() + self.summary_table.rowHeight(0) + 2
        self.summary_table.setFixedHeight(table_height)

        summary_layout.addWidget(self.summary_table)
        control_layout.addWidget(summary_group)

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

    def _on_load_type_changed(self, load_type: str):
        """Update units based on selected load type."""
        if load_type == "Current":
            suffix = " A"
            self.min_spin.setRange(0.0, 25.0)
            self.max_spin.setRange(0.0, 25.0)
            self.min_spin.setValue(0.0)
            self.max_spin.setValue(0.10)
        elif load_type == "Resistance":
            suffix = " Ω"
            self.min_spin.setRange(0.1, 10000.0)
            self.max_spin.setRange(0.1, 10000.0)
            self.min_spin.setValue(1.0)
            self.max_spin.setValue(10.0)

        self.min_spin.setSuffix(suffix)
        self.max_spin.setSuffix(suffix)

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
            # Trigger sync to automation panel after preset load
            self.battery_info_widget.settings_changed.emit()

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
            # Emit signal so other panels can reload their preset lists
            self.battery_info_widget.preset_list_changed.emit()
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
                # Emit signal so other panels can reload their preset lists
                self.battery_info_widget.preset_list_changed.emit()
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
            self.min_spin.setValue(float(preset_data.get("min", 0)))
            self.max_spin.setValue(float(preset_data.get("max", 0.1)))
            self.num_steps_spin.setValue(preset_data.get("num_steps", 10))
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
            "load_type": self.load_type_combo.currentText(),
            "min": self.min_spin.value(),
            "max": self.max_spin.value(),
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
        """Start the stepped load test."""
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

        # Update filename if autosave is enabled
        if self.autosave_checkbox.isChecked():
            self._update_filename()

        # Get test parameters
        load_type = self.load_type_combo.currentText()
        min_val = self.min_spin.value()
        max_val = self.max_spin.value()
        num_divisions = self.num_steps_spin.value()
        dwell_time = self.dwell_time_spin.value()
        v_cutoff = self.v_cutoff_spin.value()

        # Validate parameters
        if min_val >= max_val:
            QMessageBox.warning(self, "Invalid Parameters", "Min must be less than Max.")
            return
        if num_divisions < 1:
            QMessageBox.warning(self, "Invalid Parameters", "Divisions must be at least 1.")
            return

        # Emit signal that test is starting (triggers logging in main window)
        self.test_started.emit()

        # Calculate actual number of steps (divisions + 1)
        self._total_steps = num_divisions + 1
        self._step_size = (max_val - min_val) / num_divisions
        self._current_step = 0
        self._current_value = min_val

        # Set device mode
        mode_map = {"Current": 0, "Resistance": 3}  # CC=0, CR=3
        mode = mode_map.get(load_type, 0)

        try:
            # Switch device to the correct mode first
            self._device.set_mode(mode)

            # Set voltage cutoff
            self._device.set_voltage_cutoff(v_cutoff)

            # Set initial value
            if load_type == "Current":
                self._device.set_current(min_val)  # Already in A
            elif load_type == "Resistance":
                self._device.set_resistance(min_val)  # Ohms

            # Turn on load
            self._device.turn_on()

        except Exception as e:
            QMessageBox.critical(self, "Device Error", f"Failed to configure device: {e}")
            return

        # Switch plot to show Load Type vs Voltage
        if self._plot_panel:
            x_axis_name = {"Current": "Current", "Resistance": "R Load"}
            self._plot_panel.x_axis_combo.setCurrentText(x_axis_name.get(load_type, "Current"))
            # Enable Voltage on Y-axis
            if "Y" in self._plot_panel._axis_dropdowns:
                self._plot_panel._axis_dropdowns["Y"].setCurrentText("Voltage")
                self._plot_panel._axis_checkboxes["Y"].setChecked(True)

        # Update UI
        self.start_btn.setText("Abort")
        self.status_label.setText(f"Step 1/{self._total_steps}: {min_val:.3f}")
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
        load_turned_off = False
        if self._device and self._device.is_connected:
            try:
                load_turned_off = self._device.turn_off()
                if not load_turned_off:
                    print("Warning: device.turn_off() returned False")
            except Exception as e:
                print(f"Error turning off load during abort: {e}")

        # Always finish the test, even if turn_off failed
        status = "Test Aborted"
        if not load_turned_off and self._device and self._device.is_connected:
            status = "Test Aborted (manually turn off load)"
        self._finish_test(status)

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

        # Calculate next value
        self._current_value = self.min_spin.value() + (self._current_step * self._step_size)

        # Set new load value
        load_type = self.load_type_combo.currentText()
        try:
            if load_type == "Current":
                self._device.set_current(self._current_value)  # Already in A
            elif load_type == "Resistance":
                self._device.set_resistance(self._current_value)  # Ohms
        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Device Error", f"Failed to set load: {e}")
            self._abort_test()
            return

        # Update UI
        progress = int((self._current_step / self._total_steps) * 100)
        self.progress_bar.setValue(progress)
        self.status_label.setText(f"Step {self._current_step + 1}/{self._total_steps}: {self._current_value:.3f}")
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
        self.start_btn.setEnabled(True)  # Re-enable the button
        self._test_running = False

        # Show status message briefly, then revert to normal status
        if not self.status_label.text().startswith("Error") and not self.status_label.text().startswith("Connection Lost"):
            self.status_label.setText(status)
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # After 2 seconds, revert to normal status based on connection state
            QTimer.singleShot(2000, self._restore_normal_status)

        self.progress_bar.setValue(100)
        self._update_test_time()

    def _restore_normal_status(self):
        """Restore status label to normal state based on connection."""
        if not self._test_running:  # Only restore if test is still not running
            if self._device and self._device.is_connected:
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.status_label.setText("Not Connected")
                self.status_label.setStyleSheet("color: red;")

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all input widgets during test."""
        self.test_presets_combo.setEnabled(enabled)
        self.save_test_preset_btn.setEnabled(enabled)
        self.delete_test_preset_btn.setEnabled(enabled)
        self.load_type_combo.setEnabled(enabled)
        self.min_spin.setEnabled(enabled)
        self.max_spin.setEnabled(enabled)
        self.num_steps_spin.setEnabled(enabled)
        self.dwell_time_spin.setEnabled(enabled)
        self.v_cutoff_spin.setEnabled(enabled)
        self.battery_info_widget.set_inputs_enabled(enabled)
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

    def reload_battery_presets(self) -> None:
        """Reload battery presets list (called when another panel saves/deletes a preset)."""
        self._load_battery_presets_list()

    def generate_test_filename(self) -> str:
        """Generate a test filename based on battery info and test conditions.

        Format: BatteryLoad_{Manufacturer}_{BatteryName}_{LoadType}_{MinValue}-{MaxValue}_{NumSteps}-steps_{Timestamp}.json
        Example: BatteryLoad_Canon_LP-E6_Current_0.5-3.0A_10-steps_20260210_143022.json
        """
        import datetime
        manufacturer = self.battery_info_widget.manufacturer_edit.text().strip() or "Unknown"
        battery_name = self.battery_info_widget.battery_name_edit.text().strip()
        if not battery_name:
            battery_name = "Battery"
        # Sanitize manufacturer and battery name
        safe_manufacturer = "".join(c if c.isalnum() or c in "-" else "-" for c in manufacturer).strip("-")
        safe_name = "".join(c if c.isalnum() or c in "-" else "-" for c in battery_name).strip("-")

        load_type = self.load_type_combo.currentText()
        min_value = self.min_spin.value()
        max_value = self.max_spin.value()
        num_steps = self.num_steps_spin.value()

        # Get unit for load type
        unit_map = {"Current": "A", "Resistance": "ohm"}
        unit = unit_map.get(load_type, "")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = [
            "BatteryLoad",
            safe_name,
            load_type,
            f"{min_value}-{max_value}{unit}",
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
            # Set loading flag to prevent filename auto-update
            self._loading_settings = True
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Update filename to show loaded file
                self.filename_edit.setText(Path(file_path).name)

                # Load test config
                test_config = data.get("test_config", {})
                if "load_type" in test_config:
                    self.load_type_combo.setCurrentText(test_config["load_type"])
                if "min" in test_config:
                    self.min_spin.setValue(test_config["min"])
                if "max" in test_config:
                    self.max_spin.setValue(test_config["max"])

                # Emit readings for display
                readings = data.get("readings", [])
                if readings:
                    self.session_loaded.emit(readings)

                    # Update Test Summary from loaded data
                    self._update_summary_from_loaded_data(data, file_path)

            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load file: {e}")
            finally:
                self._loading_settings = False

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
        self.load_type_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.min_spin.valueChanged.connect(self._on_settings_changed)
        self.max_spin.valueChanged.connect(self._on_settings_changed)
        self.num_steps_spin.valueChanged.connect(self._on_settings_changed)
        self.dwell_time_spin.valueChanged.connect(self._on_settings_changed)
        self.v_cutoff_spin.valueChanged.connect(self._on_settings_changed)
        self.test_presets_combo.currentIndexChanged.connect(self._on_settings_changed)

        # Battery Info fields (via widget signal)
        self.battery_info_widget.settings_changed.connect(self._on_settings_changed)
        self.battery_info_widget.settings_changed.connect(lambda: self._update_filename())

        # Auto Save checkbox
        self.autosave_checkbox.toggled.connect(self._on_settings_changed)

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
                "num_steps": self.num_steps_spin.value(),
                "dwell_time": self.dwell_time_spin.value(),
                "v_cutoff": self.v_cutoff_spin.value(),
                "preset": self.test_presets_combo.currentText(),
            },
            "battery_info": battery_info,
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
            if "load_type" in test_config:
                self.load_type_combo.setCurrentText(test_config["load_type"])
            if "min" in test_config:
                self.min_spin.setValue(test_config["min"])
            if "max" in test_config:
                self.max_spin.setValue(test_config["max"])
            if "num_steps" in test_config:
                self.num_steps_spin.setValue(test_config["num_steps"])
            if "dwell_time" in test_config:
                self.dwell_time_spin.setValue(test_config["dwell_time"])
            if "v_cutoff" in test_config:
                self.v_cutoff_spin.setValue(test_config["v_cutoff"])

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
            Dictionary with load_type, min, max, num_steps (divisions), dwell_time, voltage_cutoff
        """
        return {
            "load_type": self.load_type_combo.currentText(),
            "min": self.min_spin.value(),
            "max": self.max_spin.value(),
            "num_steps": self.num_steps_spin.value(),  # Now represents divisions (actual steps = divisions + 1)
            "dwell_time": self.dwell_time_spin.value(),
            "voltage_cutoff": self.v_cutoff_spin.value(),
        }

    def get_battery_info(self) -> dict:
        """Get current battery info as a dictionary.

        Returns:
            Dictionary with battery information
        """
        return self.battery_info_widget.get_battery_info()

    def update_test_summary(self, runtime_s: int, load_type: str, min_val: float, max_val: float,
                           resistance_ohm: float = None, r_squared: float = None):
        """Update the test summary table with results.

        Args:
            runtime_s: Test runtime in seconds
            load_type: Type of load test (Current/Power/Resistance)
            min_val: Minimum load value
            max_val: Maximum load value
            resistance_ohm: Calculated battery resistance (optional)
            r_squared: R-squared value of fit (optional)
        """
        # Format runtime
        hours = int(runtime_s // 3600)
        minutes = int((runtime_s % 3600) // 60)
        seconds = int(runtime_s % 60)
        runtime_str = f"{hours}h {minutes}m {seconds}s"
        self.summary_runtime_item.setText(runtime_str)

        # Load type
        self.summary_loadtype_item.setText(load_type)

        # Load range with units
        unit_map = {"Current": "A", "Resistance": "Ω"}
        unit = unit_map.get(load_type, "")
        load_range_str = f"{min_val:.3f}-{max_val:.3f} {unit}"
        self.summary_loadrange_item.setText(load_range_str)

        # Resistance
        if resistance_ohm is not None:
            self.summary_resistance_item.setText(f"{resistance_ohm:.3f} Ω")
        else:
            self.summary_resistance_item.setText("--")

        # R-squared
        if r_squared is not None:
            self.summary_rsquared_item.setText(f"{r_squared:.4f}")
        else:
            self.summary_rsquared_item.setText("--")

    def _update_summary_from_loaded_data(self, data: dict, file_path: str):
        """Calculate and update Test Summary from loaded JSON data.

        Args:
            data: Parsed JSON data dictionary
            file_path: Path to the JSON file (for updating if needed)
        """
        try:
            summary = data.get("summary", {})
            test_config = data.get("test_config", {})
            readings = data.get("readings", [])

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

            self.update_test_summary(
                runtime_s=runtime_s,
                load_type=test_config.get("load_type", "Current"),
                min_val=test_config.get("min", 0),
                max_val=test_config.get("max", 0),
                resistance_ohm=resistance_ohm,
                r_squared=r_squared
            )
        except Exception as e:
            print(f"Warning: Could not update Test Summary: {e}")
