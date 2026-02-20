"""Settings dialog for application configuration."""

import os
import subprocess
from pathlib import Path
from datetime import datetime
from platform import system

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
    QLineEdit,
    QGridLayout,
    QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import Qt, QTimer

from ..config import get_data_dir, set_data_dir, get_default_data_dir
from ..alerts.notifier import Notifier
from ..alerts.conditions import VoltageAlert, TemperatureAlert
from ..data.database import Database


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, notifier: Notifier, parent=None, notification_settings=None, database=None):
        super().__init__(parent)

        self.notifier = notifier
        self._notification_settings = notification_settings or {}
        self.database = database

        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        self._create_ui()
        self._load_settings()

    def _create_ui(self) -> None:
        """Create the settings dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        tabs = self.tabs

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
        voltage_layout.addRow("Threshold", self.voltage_threshold_spin)

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
        temp_layout.addRow("Threshold", self.temp_threshold_spin)

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
        plot_layout.addRow("Max data points", self.max_points_spin)

        display_layout.addWidget(plot_group)
        display_layout.addStretch()
        tabs.addTab(display_tab, "Display")

        # Notifications tab
        notif_tab = QWidget()
        notif_tab_layout = QVBoxLayout(notif_tab)

        # ntfy group
        ntfy_group = QGroupBox("ntfy")
        ntfy_layout = QFormLayout(ntfy_group)

        self.ntfy_enabled_check = QCheckBox("Enable")
        self.ntfy_enabled_check.toggled.connect(self._update_ntfy_enabled)
        ntfy_layout.addRow("", self.ntfy_enabled_check)

        self.ntfy_server_edit = QLineEdit()
        self.ntfy_server_edit.setPlaceholderText("https://ntfy.sh")
        ntfy_layout.addRow("Server", self.ntfy_server_edit)

        self.ntfy_topic_edit = QLineEdit()
        self.ntfy_topic_edit.setPlaceholderText("e.g. atorch-my-device")
        ntfy_layout.addRow("Topic", self.ntfy_topic_edit)

        self.ntfy_test_btn = QPushButton("Send Test")
        self.ntfy_test_btn.clicked.connect(self._test_ntfy)
        ntfy_layout.addRow("", self.ntfy_test_btn)

        notif_tab_layout.addWidget(ntfy_group)

        # Pushover group
        pushover_group = QGroupBox("Pushover")
        pushover_layout = QFormLayout(pushover_group)

        self.pushover_enabled_check = QCheckBox("Enable")
        self.pushover_enabled_check.toggled.connect(self._update_pushover_enabled)
        pushover_layout.addRow("", self.pushover_enabled_check)

        self.pushover_user_edit = QLineEdit()
        self.pushover_user_edit.setPlaceholderText("User Key from pushover.net")
        pushover_layout.addRow("User Key", self.pushover_user_edit)

        self.pushover_token_edit = QLineEdit()
        self.pushover_token_edit.setPlaceholderText("Create app at pushover.net/apps")
        pushover_layout.addRow("App Token", self.pushover_token_edit)

        self.pushover_test_btn = QPushButton("Send Test")
        self.pushover_test_btn.clicked.connect(self._test_pushover)
        pushover_layout.addRow("", self.pushover_test_btn)

        notif_tab_layout.addWidget(pushover_group)

        # Events group — which events trigger push notifications
        self.events_group = QGroupBox("Events")
        events_layout = QVBoxLayout(self.events_group)

        self.notify_started_check = QCheckBox("Test Started")
        self.notify_started_check.setChecked(False)
        events_layout.addWidget(self.notify_started_check)

        self.notify_ended_check = QCheckBox("Test Ended")
        self.notify_ended_check.setChecked(True)
        events_layout.addWidget(self.notify_ended_check)

        self.notify_aborted_check = QCheckBox("Test Aborted")
        self.notify_aborted_check.setChecked(True)
        events_layout.addWidget(self.notify_aborted_check)

        notif_tab_layout.addWidget(self.events_group)

        # Connect enable checkboxes to show/hide events group
        self.ntfy_enabled_check.toggled.connect(self._update_events_visible)
        self.pushover_enabled_check.toggled.connect(self._update_events_visible)

        notif_tab_layout.addStretch()
        tabs.addTab(notif_tab, "Notifications")

        # Testing tab
        testing_tab = QWidget()
        testing_layout = QVBoxLayout(testing_tab)

        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout(timing_group)

        self.start_delay_spin = QSpinBox()
        self.start_delay_spin.setRange(0, 60)
        self.start_delay_spin.setValue(3)
        self.start_delay_spin.setSuffix(" s")
        self.start_delay_spin.setToolTip(
            "Delay between applying test conditions and turning on the load.\n"
            "Allows capturing unloaded voltage before the test begins."
        )
        timing_layout.addRow("Start Delay", self.start_delay_spin)

        testing_layout.addWidget(timing_group)
        testing_layout.addStretch()
        tabs.addTab(testing_tab, "Testing")

        # Database tab
        if self.database:
            db_tab = QWidget()
            db_tab_layout = QVBoxLayout(db_tab)

            # Data Directory group
            dir_group = QGroupBox("Data Directory")
            dir_layout = QVBoxLayout()

            self.data_dir_label = QLabel(str(get_data_dir()))
            self.data_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.data_dir_label.setWordWrap(True)
            dir_layout.addWidget(self.data_dir_label)

            dir_btn_layout = QHBoxLayout()
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(self._browse_data_dir)
            dir_btn_layout.addWidget(browse_btn)

            reset_dir_btn = QPushButton("Reset to Default")
            reset_dir_btn.clicked.connect(self._reset_data_dir)
            dir_btn_layout.addWidget(reset_dir_btn)

            dir_btn_layout.addStretch()
            dir_layout.addLayout(dir_btn_layout)

            dir_info = QLabel("Changes take effect after restarting the application.")
            dir_info.setStyleSheet("color: #888; font-size: 11px;")
            dir_layout.addWidget(dir_info)

            dir_group.setLayout(dir_layout)
            db_tab_layout.addWidget(dir_group)

            # Statistics group
            stats_group = QGroupBox("Database Statistics")
            stats_layout = QGridLayout()

            stats_layout.addWidget(QLabel("Location"), 0, 0, Qt.AlignRight)
            self.db_location_label = QLabel()
            self.db_location_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.db_location_label.setWordWrap(True)
            stats_layout.addWidget(self.db_location_label, 0, 1)

            self.db_show_folder_btn = QPushButton("Show in Folder")
            self.db_show_folder_btn.clicked.connect(self._db_show_in_folder)
            stats_layout.addWidget(self.db_show_folder_btn, 0, 2)

            stats_layout.addWidget(QLabel("File Size"), 1, 0, Qt.AlignRight)
            self.db_size_label = QLabel()
            stats_layout.addWidget(self.db_size_label, 1, 1, 1, 2)

            stats_layout.addWidget(QLabel("Created"), 2, 0, Qt.AlignRight)
            self.db_created_label = QLabel()
            stats_layout.addWidget(self.db_created_label, 2, 1, 1, 2)

            stats_layout.addWidget(QLabel("Last Modified"), 3, 0, Qt.AlignRight)
            self.db_modified_label = QLabel()
            stats_layout.addWidget(self.db_modified_label, 3, 1, 1, 2)

            stats_layout.addWidget(QLabel("Sessions"), 4, 0, Qt.AlignRight)
            self.db_sessions_label = QLabel()
            stats_layout.addWidget(self.db_sessions_label, 4, 1, 1, 2)

            stats_layout.addWidget(QLabel("Total Readings"), 5, 0, Qt.AlignRight)
            self.db_readings_label = QLabel()
            stats_layout.addWidget(self.db_readings_label, 5, 1, 1, 2)

            stats_group.setLayout(stats_layout)
            db_tab_layout.addWidget(stats_group)

            # Maintenance group
            maint_group = QGroupBox("Maintenance")
            maint_layout = QHBoxLayout()

            vacuum_btn = QPushButton("Compact Database")
            vacuum_btn.setToolTip("Rebuild the database file to reclaim unused space (VACUUM)")
            vacuum_btn.clicked.connect(self._db_vacuum)
            maint_layout.addWidget(vacuum_btn)

            integrity_btn = QPushButton("Check Integrity")
            integrity_btn.setToolTip("Verify the structural integrity of the database (PRAGMA integrity_check)")
            integrity_btn.clicked.connect(self._db_integrity_check)
            maint_layout.addWidget(integrity_btn)

            maint_group.setLayout(maint_layout)
            db_tab_layout.addWidget(maint_group)

            # Management group
            mgmt_group = QGroupBox("Database Management")
            mgmt_layout = QVBoxLayout()

            info_label = QLabel(
                "Purging the database will permanently delete all test sessions and readings.\n"
                "This cannot be undone. Exported JSON/CSV files will not be affected."
            )
            info_label.setWordWrap(True)
            mgmt_layout.addWidget(info_label)

            purge_btn = QPushButton("Purge Database...")
            purge_btn.setStyleSheet("QPushButton { background-color: #c84040; color: white; font-weight: bold; }")
            purge_btn.clicked.connect(self._db_purge)
            mgmt_layout.addWidget(purge_btn)

            mgmt_group.setLayout(mgmt_layout)
            db_tab_layout.addWidget(mgmt_group)

            db_tab_layout.addStretch()
            tabs.addTab(db_tab, "Database")

            self._db_load_statistics()

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

        # Notification settings
        ns = self._notification_settings
        self.ntfy_enabled_check.setChecked(ns.get("ntfy_enabled", False))
        self.ntfy_server_edit.setText(ns.get("ntfy_server", "https://ntfy.sh"))
        self.ntfy_topic_edit.setText(ns.get("ntfy_topic", ""))
        self.pushover_enabled_check.setChecked(ns.get("pushover_enabled", False))
        self.pushover_user_edit.setText(ns.get("pushover_user_key", ""))
        self.pushover_token_edit.setText(ns.get("pushover_app_token", ""))

        # Event checkboxes
        self.notify_started_check.setChecked(ns.get("notify_test_started", False))
        self.notify_ended_check.setChecked(ns.get("notify_test_ended", True))
        self.notify_aborted_check.setChecked(ns.get("notify_test_aborted", True))

        # Testing settings
        self.start_delay_spin.setValue(self._notification_settings.get("start_delay", 3))

        # Apply initial enabled state
        self._update_ntfy_enabled(self.ntfy_enabled_check.isChecked())
        self._update_pushover_enabled(self.pushover_enabled_check.isChecked())
        self._update_events_visible()

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

        # Store updated notification settings for caller to retrieve
        self._notification_settings = self.get_notification_settings()

        self.accept()

    def get_notification_settings(self) -> dict:
        """Return current notification and testing settings from the UI."""
        return {
            "ntfy_enabled": self.ntfy_enabled_check.isChecked(),
            "ntfy_server": self.ntfy_server_edit.text().strip() or "https://ntfy.sh",
            "ntfy_topic": self.ntfy_topic_edit.text().strip(),
            "pushover_enabled": self.pushover_enabled_check.isChecked(),
            "pushover_user_key": self.pushover_user_edit.text().strip(),
            "pushover_app_token": self.pushover_token_edit.text().strip(),
            "notify_test_started": self.notify_started_check.isChecked(),
            "notify_test_ended": self.notify_ended_check.isChecked(),
            "notify_test_aborted": self.notify_aborted_check.isChecked(),
            "start_delay": self.start_delay_spin.value(),
        }

    def _update_events_visible(self, _=None) -> None:
        """Show/hide Events group based on whether any push service is enabled."""
        visible = self.ntfy_enabled_check.isChecked() or self.pushover_enabled_check.isChecked()
        self.events_group.setVisible(visible)

    def _update_ntfy_enabled(self, enabled: bool) -> None:
        """Enable/disable ntfy fields based on checkbox."""
        self.ntfy_server_edit.setEnabled(enabled)
        self.ntfy_topic_edit.setEnabled(enabled)
        self.ntfy_test_btn.setEnabled(enabled)

    def _update_pushover_enabled(self, enabled: bool) -> None:
        """Enable/disable Pushover fields based on checkbox."""
        self.pushover_user_edit.setEnabled(enabled)
        self.pushover_token_edit.setEnabled(enabled)
        self.pushover_test_btn.setEnabled(enabled)

    def _test_ntfy(self) -> None:
        """Send a test notification via ntfy."""
        import threading
        server = self.ntfy_server_edit.text().strip() or "https://ntfy.sh"
        topic = self.ntfy_topic_edit.text().strip()
        if not topic:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "ntfy", "Please enter a topic.")
            return

        def _send():
            try:
                import urllib.request
                url = f"{server.rstrip('/')}/{topic}"
                req = urllib.request.Request(url, data=b"Test notification from Load Test Bench",
                                             method="POST")
                req.add_header("Title", "Load Test Bench Test")
                urllib.request.urlopen(req, timeout=10)
            except Exception as e:
                print(f"ntfy test failed: {e}")

        threading.Thread(target=_send, daemon=True).start()
        self.ntfy_test_btn.setText("Sent!")
        QTimer.singleShot(2000, lambda: self.ntfy_test_btn.setText("Send Test"))

    def _test_pushover(self) -> None:
        """Send a test notification via Pushover."""
        import threading
        user = self.pushover_user_edit.text().strip()
        token = self.pushover_token_edit.text().strip()
        if not user or not token:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Pushover", "Please enter both User Key and App Token.")
            return

        def _send():
            try:
                import urllib.request
                import urllib.parse
                data = urllib.parse.urlencode({
                    "token": token,
                    "user": user,
                    "title": "Load Test Bench Test",
                    "message": "Test notification from Load Test Bench",
                }).encode()
                req = urllib.request.Request("https://api.pushover.net/1/messages.json",
                                             data=data, method="POST")
                urllib.request.urlopen(req, timeout=10)
            except Exception as e:
                print(f"Pushover test failed: {e}")

        threading.Thread(target=_send, daemon=True).start()
        self.pushover_test_btn.setText("Sent!")
        QTimer.singleShot(2000, lambda: self.pushover_test_btn.setText("Send Test"))


    # --- Data directory methods ---

    def _browse_data_dir(self) -> None:
        """Browse for a custom data directory."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Data Directory", str(get_data_dir())
        )
        if path:
            set_data_dir(Path(path))
            self.data_dir_label.setText(path)

    def _reset_data_dir(self) -> None:
        """Reset data directory to OS default."""
        set_data_dir(None)
        self.data_dir_label.setText(str(get_default_data_dir()))

    # --- Database tab methods ---

    def _db_load_statistics(self) -> None:
        """Load and display database statistics."""
        db_path = Path(self.database.path)
        self.db_location_label.setText(str(db_path))

        if not db_path.exists():
            self.db_size_label.setText("Database file not found")
            self.db_created_label.setText("N/A")
            self.db_modified_label.setText("N/A")
            self.db_sessions_label.setText("0")
            self.db_readings_label.setText("0")
            return

        size_bytes = db_path.stat().st_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                self.db_size_label.setText(f"{size_bytes:.1f} {unit}")
                break
            size_bytes /= 1024.0
        else:
            self.db_size_label.setText(f"{size_bytes:.1f} TB")

        try:
            if system() == "Darwin":
                created_time = db_path.stat().st_birthtime
            else:
                created_time = db_path.stat().st_ctime
            self.db_created_label.setText(datetime.fromtimestamp(created_time).strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self.db_created_label.setText("Unknown")

        modified_time = db_path.stat().st_mtime
        self.db_modified_label.setText(datetime.fromtimestamp(modified_time).strftime("%Y-%m-%d %H:%M:%S"))

        try:
            cursor = self.database._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sessions")
            self.db_sessions_label.setText(f"{cursor.fetchone()[0]:,}")
            cursor.execute("SELECT COUNT(*) FROM readings")
            self.db_readings_label.setText(f"{cursor.fetchone()[0]:,}")
        except Exception as e:
            self.db_sessions_label.setText(f"Error: {e}")
            self.db_readings_label.setText("N/A")

    def _db_show_in_folder(self) -> None:
        """Show database file in file browser."""
        db_path = str(self.database.path)
        if system() == "Darwin":
            subprocess.run(["open", "-R", db_path])
        elif system() == "Windows":
            subprocess.run(["explorer", f"/select,{db_path}"])
        else:
            subprocess.run(["xdg-open", str(Path(db_path).parent)])

    def _db_vacuum(self) -> None:
        """Compact the database by running VACUUM."""
        try:
            db_path = Path(self.database.path)
            size_before = db_path.stat().st_size if db_path.exists() else 0
            self.database._conn.execute("VACUUM")
            size_after = db_path.stat().st_size if db_path.exists() else 0
            saved = size_before - size_after
            if saved > 0:
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if saved < 1024.0:
                        saved_str = f"{saved:.1f} {unit}"
                        break
                    saved /= 1024.0
                else:
                    saved_str = f"{saved:.1f} TB"
                QMessageBox.information(self, "Compact Database",
                    f"Database compacted successfully.\nReclaimed {saved_str}.")
            else:
                QMessageBox.information(self, "Compact Database",
                    "Database compacted successfully.\nNo additional space to reclaim.")
            self._db_load_statistics()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to compact database:\n{e}")

    def _db_integrity_check(self) -> None:
        """Run integrity check on the database."""
        try:
            cursor = self.database._conn.execute("PRAGMA integrity_check")
            results = cursor.fetchall()
            if len(results) == 1 and results[0][0] == "ok":
                QMessageBox.information(self, "Integrity Check", "Database integrity check passed.")
            else:
                issues = "\n".join(row[0] for row in results[:20])
                QMessageBox.warning(self, "Integrity Check",
                    f"Database integrity issues found:\n\n{issues}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to check database integrity:\n{e}")

    def _db_purge(self) -> None:
        """Purge all data from the database."""
        reply = QMessageBox.question(
            self, "Purge Database?",
            "Are you sure you want to purge the database?\n\n"
            "This will permanently delete ALL test sessions and readings.\n"
            "This action cannot be undone.\n\n"
            "Exported JSON/CSV files will not be affected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Confirm Purge", "Type 'DELETE' (all caps) to confirm:")
        if not ok or text != "DELETE":
            QMessageBox.information(self, "Cancelled", "Database purge cancelled.")
            return

        try:
            cursor = self.database._conn.cursor()
            cursor.execute("DELETE FROM readings")
            cursor.execute("DELETE FROM sessions")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='readings'")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='sessions'")
            self.database._conn.commit()
            QMessageBox.information(self, "Success",
                "Database has been purged successfully.\n"
                "All test sessions and readings have been deleted.")
            self._db_load_statistics()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to purge database:\n{e}")


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
        brightness_lbl = QLabel("Brightness")
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
        standby_lbl = QLabel("Standby")
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
        timeout_lbl = QLabel("Timeout")
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

        # Factory Reset group
        reset_group = QGroupBox("Factory Reset")
        reset_layout = QVBoxLayout(reset_group)

        self.restore_defaults_btn = QPushButton("Restore Defaults")
        self.restore_defaults_btn.setToolTip("Restore device to factory default settings")
        self.restore_defaults_btn.clicked.connect(self._on_restore_defaults)
        reset_layout.addWidget(self.restore_defaults_btn)

        layout.addWidget(reset_group)

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

    def _on_restore_defaults(self) -> None:
        """Restore device to factory defaults."""
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Restore Defaults",
            "Are you sure you want to restore the device to factory default settings?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.device and hasattr(self.device, 'restore_defaults'):
                self.device.restore_defaults()
