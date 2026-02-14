"""Test list panel for viewing and selecting test data files."""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QColorDialog, QMessageBox, QFileDialog,
    QCheckBox, QLabel
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from .json_viewer_dialog import JsonViewerDialog


class ColorButton(QPushButton):
    """Button that displays and allows selection of a color."""

    color_changed = Signal(QColor)

    def __init__(self, initial_color: QColor = None):
        super().__init__()
        self._color = initial_color or QColor(255, 0, 0)
        self.setMaximumWidth(30)
        self.setMaximumHeight(25)
        self.clicked.connect(self._choose_color)
        self._update_style()

    def _update_style(self):
        """Update button style to show current color."""
        self.setStyleSheet(f"background-color: {self._color.name()}; border: 1px solid #666;")

    def _choose_color(self):
        """Open color picker dialog."""
        color = QColorDialog.getColor(self._color, self, "Choose Color")
        if color.isValid():
            self._color = color
            self._update_style()
            self.color_changed.emit(color)

    def get_color(self) -> QColor:
        """Get current color."""
        return self._color

    def set_color(self, color: QColor):
        """Set color without emitting signal."""
        self._color = color
        self._update_style()


class TestListPanel(QWidget):
    """Panel showing list of test files for a specific test type."""

    # Signals
    selection_changed = Signal(list)  # List of selected test data dicts
    files_changed = Signal()  # Emitted when files are added/removed

    def __init__(self, test_type: str, data_directory: Path, log_callback=None):
        """Initialize test list panel.

        Args:
            test_type: Type of test (battery_capacity, battery_load, etc.)
            data_directory: Directory containing test data files
            log_callback: Optional callback function for logging (message, level)
        """
        super().__init__()

        self.test_type = test_type
        self.data_directory = data_directory
        self._log_callback = log_callback
        self._test_files: List[Dict[str, Any]] = []  # List of {path, data, color, checked}
        self._default_colors = [
            QColor(255, 0, 0),    # Red
            QColor(0, 0, 255),    # Blue
            QColor(0, 255, 0),    # Green
            QColor(255, 165, 0),  # Orange
            QColor(128, 0, 128),  # Purple
            QColor(0, 255, 255),  # Cyan
            QColor(255, 0, 255),  # Magenta
            QColor(128, 128, 0),  # Olive
        ]
        self._color_index = 0

        # JSON viewer dialog
        self._json_viewer = JsonViewerDialog()

        self._create_ui()
        self._load_test_files()

        # Auto-refresh timer (check for new files every 5 seconds)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_for_updates)
        self._refresh_timer.start(5000)  # 5 seconds

    def _log(self, message: str, level: str = "INFO"):
        """Log a message if callback is available."""
        if self._log_callback:
            self._log_callback(message, level)

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Top controls
        controls_layout = QHBoxLayout()

        # File count label
        self.file_count_label = QLabel("0 files")
        controls_layout.addWidget(self.file_count_label)

        controls_layout.addStretch()

        # Browse button
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setToolTip("Browse to a different data folder")
        self.browse_btn.clicked.connect(self._browse_folder)
        controls_layout.addWidget(self.browse_btn)

        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload test files from disk")
        self.refresh_btn.clicked.connect(self._load_test_files)
        controls_layout.addWidget(self.refresh_btn)

        layout.addLayout(controls_layout)

        # Table widget for test files
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        # Initial headers (will be updated based on test type in _populate_table)
        self.table.setHorizontalHeaderLabels([
            "✓", "Color", "Test Date", "Manufactured", "Manufacturer", "Name", "SN",
            "Conditions", "Result 1", "Result 2", "JSON", "Delete"
        ])

        # Set column widths - make all columns user-resizable (Interactive mode)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Checkbox (auto)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Color (auto)
        header.setSectionResizeMode(2, QHeaderView.Interactive)  # Test Date (user-resizable)
        header.setSectionResizeMode(3, QHeaderView.Interactive)  # Manufactured (user-resizable)
        header.setSectionResizeMode(4, QHeaderView.Interactive)  # Manufacturer (user-resizable)
        header.setSectionResizeMode(5, QHeaderView.Stretch)  # Name (stretches)
        header.setSectionResizeMode(6, QHeaderView.Interactive)  # SN (user-resizable)
        header.setSectionResizeMode(7, QHeaderView.Interactive)  # Conditions (user-resizable)
        header.setSectionResizeMode(8, QHeaderView.Interactive)  # Result 1: Capacity or Resistance (user-resizable)
        header.setSectionResizeMode(9, QHeaderView.Interactive)  # Result 2: Energy or R² (user-resizable)
        header.setSectionResizeMode(10, QHeaderView.ResizeToContents)  # JSON (auto)
        header.setSectionResizeMode(11, QHeaderView.ResizeToContents)  # Delete (auto)

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        # Enable sorting by clicking column headers
        # Note: Must be set AFTER populating table to avoid breaking cell widgets
        self.table.setSortingEnabled(False)  # Will enable after first population

        # Resize columns to content on initial load
        header.setStretchLastSection(False)

        # Connect item changed signal for checkbox handling
        self.table.itemChanged.connect(self._on_item_changed)

        layout.addWidget(self.table)

    def _browse_folder(self):
        """Browse to a different data folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Data Folder",
            str(self.data_directory),
            QFileDialog.ShowDirsOnly
        )

        if folder:
            self.data_directory = Path(folder)
            self._load_test_files()

    def _load_test_files(self):
        """Load test files from the data directory by scanning all JSON files and filtering by test_panel_type."""
        self._log(f"Loading test files for type: {self.test_type}", "DEBUG")

        if not self.data_directory.exists():
            self._log(f"Data directory does not exist, creating: {self.data_directory}", "WARN")
            self.data_directory.mkdir(parents=True, exist_ok=True)

        # Save current checked states and colors before reloading
        previous_states = {}
        for test_file in self._test_files:
            file_path = test_file['path']
            previous_states[file_path] = {
                'checked': test_file['checked'],
                'color': test_file['color']
            }

        # Scan ALL JSON files in the directory (fast - single directory scan)
        json_files = list(self.data_directory.glob("*.json"))
        self._log(f"Scanning {len(json_files)} JSON files for test_panel_type='{self.test_type}'", "DEBUG")

        # Clear current list
        self._test_files.clear()
        self._color_index = 0

        # Load each file and filter by test_panel_type
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                # Filter by test_panel_type field
                file_test_type = data.get('test_panel_type', '')
                if file_test_type != self.test_type:
                    continue  # Skip files that don't match this panel's type

                # Restore previous state if this file was loaded before
                if json_file in previous_states:
                    checked = previous_states[json_file]['checked']
                    color = previous_states[json_file]['color']
                else:
                    # New file - assign new color and default to unchecked
                    checked = False
                    color = self._default_colors[self._color_index % len(self._default_colors)]
                    self._color_index += 1

                self._test_files.append({
                    'path': json_file,
                    'data': data,
                    'color': color,
                    'checked': checked
                })
            except Exception as e:
                self._log(f"Error loading {json_file.name}: {e}", "ERROR")

        # Sort by modification time (newest first)
        self._test_files.sort(key=lambda x: x['path'].stat().st_mtime, reverse=True)

        self._populate_table()
        self.file_count_label.setText(f"{len(self._test_files)} files")
        self._log(f"Loaded {len(self._test_files)} test files for type '{self.test_type}'", "INFO")

    def _check_for_updates(self):
        """Check if files have been added or removed."""
        if not self.data_directory.exists():
            return

        # Get all JSON files and filter by test_panel_type (quick check)
        json_files = list(self.data_directory.glob("*.json"))
        current_files = set()

        for json_file in json_files:
            try:
                # Quick read to check test_panel_type
                with open(json_file, 'r') as f:
                    data = json.load(f)
                if data.get('test_panel_type', '') == self.test_type:
                    current_files.add(json_file)
            except:
                pass  # Skip files that can't be read

        stored_files = {item['path'] for item in self._test_files}

        if current_files != stored_files:
            # Files changed, reload
            self._log(f"File changes detected, reloading {self.test_type} files", "INFO")
            self._load_test_files()
            self.files_changed.emit()

    def _populate_table(self):
        """Populate table with test file information."""
        # Update column headers based on test type
        if self.test_type == 'battery_load':
            # Battery Load: show Resistance and R²
            self.table.setHorizontalHeaderLabels([
                "✓", "Color", "Test Date", "Manufactured", "Manufacturer", "Name", "SN",
                "Conditions", "Resistance", "R²", "JSON", "Delete"
            ])
        else:
            # Battery Capacity and others: show Capacity and Energy
            self.table.setHorizontalHeaderLabels([
                "✓", "Color", "Test Date", "Manufactured", "Manufacturer", "Name", "SN",
                "Conditions", "Capacity", "Energy", "JSON", "Delete"
            ])

        # Block signals during population to avoid triggering itemChanged
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._test_files))

        for row, test_file in enumerate(self._test_files):
            data = test_file['data']

            # Checkbox - use checkable QTableWidgetItem instead of QCheckBox widget
            # This works properly with table sorting
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.Checked if test_file['checked'] else Qt.Unchecked)
            # Store the test file index in the item's UserRole so we can find it after sorting
            checkbox_item.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, checkbox_item)

            # Color button
            color_btn = ColorButton(test_file['color'])
            color_btn.color_changed.connect(lambda color, r=row: self._on_color_changed(r, color))
            color_widget = QWidget()
            color_layout = QHBoxLayout(color_widget)
            color_layout.addWidget(color_btn)
            color_layout.setAlignment(Qt.AlignCenter)
            color_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 1, color_widget)

            # Date - get from summary.start_time or first reading
            timestamp = None
            summary = data.get('summary', {})
            if summary:
                timestamp = summary.get('start_time')

            if not timestamp:
                # Fallback to first reading's timestamp
                readings = data.get('readings', [])
                if readings:
                    timestamp = readings[0].get('timestamp')

            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = timestamp[:16] if len(timestamp) > 16 else timestamp
            else:
                date_str = ""

            self.table.setItem(row, 2, QTableWidgetItem(date_str))

            # Manufactured date - column 3
            battery_info = data.get('battery_info', {})
            manufactured = battery_info.get('manufactured', '')
            if manufactured:
                # Format as YYYY-MM-DD if it's a valid date
                try:
                    dt = datetime.fromisoformat(manufactured)
                    manufactured_str = dt.strftime("%Y-%m-%d")
                except:
                    manufactured_str = manufactured
            else:
                manufactured_str = ""
            self.table.setItem(row, 3, QTableWidgetItem(manufactured_str))

            # Manufacturer - column 4
            manufacturer = battery_info.get('manufacturer', '')
            self.table.setItem(row, 4, QTableWidgetItem(manufacturer))

            # Name (battery name, cable name, etc.) - column 5
            name = battery_info.get('name', data.get('device_name', 'Unknown'))
            self.table.setItem(row, 5, QTableWidgetItem(name))

            # Serial Number - column 6
            serial_number = battery_info.get('serial_number', '')
            self.table.setItem(row, 6, QTableWidgetItem(serial_number))

            # Conditions - column 7
            test_config = data.get('test_config', {})
            conditions = self._format_conditions(test_config)
            self.table.setItem(row, 7, QTableWidgetItem(conditions))

            # Result columns - show different values based on test type
            test_panel_type = data.get('test_panel_type', 'battery_capacity')
            summary = data.get('summary', {})
            readings = data.get('readings', [])

            if test_panel_type == 'battery_load':
                # For Battery Load: show Resistance and R²
                resistance_ohm = summary.get('battery_resistance_ohm')
                r_squared = summary.get('resistance_r_squared')

                # If resistance not in file, calculate it now
                if resistance_ohm is None and len(readings) >= 2:
                    resistance_ohm, r_squared = self._calculate_resistance(readings)

                    # Update the JSON file with calculated values
                    if resistance_ohm is not None:
                        if 'summary' not in data:
                            data['summary'] = {}
                        data['summary']['battery_resistance_ohm'] = float(resistance_ohm)
                        data['summary']['resistance_r_squared'] = float(r_squared)

                        # Write back to file
                        try:
                            with open(test_file['path'], 'w') as f:
                                json.dump(data, f, indent=2)
                        except Exception as e:
                            print(f"Warning: Could not update JSON file with resistance: {e}")

                result1_str = f"{resistance_ohm:.3f} Ω" if resistance_ohm is not None else ""
                result2_str = f"{r_squared:.4f}" if r_squared is not None else ""
            else:
                # For Battery Capacity and others: show Capacity and Energy
                results = data.get('results', {})

                if results:
                    # Use results section if available
                    capacity = results.get('capacity_mah', 0)
                    energy = results.get('energy_wh', 0)
                elif readings:
                    # Otherwise use last reading
                    last_reading = readings[-1]
                    capacity = last_reading.get('capacity_mah', 0)
                    energy = last_reading.get('energy_wh', 0)
                else:
                    capacity = 0
                    energy = 0

                result1_str = f"{capacity:.0f} mAh" if capacity else ""
                result2_str = f"{energy:.2f} Wh" if energy else ""

            self.table.setItem(row, 8, QTableWidgetItem(result1_str))
            self.table.setItem(row, 9, QTableWidgetItem(result2_str))

            # View JSON button - column 10
            json_btn = QPushButton("📄")
            json_btn.setMaximumWidth(30)
            json_btn.setToolTip("View raw JSON data")
            json_btn.clicked.connect(lambda checked, r=row: self._view_json(r))
            json_widget = QWidget()
            json_layout = QHBoxLayout(json_widget)
            json_layout.addWidget(json_btn)
            json_layout.setAlignment(Qt.AlignCenter)
            json_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 10, json_widget)

            # Delete button - column 11
            delete_btn = QPushButton("✕")
            delete_btn.setMaximumWidth(30)
            delete_btn.setToolTip("Delete this test file")
            delete_btn.clicked.connect(lambda checked, r=row: self._delete_file(r))
            delete_widget = QWidget()
            delete_layout = QHBoxLayout(delete_widget)
            delete_layout.addWidget(delete_btn)
            delete_layout.setAlignment(Qt.AlignCenter)
            delete_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 11, delete_widget)

        # Auto-resize columns to fit content
        for col in [2, 3, 4, 6, 7, 8, 9]:  # Test Date, Manufactured, Manufacturer, SN, Conditions, Result 1, Result 2
            self.table.resizeColumnToContents(col)

        # Re-enable signals and sorting
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)

    def _calculate_resistance(self, readings: list) -> tuple:
        """Calculate battery resistance from readings using linear regression.

        Args:
            readings: List of reading dicts with current_a and voltage_v

        Returns:
            tuple: (resistance_ohm, r_squared) or (None, None) if calculation fails
        """
        try:
            import numpy as np
            # Extract current and voltage data
            currents = [r.get("current_a", 0) for r in readings]
            voltages = [r.get("voltage_v", 0) for r in readings]

            # Filter out zero current readings
            valid_points = [(c, v) for c, v in zip(currents, voltages) if c > 0]

            if len(valid_points) < 2:
                return None, None

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

            return resistance_ohm, r_squared
        except Exception as e:
            print(f"Warning: Could not calculate battery resistance: {e}")
            return None, None

    def _format_conditions(self, test_config: dict) -> str:
        """Format test conditions as a string."""
        parts = []

        discharge_type = test_config.get('discharge_type')
        if discharge_type is not None:
            modes = {0: 'CC', 1: 'CP', 2: 'CV', 3: 'CR'}
            mode = modes.get(discharge_type, f'Mode {discharge_type}')
            parts.append(mode)

        value = test_config.get('value')
        if value is not None:
            parts.append(f"{value:.2f}")

        voltage_cutoff = test_config.get('voltage_cutoff')
        if voltage_cutoff:
            parts.append(f"Cutoff: {voltage_cutoff:.2f}V")

        return " | ".join(parts) if parts else ""

    def _on_item_changed(self, item: QTableWidgetItem):
        """Handle table item change (checkbox state)."""
        if item.column() != 0:  # Only handle checkbox column
            return

        checked = (item.checkState() == Qt.Checked)

        # Get the test file index stored in the item's UserRole
        test_file_index = item.data(Qt.ItemDataRole.UserRole)

        if test_file_index is not None and 0 <= test_file_index < len(self._test_files):
            test_file = self._test_files[test_file_index]
            test_file['checked'] = checked

            # Log with more detail to identify the specific file
            name = test_file['data'].get('battery_info', {}).get('name', 'Unknown')
            manufacturer = test_file['data'].get('battery_info', {}).get('manufacturer', '')
            label = f"{manufacturer} {name}" if manufacturer else name
            self._log(f"Checkbox changed: {label}, checked={checked}", "DEBUG")

            self._emit_selection_changed()

    def _on_color_changed(self, row: int, color: QColor):
        """Handle color change."""
        if 0 <= row < len(self._test_files):
            self._test_files[row]['color'] = color
            self._emit_selection_changed()

    def _view_json(self, row: int):
        """View JSON data for a test file."""
        if not (0 <= row < self.table.rowCount()):
            return

        # Get the test name from the table to find matching test file
        name_item = self.table.item(row, 5)  # Name column
        if not name_item:
            return

        name = name_item.text()

        # Find matching test file
        for test_file in self._test_files:
            test_name = test_file['data'].get('battery_info', {}).get('name', 'Unknown')
            if test_name == name:
                file_path = test_file['path']
                self._log(f"Opening JSON viewer for: {file_path.name}", "DEBUG")
                self._json_viewer.load_json_file(file_path)
                self._json_viewer.show()
                self._json_viewer.raise_()
                self._json_viewer.activateWindow()
                break

    def _delete_file(self, row: int):
        """Delete a test file."""
        if not (0 <= row < len(self._test_files)):
            return

        test_file = self._test_files[row]
        file_path = test_file['path']

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete test file?\n\n{file_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self._load_test_files()
                self.files_changed.emit()
                self._emit_selection_changed()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Delete Error",
                    f"Failed to delete file:\n{e}"
                )

    def _emit_selection_changed(self):
        """Emit signal with currently selected test data."""
        selected = [
            {
                'data': item['data'],
                'color': item['color'],
                'name': item['data'].get('battery_info', {}).get('name', 'Unknown'),
                'manufacturer': item['data'].get('battery_info', {}).get('manufacturer', ''),
            }
            for item in self._test_files
            if item['checked']
        ]
        self._log(f"Emitting selection_changed with {len(selected)} tests", "DEBUG")
        self.selection_changed.emit(selected)

    def get_selected_tests(self) -> List[Dict[str, Any]]:
        """Get list of selected test data."""
        return [
            {
                'data': item['data'],
                'color': item['color'],
                'name': item['data'].get('battery_info', {}).get('name', 'Unknown'),
                'manufacturer': item['data'].get('battery_info', {}).get('manufacturer', ''),
            }
            for item in self._test_files
            if item['checked']
        ]
