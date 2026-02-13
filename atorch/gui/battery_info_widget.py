"""Reusable Battery Info widget for test panels."""

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QTextEdit, QDateEdit
)
from PySide6.QtCore import Signal, QDate


class BatteryInfoWidget(QGroupBox):
    """Reusable battery information widget with presets."""

    # Signal emitted when any battery info field changes
    settings_changed = Signal()

    def __init__(self, title: str = "Battery Info", fixed_width: int = 350):
        super().__init__(title)
        self.setFixedWidth(fixed_width)

        self._loading = False  # Flag to prevent signal emission during programmatic updates

        self._create_ui()

    def _create_ui(self):
        """Create the battery info UI."""
        info_main_layout = QVBoxLayout(self)

        # Presets row
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Presets"))
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
        info_layout.addRow("Name", self.battery_name_edit)

        self.manufacturer_edit = QLineEdit()
        self.manufacturer_edit.setPlaceholderText("e.g., Samsung, LG")
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

        # Sub-panel for Manufactured date and Notes (outlined, no label)
        instance_group = QGroupBox()
        instance_layout = QFormLayout(instance_group)
        instance_layout.setContentsMargins(6, 6, 6, 6)

        self.manufactured_date_edit = QDateEdit()
        self.manufactured_date_edit.setCalendarPopup(True)
        self.manufactured_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.manufactured_date_edit.setDate(QDate(2000, 1, 1))  # Start with minimum date
        self.manufactured_date_edit.setSpecialValueText(" ")  # Show blank when no date
        self.manufactured_date_edit.setMinimumDate(QDate(2000, 1, 1))
        self.manufactured_date_edit.setMaximumDate(QDate.currentDate())

        # Configure calendar for easy year navigation
        calendar = self.manufactured_date_edit.calendarWidget()
        if calendar:
            from PySide6.QtWidgets import QCalendarWidget
            calendar.setNavigationBarVisible(True)
            calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
            calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

        # Manufactured date and Serial Number on same row
        manuf_sn_layout = QHBoxLayout()
        manuf_sn_layout.addWidget(self.manufactured_date_edit)
        manuf_sn_layout.addWidget(QLabel("SN"))
        self.serial_number_edit = QLineEdit()
        self.serial_number_edit.setPlaceholderText("Serial #")
        manuf_sn_layout.addWidget(self.serial_number_edit)
        instance_layout.addRow("Manufactured", manuf_sn_layout)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(50)
        self.notes_edit.setPlaceholderText("Test notes...")
        instance_layout.addRow("Notes", self.notes_edit)

        info_main_layout.addWidget(instance_group)

        # Connect signals for change tracking
        self._connect_change_signals()

    def _connect_change_signals(self):
        """Connect all input widgets to emit settings_changed signal."""
        self.presets_combo.currentIndexChanged.connect(lambda: self._emit_changed())
        self.battery_name_edit.textChanged.connect(lambda: self._emit_changed())
        self.manufacturer_edit.textChanged.connect(lambda: self._emit_changed())
        self.serial_number_edit.textChanged.connect(lambda: self._emit_changed())
        self.oem_equiv_edit.textChanged.connect(lambda: self._emit_changed())
        self.manufactured_date_edit.dateChanged.connect(lambda: self._emit_changed())
        self.rated_voltage_spin.valueChanged.connect(lambda: self._emit_changed())
        self.technology_combo.currentIndexChanged.connect(lambda: self._emit_changed())
        self.nominal_capacity_spin.valueChanged.connect(lambda: self._emit_changed())
        self.nominal_energy_spin.valueChanged.connect(lambda: self._emit_changed())
        self.notes_edit.textChanged.connect(lambda: self._emit_changed())

    def _emit_changed(self):
        """Emit settings_changed signal if not currently loading."""
        if not self._loading:
            self.settings_changed.emit()

    def get_battery_info(self) -> dict:
        """Get battery info as a dictionary."""
        # Get manufactured date, return None if it's the minimum date (unset)
        manufactured_date = self.manufactured_date_edit.date()
        if manufactured_date == QDate(2000, 1, 1):
            manufactured_str = None
        else:
            manufactured_str = manufactured_date.toString("yyyy-MM-dd")

        return {
            "name": self.battery_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "serial_number": self.serial_number_edit.text(),
            "oem_equivalent": self.oem_equiv_edit.text(),
            "manufactured": manufactured_str,
            "rated_voltage": self.rated_voltage_spin.value(),
            "technology": self.technology_combo.currentText(),
            "nominal_capacity_mah": self.nominal_capacity_spin.value(),
            "nominal_energy_wh": self.nominal_energy_spin.value(),
            "notes": self.notes_edit.toPlainText(),
        }

    def set_battery_info(self, info: dict):
        """Set battery info from a dictionary.

        Args:
            info: Dictionary containing battery information
        """
        # Set loading flag to prevent signal emission
        was_loading = self._loading
        self._loading = True

        try:
            # Always set fields - use empty string if not in dict
            self.battery_name_edit.setText(info.get("name", ""))
            self.manufacturer_edit.setText(info.get("manufacturer", ""))
            self.serial_number_edit.setText(info.get("serial_number", ""))
            self.oem_equiv_edit.setText(info.get("oem_equivalent", ""))

            # Handle manufactured date
            if "manufactured" in info and info["manufactured"]:
                try:
                    date = QDate.fromString(info["manufactured"], "yyyy-MM-dd")
                    if date.isValid():
                        self.manufactured_date_edit.setDate(date)
                    else:
                        # Set to minimum date (unset)
                        self.manufactured_date_edit.setDate(QDate(2000, 1, 1))
                except:
                    self.manufactured_date_edit.setDate(QDate(2000, 1, 1))
            elif "serial_number" in info and info["serial_number"]:
                # Backwards compatibility: Try to parse old serial_number field as a date
                # (Old data used serial_number to store manufactured date)
                try:
                    # Try common date formats
                    for fmt in ["yyyy-MM-dd", "MM/dd/yyyy", "dd-MM-yyyy", "yyyyMMdd"]:
                        date = QDate.fromString(info["serial_number"], fmt)
                        if date.isValid():
                            self.manufactured_date_edit.setDate(date)
                            break
                    else:
                        # Couldn't parse as date, set to minimum (unset)
                        self.manufactured_date_edit.setDate(QDate(2000, 1, 1))
                except:
                    self.manufactured_date_edit.setDate(QDate(2000, 1, 1))
            else:
                # No date info, set to minimum (unset)
                self.manufactured_date_edit.setDate(QDate(2000, 1, 1))

            # Rated voltage - default to 3.7V if missing
            self.rated_voltage_spin.setValue(info.get("rated_voltage", 3.7))

            # Technology - default to Li-Ion (index 0) if missing
            if "technology" in info:
                index = self.technology_combo.findText(info["technology"])
                if index >= 0:
                    self.technology_combo.setCurrentIndex(index)
                else:
                    self.technology_combo.setCurrentIndex(0)  # Default to Li-Ion
            else:
                self.technology_combo.setCurrentIndex(0)  # Default to Li-Ion

            # Handle both formats for backwards compatibility with preset files
            # Default to 3000 mAh if missing
            if "nominal_capacity_mah" in info:
                self.nominal_capacity_spin.setValue(info["nominal_capacity_mah"])
            elif "nominal_capacity" in info:
                self.nominal_capacity_spin.setValue(info["nominal_capacity"])
            else:
                self.nominal_capacity_spin.setValue(3000)

            # Default to 11.1 Wh if missing
            if "nominal_energy_wh" in info:
                self.nominal_energy_spin.setValue(info["nominal_energy_wh"])
            elif "nominal_energy" in info:
                self.nominal_energy_spin.setValue(info["nominal_energy"])
            else:
                self.nominal_energy_spin.setValue(11.1)

            # Notes - clear if missing
            self.notes_edit.setPlainText(info.get("notes", ""))
        finally:
            self._loading = was_loading
