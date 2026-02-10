"""Historical data browser panel."""

import json
from typing import Optional
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
    QLabel,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QCursor

from ..data.database import Database
from ..data.models import TestSession


class HistoryPanel(QWidget):
    """Panel for browsing historical test data from JSON files."""

    json_file_selected = Signal(str, str)  # Emits (file_path, test_panel_type) when a file is clicked

    # Map test panel types to friendly names
    PANEL_TYPE_NAMES = {
        "battery_capacity": "Battery Capacity",
        "battery_load": "Battery Load",
        "battery_charger": "Battery Charger",
        "cable_resistance": "Cable Resistance",
        "charger": "Charger",
        "power_bank": "Power Bank",
    }

    def __init__(self, database: Database):
        super().__init__()

        self.database = database
        self._test_files: list[dict] = []  # List of test file info dicts
        self._test_data_dir = Path.home() / ".atorch" / "test_data"

        # Ensure directory exists
        self._test_data_dir.mkdir(parents=True, exist_ok=True)

        self._create_ui()
        self.refresh()

    def _create_ui(self) -> None:
        """Create the history panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top bar with refresh button
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Test History (JSON Files)"))
        top_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top_layout.addWidget(self.refresh_btn)

        layout.addLayout(top_layout)

        # Test files table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Date",
            "Name of File",
            "Test Type",
            "Conditions",
            "Duration",
            "Summary",
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)  # Enable sorting by clicking column headers

        # Configure column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Date
        header.setSectionResizeMode(1, QHeaderView.Stretch)           # Name of File
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Test Type
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Conditions
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Duration
        header.setSectionResizeMode(5, QHeaderView.Stretch)           # Summary

        self.table.cellClicked.connect(self._on_cell_clicked)

        layout.addWidget(self.table)

        # Action buttons
        action_layout = QHBoxLayout()

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self._on_delete)
        action_layout.addWidget(self.delete_btn)

        self.open_folder_btn = QPushButton("Show Folder")
        self.open_folder_btn.clicked.connect(self._on_show_folder)
        action_layout.addWidget(self.open_folder_btn)

        action_layout.addStretch()

        layout.addLayout(action_layout)

    @Slot()
    def refresh(self) -> None:
        """Refresh the test files list."""
        self._test_files = []

        # Scan test_data directory for JSON files
        if not self._test_data_dir.exists():
            self.table.setRowCount(0)
            return

        json_files = sorted(self._test_data_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                # Extract information from JSON
                summary_data = data.get("summary", {})
                test_config = data.get("test_config", {})
                battery_info = data.get("battery_info", {})
                test_panel_type = data.get("test_panel_type", "battery_capacity")

                # Parse date from filename or start_time
                start_time_str = summary_data.get("start_time", "")
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    date_str = start_time.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = "Unknown"

                # Test type - use panel type with friendly name
                test_type_display = self.PANEL_TYPE_NAMES.get(test_panel_type, test_panel_type.replace("_", " ").title())

                # Conditions - extract test conditions from test_config
                discharge_type = test_config.get("discharge_type", "")
                value = test_config.get("value", 0)
                unit = test_config.get("value_unit", "")
                voltage_cutoff = test_config.get("voltage_cutoff", 0)
                timed = test_config.get("timed", False)
                duration_seconds = test_config.get("duration_seconds", 0)

                conditions_parts = []
                if discharge_type and value:
                    conditions_parts.append(f"{discharge_type} {value}{unit}")
                if voltage_cutoff > 0:
                    conditions_parts.append(f"Cutoff {voltage_cutoff}V")
                if timed and duration_seconds > 0:
                    h = duration_seconds // 3600
                    m = (duration_seconds % 3600) // 60
                    if h > 0:
                        conditions_parts.append(f"Time {h}h{m}m")
                    else:
                        conditions_parts.append(f"Time {m}m")

                conditions_str = ", ".join(conditions_parts) if conditions_parts else "N/A"

                # Duration
                duration_sec = summary_data.get("total_runtime_seconds", 0)
                h = duration_sec // 3600
                m = (duration_sec % 3600) // 60
                s = duration_sec % 60
                duration_str = f"{h:02d}:{m:02d}:{s:02d}"

                # Summary (result)
                capacity = summary_data.get("final_capacity_mah", 0)
                energy = summary_data.get("final_energy_wh", 0)
                battery_name = battery_info.get("name", "")

                if capacity > 0 or energy > 0:
                    summary_str = f"{battery_name}: {capacity:.0f} mAh / {energy:.2f} Wh"
                else:
                    summary_str = f"{battery_name}: No data recorded"

                self._test_files.append({
                    "path": str(json_file),
                    "filename": json_file.name,
                    "date": date_str,
                    "test_type": test_type_display,
                    "test_panel_type": test_panel_type,
                    "conditions": conditions_str,
                    "duration": duration_str,
                    "summary": summary_str,
                })

            except Exception as e:
                # Skip files that can't be parsed
                continue

        # Populate table
        # Temporarily disable sorting while populating to avoid issues
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._test_files))

        for row, file_info in enumerate(self._test_files):
            # Date
            self.table.setItem(row, 0, QTableWidgetItem(file_info["date"]))

            # Name of File (clickable, underlined, blue)
            filename_item = QTableWidgetItem(file_info["filename"])
            font = QFont()
            font.setUnderline(True)
            filename_item.setFont(font)
            filename_item.setForeground(Qt.blue)
            filename_item.setData(Qt.UserRole, file_info["path"])  # Store full path
            self.table.setItem(row, 1, filename_item)

            # Test Type
            self.table.setItem(row, 2, QTableWidgetItem(file_info["test_type"]))

            # Conditions
            self.table.setItem(row, 3, QTableWidgetItem(file_info["conditions"]))

            # Duration
            self.table.setItem(row, 4, QTableWidgetItem(file_info["duration"]))

            # Summary
            self.table.setItem(row, 5, QTableWidgetItem(file_info["summary"]))

        # Re-enable sorting after populating
        self.table.setSortingEnabled(True)

        # Set cursor to pointing hand for filename column
        self.table.viewport().setCursor(QCursor(Qt.ArrowCursor))

    @Slot(int, int)
    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Handle cell click - if Name of File column, emit signal to load."""
        if column == 1:  # Name of File column
            if 0 <= row < len(self._test_files):
                file_info = self._test_files[row]
                file_path = file_info["path"]
                test_panel_type = file_info["test_panel_type"]
                self.json_file_selected.emit(file_path, test_panel_type)

    @Slot()
    def _on_delete(self) -> None:
        """Delete the selected test file(s)."""
        # Get all selected rows
        selected_rows = sorted(set(index.row() for index in self.table.selectedIndexes()))

        if not selected_rows:
            QMessageBox.information(self, "Delete", "Please select test file(s) to delete.")
            return

        # Get file info for selected rows
        files_to_delete = []
        for row in selected_rows:
            if 0 <= row < len(self._test_files):
                files_to_delete.append(self._test_files[row])

        if not files_to_delete:
            return

        # Confirm deletion
        if len(files_to_delete) == 1:
            message = f"Are you sure you want to delete '{files_to_delete[0]['filename']}'?\nThis cannot be undone."
        else:
            message = f"Are you sure you want to delete {len(files_to_delete)} test files?\nThis cannot be undone."

        reply = QMessageBox.question(
            self,
            "Delete Test File(s)",
            message,
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            failed_files = []
            for file_info in files_to_delete:
                try:
                    Path(file_info["path"]).unlink()
                except Exception as e:
                    failed_files.append(f"{file_info['filename']}: {e}")

            self.refresh()

            if failed_files:
                QMessageBox.warning(
                    self,
                    "Delete Error",
                    f"Failed to delete some files:\n" + "\n".join(failed_files)
                )

    @Slot()
    def _on_show_folder(self) -> None:
        """Open the test_data folder in the system file manager, highlighting selected file if any."""
        import subprocess
        import platform

        # Get selected rows
        selected_rows = sorted(set(index.row() for index in self.table.selectedIndexes()))

        # If exactly one file is selected, highlight it; otherwise just open folder
        selected_file = None
        if len(selected_rows) == 1:
            row = selected_rows[0]
            if 0 <= row < len(self._test_files):
                selected_file = self._test_files[row]["path"]

        try:
            system = platform.system()
            if selected_file:
                # Highlight/reveal the selected file
                if system == "Darwin":  # macOS
                    subprocess.run(["open", "-R", selected_file])
                elif system == "Windows":
                    subprocess.run(["explorer", f"/select,{selected_file}"])
                else:  # Linux - just open folder (no standard way to select file)
                    subprocess.run(["xdg-open", str(self._test_data_dir)])
            else:
                # No file selected or multiple files selected, just open the folder
                if system == "Darwin":  # macOS
                    subprocess.run(["open", str(self._test_data_dir)])
                elif system == "Windows":
                    subprocess.run(["explorer", str(self._test_data_dir)])
                else:  # Linux
                    subprocess.run(["xdg-open", str(self._test_data_dir)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder: {e}")
