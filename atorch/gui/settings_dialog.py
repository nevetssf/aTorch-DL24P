"""Settings dialog for application configuration."""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QFormLayout,
    QTabWidget,
    QWidget,
)
from PySide6.QtCore import Qt

from ..alerts.notifier import Notifier
from ..alerts.conditions import VoltageAlert, TemperatureAlert


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, notifier: Notifier, parent=None):
        super().__init__(parent)

        self.notifier = notifier

        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        self._create_ui()
        self._load_settings()

    def _create_ui(self) -> None:
        """Create the settings dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget
        tabs = QTabWidget()

        # Alerts tab
        alerts_tab = QWidget()
        alerts_layout = QVBoxLayout(alerts_tab)

        # Notification settings
        notif_group = QGroupBox("Notifications")
        notif_layout = QVBoxLayout(notif_group)

        self.desktop_check = QCheckBox("Desktop notifications")
        self.desktop_check.setChecked(self.notifier.desktop_enabled)
        notif_layout.addWidget(self.desktop_check)

        self.sound_check = QCheckBox("Sound alerts")
        self.sound_check.setChecked(self.notifier.sound_enabled)
        notif_layout.addWidget(self.sound_check)

        alerts_layout.addWidget(notif_group)

        # Voltage alert settings
        voltage_group = QGroupBox("Low Voltage Alert")
        voltage_layout = QFormLayout(voltage_group)

        self.voltage_enabled_check = QCheckBox("Enable")
        voltage_layout.addRow("", self.voltage_enabled_check)

        self.voltage_threshold_spin = QDoubleSpinBox()
        self.voltage_threshold_spin.setRange(0.0, 200.0)
        self.voltage_threshold_spin.setDecimals(2)
        self.voltage_threshold_spin.setValue(3.0)
        self.voltage_threshold_spin.setSuffix(" V")
        voltage_layout.addRow("Threshold:", self.voltage_threshold_spin)

        alerts_layout.addWidget(voltage_group)

        # Temperature alert settings
        temp_group = QGroupBox("Temperature Alert")
        temp_layout = QFormLayout(temp_group)

        self.temp_enabled_check = QCheckBox("Enable")
        self.temp_enabled_check.setChecked(True)
        temp_layout.addRow("", self.temp_enabled_check)

        self.temp_threshold_spin = QSpinBox()
        self.temp_threshold_spin.setRange(0, 150)
        self.temp_threshold_spin.setValue(70)
        self.temp_threshold_spin.setSuffix(" °C")
        temp_layout.addRow("Threshold:", self.temp_threshold_spin)

        self.temp_external_check = QCheckBox("Use external probe")
        temp_layout.addRow("", self.temp_external_check)

        alerts_layout.addWidget(temp_group)

        alerts_layout.addStretch()
        tabs.addTab(alerts_tab, "Alerts")

        # Display tab
        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)

        plot_group = QGroupBox("Plot Settings")
        plot_layout = QFormLayout(plot_group)

        self.max_points_spin = QSpinBox()
        self.max_points_spin.setRange(60, 36000)
        self.max_points_spin.setValue(3600)
        self.max_points_spin.setSuffix(" points")
        plot_layout.addRow("Max data points:", self.max_points_spin)

        display_layout.addWidget(plot_group)
        display_layout.addStretch()
        tabs.addTab(display_tab, "Display")

        layout.addWidget(tabs)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._save_and_accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

    def _load_settings(self) -> None:
        """Load current settings into UI."""
        self.desktop_check.setChecked(self.notifier.desktop_enabled)
        self.sound_check.setChecked(self.notifier.sound_enabled)

        # Find existing voltage/temperature alerts
        for condition in self.notifier._conditions:
            if isinstance(condition, VoltageAlert):
                self.voltage_enabled_check.setChecked(True)
                self.voltage_threshold_spin.setValue(condition.threshold)
            elif isinstance(condition, TemperatureAlert):
                self.temp_enabled_check.setChecked(True)
                self.temp_threshold_spin.setValue(condition.threshold)
                self.temp_external_check.setChecked(condition.use_external)

    def _save_and_accept(self) -> None:
        """Save settings and close dialog."""
        # Apply notification settings
        self.notifier.desktop_enabled = self.desktop_check.isChecked()
        self.notifier.sound_enabled = self.sound_check.isChecked()

        # Rebuild alert conditions
        from ..alerts.conditions import TestCompleteAlert

        self.notifier.clear_conditions()

        if self.voltage_enabled_check.isChecked():
            self.notifier.add_condition(
                VoltageAlert(threshold=self.voltage_threshold_spin.value())
            )

        if self.temp_enabled_check.isChecked():
            self.notifier.add_condition(
                TemperatureAlert(
                    threshold=self.temp_threshold_spin.value(),
                    use_external=self.temp_external_check.isChecked(),
                )
            )

        # Always add test complete alert
        self.notifier.add_condition(TestCompleteAlert())

        self.accept()


class DeviceSettingsDialog(QDialog):
    """Dialog for device settings (brightness, standby, etc.)."""

    def __init__(self, device, parent=None):
        super().__init__(parent)
        self.device = device

        self.setWindowTitle("Device Settings")
        self.setMinimumWidth(300)

        self._create_ui()

    def _create_ui(self) -> None:
        """Create the device settings dialog UI."""
        layout = QVBoxLayout(self)

        # Display group
        display_group = QGroupBox("Display")
        display_layout = QVBoxLayout(display_group)

        # Brightness slider
        from PySide6.QtWidgets import QSlider
        brightness_layout = QHBoxLayout()
        brightness_lbl = QLabel("Brightness:")
        brightness_lbl.setMinimumWidth(70)
        brightness_layout.addWidget(brightness_lbl)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(1, 9)
        self.brightness_slider.setValue(5)
        self.brightness_slider.setToolTip("Adjust device screen brightness\nRelease slider to apply.")
        self.brightness_slider.valueChanged.connect(self._on_brightness_label_update)
        self.brightness_slider.sliderReleased.connect(self._on_brightness_apply)
        brightness_layout.addWidget(self.brightness_slider)

        self.brightness_label = QLabel("5")
        self.brightness_label.setMinimumWidth(25)
        brightness_layout.addWidget(self.brightness_label)

        display_layout.addLayout(brightness_layout)

        # Standby Brightness slider
        standby_brt_layout = QHBoxLayout()
        standby_lbl = QLabel("Standby:")
        standby_lbl.setMinimumWidth(70)
        standby_brt_layout.addWidget(standby_lbl)

        self.standby_brightness_slider = QSlider(Qt.Horizontal)
        self.standby_brightness_slider.setRange(1, 9)
        self.standby_brightness_slider.setValue(3)
        self.standby_brightness_slider.setToolTip("Adjust standby screen brightness\nRelease slider to apply.")
        self.standby_brightness_slider.valueChanged.connect(self._on_standby_brightness_label_update)
        self.standby_brightness_slider.sliderReleased.connect(self._on_standby_brightness_apply)
        standby_brt_layout.addWidget(self.standby_brightness_slider)

        self.standby_brightness_label = QLabel("3")
        self.standby_brightness_label.setMinimumWidth(25)
        standby_brt_layout.addWidget(self.standby_brightness_label)

        display_layout.addLayout(standby_brt_layout)

        # Standby Timeout
        timeout_layout = QHBoxLayout()
        timeout_lbl = QLabel("Timeout:")
        timeout_lbl.setMinimumWidth(70)
        timeout_layout.addWidget(timeout_lbl)

        self.standby_timeout_spin = QSpinBox()
        self.standby_timeout_spin.setRange(10, 60)
        self.standby_timeout_spin.setValue(30)
        self.standby_timeout_spin.setSuffix(" s")
        self.standby_timeout_spin.setToolTip("Standby timeout in seconds")
        timeout_layout.addWidget(self.standby_timeout_spin)

        self.set_timeout_btn = QPushButton("Set")
        self.set_timeout_btn.setMaximumWidth(50)
        self.set_timeout_btn.clicked.connect(self._on_set_standby_timeout)
        timeout_layout.addWidget(self.set_timeout_btn)

        display_layout.addLayout(timeout_layout)

        layout.addWidget(display_group)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _on_brightness_label_update(self, value: int) -> None:
        """Update brightness label while dragging."""
        self.brightness_label.setText(str(value))

    def _on_brightness_apply(self) -> None:
        """Apply brightness when slider is released."""
        value = self.brightness_slider.value()
        if self.device and hasattr(self.device, 'set_brightness'):
            self.device.set_brightness(value)

    def _on_standby_brightness_label_update(self, value: int) -> None:
        """Update standby brightness label while dragging."""
        self.standby_brightness_label.setText(str(value))

    def _on_standby_brightness_apply(self) -> None:
        """Apply standby brightness when slider is released."""
        value = self.standby_brightness_slider.value()
        if self.device and hasattr(self.device, 'set_standby_brightness'):
            self.device.set_standby_brightness(value)

    def _on_set_standby_timeout(self) -> None:
        """Set standby timeout."""
        value = self.standby_timeout_spin.value()
        if self.device and hasattr(self.device, 'set_standby_timeout'):
            self.device.set_standby_timeout(value)
