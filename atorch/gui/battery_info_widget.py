"""Reusable Battery Info widget for test panels."""

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QTextEdit
)
from PySide6.QtCore import Signal


class BatteryInfoWidget(QGroupBox):
    """Reusable battery information widget with presets."""

    # Signal emitted when any battery info field changes
    settings_changed = Signal()

    def __init__(self, title: str = "Battery Info", fixed_width: int = 350):
        super().__init__(title)
        self.setFixedWidth(fixed_width)

        self._create_ui()

    def _create_ui(self):
        """Create the battery info UI."""
        info_main_layout = QVBoxLayout(self)

        # Presets row
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets:"))
        self.presets_combo = QComboBox()
        self.presets_combo.setSizePolicy(
            self.presets_combo.sizePolicy().horizontalPolicy(),
            self.presets_combo.sizePolicy().verticalPolicy()
        )
        presets_layout.addWidget(self.presets_combo, 1)  # Stretch to fill

        self.save_preset_btn = QPushButton("Save")
        self.save_preset_btn.setMaximumWidth(50)
        presets_layout.addWidget(self.save_preset_btn)

        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.setMaximumWidth(50)
        self.delete_preset_btn.setEnabled(False)
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
        info_layout.addRow("Rated Voltage:", voltage_tech_layout)

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

        # Connect signals for change tracking
        self._connect_change_signals()

    def _connect_change_signals(self):
        """Connect all input widgets to emit settings_changed signal."""
        self.battery_name_edit.textChanged.connect(lambda: self.settings_changed.emit())
        self.manufacturer_edit.textChanged.connect(lambda: self.settings_changed.emit())
        self.oem_equiv_edit.textChanged.connect(lambda: self.settings_changed.emit())
        self.serial_number_edit.textChanged.connect(lambda: self.settings_changed.emit())
        self.rated_voltage_spin.valueChanged.connect(lambda: self.settings_changed.emit())
        self.technology_combo.currentIndexChanged.connect(lambda: self.settings_changed.emit())
        self.nominal_capacity_spin.valueChanged.connect(lambda: self.settings_changed.emit())
        self.nominal_energy_spin.valueChanged.connect(lambda: self.settings_changed.emit())
        self.notes_edit.textChanged.connect(lambda: self.settings_changed.emit())

    def get_battery_info(self) -> dict:
        """Get battery info as a dictionary."""
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

    def set_battery_info(self, info: dict):
        """Set battery info from a dictionary."""
        if "name" in info:
            self.battery_name_edit.setText(info["name"])
        if "manufacturer" in info:
            self.manufacturer_edit.setText(info["manufacturer"])
        if "oem_equivalent" in info:
            self.oem_equiv_edit.setText(info["oem_equivalent"])
        if "serial_number" in info:
            self.serial_number_edit.setText(info["serial_number"])
        if "rated_voltage" in info:
            self.rated_voltage_spin.setValue(info["rated_voltage"])
        if "technology" in info:
            index = self.technology_combo.findText(info["technology"])
            if index >= 0:
                self.technology_combo.setCurrentIndex(index)
        # Handle both formats for backwards compatibility with preset files
        if "nominal_capacity_mah" in info:
            self.nominal_capacity_spin.setValue(info["nominal_capacity_mah"])
        elif "nominal_capacity" in info:
            self.nominal_capacity_spin.setValue(info["nominal_capacity"])

        if "nominal_energy_wh" in info:
            self.nominal_energy_spin.setValue(info["nominal_energy_wh"])
        elif "nominal_energy" in info:
            self.nominal_energy_spin.setValue(info["nominal_energy"])
        if "notes" in info:
            self.notes_edit.setPlainText(info["notes"])
