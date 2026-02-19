"""Historical data browser panel."""

import json
import shutil
from typing import Optional
from pathlib import Path
from datetime import datetime, date
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
    QComboBox,
    QDateEdit,
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal, Slot, QDate
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
        "charger": "Charger Load",
        "power_bank": "Power Bank Capacity",
    }

    # Column indices
    COL_CHECK = 0
    COL_DATE = 1
    COL_FILENAME = 2
    COL_NAME = 3
    COL_TEST_TYPE = 4
    COL_CONDITIONS = 5
    COL_DURATION = 6
    COL_SUMMARY = 7
    COL_VIEW = 8
    NUM_COLS = 9

    def __init__(self, database: Database):
        super().__init__()

        self.database = database
        self._test_files: list[dict] = []  # All test file info dicts
        self._visible_files: list[dict] = []  # Filtered subset shown in table
        from ..config import get_data_dir
        self._test_data_dir = get_data_dir() / "test_data"
        self._trash_dir = self._test_data_dir / ".trash"

        self._create_ui()
        self.refresh()

    def _create_ui(self) -> None:
        """Create the history panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top bar: buttons and filters
        top_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top_layout.addWidget(self.refresh_btn)

        self.open_folder_btn = QPushButton("Show Folder")
        self.open_folder_btn.clicked.connect(self._on_show_folder)
        top_layout.addWidget(self.open_folder_btn)

        top_layout.addSpacing(20)

        self.delete_btn = QPushButton("Trash Selected")
        self.delete_btn.clicked.connect(self._on_delete)
        top_layout.addWidget(self.delete_btn)

        self.empty_trash_btn = QPushButton("Empty Trash...")
        self.empty_trash_btn.clicked.connect(self._on_empty_trash)
        top_layout.addWidget(self.empty_trash_btn)

        self.restore_btn = QPushButton("Restore...")
        self.restore_btn.clicked.connect(self._on_restore)
        top_layout.addWidget(self.restore_btn)

        top_layout.addStretch()

        # Test type filter
        top_layout.addWidget(QLabel("Test Type:"))
        self.type_filter_combo = QComboBox()
        self.type_filter_combo.addItem("All", "")
        for key, name in self.PANEL_TYPE_NAMES.items():
            self.type_filter_combo.addItem(name, key)
        self.type_filter_combo.setMinimumWidth(140)
        self.type_filter_combo.currentIndexChanged.connect(self._apply_filters)
        top_layout.addWidget(self.type_filter_combo)

        # Date range filter
        top_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.dateChanged.connect(self._apply_filters)
        top_layout.addWidget(self.date_from)

        top_layout.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setDate(QDate.currentDate())
        self.date_to.dateChanged.connect(self._apply_filters)
        top_layout.addWidget(self.date_to)

        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        top_layout.addWidget(self.clear_filters_btn)

        layout.addLayout(top_layout)

        # Test files table
        self.table = QTableWidget()
        self.table.setColumnCount(self.NUM_COLS)
        self.table.setHorizontalHeaderLabels([
            "",           # Checkbox
            "Date",
            "Name of File",
            "Name",
            "Test Type",
            "Conditions",
            "Run Time",
            "Summary",
            "",           # View button
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)

        # Configure column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_CHECK, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_CHECK, 30)
        header.setSectionResizeMode(self.COL_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_FILENAME, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TEST_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_CONDITIONS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_SUMMARY, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_VIEW, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_VIEW, 50)

        self.table.cellClicked.connect(self._on_cell_clicked)

        # Override table key press to toggle checkboxes on spacebar
        self.table.keyPressEvent = self._table_key_press

        layout.addWidget(self.table)

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
                start_date = None
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    date_str = start_time.strftime("%Y-%m-%d %H:%M")
                    start_date = start_time.date()
                except Exception:
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

                if test_panel_type == "battery_charger":
                    conditions_str = self._format_charger_conditions(test_config)
                else:
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

                # Run time from summary end_time - start_time
                end_time_str = summary_data.get("end_time", "")
                duration_sec = 0
                try:
                    if start_time_str and end_time_str:
                        st = datetime.fromisoformat(start_time_str)
                        et = datetime.fromisoformat(end_time_str)
                        duration_sec = abs(int((et - st).total_seconds()))
                except Exception:
                    pass
                h = duration_sec // 3600
                m = (duration_sec % 3600) // 60
                s = duration_sec % 60
                duration_str = f"{h:02d}:{m:02d}:{s:02d}"

                # Summary (result)
                capacity = summary_data.get("final_capacity_mah", 0)
                energy = summary_data.get("final_energy_wh", 0)

                # Extract manufacturer and device name based on test type
                manufacturer = ""
                device_name = ""

                if test_panel_type in ["battery_capacity", "battery_load"]:
                    manufacturer = battery_info.get("manufacturer", "")
                    device_name = battery_info.get("name", "")
                elif test_panel_type == "battery_charger":
                    charger_info = data.get("charger_info", {})
                    manufacturer = charger_info.get("manufacturer", "")
                    device_name = charger_info.get("name", "")
                elif test_panel_type == "charger":
                    charger_info = data.get("charger_info", {})
                    manufacturer = charger_info.get("manufacturer", "")
                    device_name = charger_info.get("name", "")
                elif test_panel_type == "power_bank":
                    power_bank_info = data.get("power_bank_info", {})
                    manufacturer = power_bank_info.get("manufacturer", "")
                    device_name = power_bank_info.get("name", "")

                # Build summary with manufacturer prefix
                if manufacturer:
                    full_name = f"{manufacturer} {device_name}".strip()
                else:
                    full_name = device_name

                if test_panel_type == "battery_charger":
                    # Show charger model in summary
                    charger_info = data.get("charger_info", battery_info)
                    charger_model = charger_info.get("model", "")
                    summary_str = f"{full_name} {charger_model}".strip() if charger_model else full_name
                elif capacity > 0 or energy > 0:
                    summary_str = f"{full_name}: {capacity:.0f} mAh / {energy:.2f} Wh"
                else:
                    summary_str = f"{full_name}: No data recorded"

                self._test_files.append({
                    "path": str(json_file),
                    "filename": json_file.name,
                    "date": date_str,
                    "start_date": start_date,
                    "device_name": full_name,
                    "test_type": test_type_display,
                    "test_panel_type": test_panel_type,
                    "conditions": conditions_str,
                    "duration": duration_str,
                    "summary": summary_str,
                })

            except Exception as e:
                # Skip files that can't be parsed
                print(f"ERROR parsing {json_file.name}: {e}")
                import traceback
                traceback.print_exc()
                continue

        # Auto-expand date range to cover all data
        dates = [f["start_date"] for f in self._test_files if f.get("start_date")]
        if dates:
            earliest = min(dates)
            latest = max(dates)
            self.date_from.blockSignals(True)
            self.date_to.blockSignals(True)
            self.date_from.setDate(QDate(earliest.year, earliest.month, earliest.day))
            self.date_to.setDate(QDate(latest.year, latest.month, latest.day))
            self.date_from.blockSignals(False)
            self.date_to.blockSignals(False)

        self._apply_filters()

    @Slot()
    def _apply_filters(self) -> None:
        """Filter and display test files based on current filter settings."""
        type_filter = self.type_filter_combo.currentData()
        date_from = self.date_from.date().toPython()  # datetime.date
        date_to = self.date_to.date().toPython()

        filtered = []
        for f in self._test_files:
            # Test type filter
            if type_filter and f["test_panel_type"] != type_filter:
                continue
            # Date range filter
            if f.get("start_date"):
                if f["start_date"] < date_from or f["start_date"] > date_to:
                    continue
            filtered.append(f)

        self._visible_files = filtered

        # Populate table
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(filtered))

        for row, file_info in enumerate(filtered):
            # Checkbox
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, self.COL_CHECK, check_item)

            # Date
            self.table.setItem(row, self.COL_DATE, QTableWidgetItem(file_info["date"]))

            # Name of File (clickable, underlined, blue)
            filename_item = QTableWidgetItem(file_info["filename"])
            font = QFont()
            font.setUnderline(True)
            filename_item.setFont(font)
            filename_item.setForeground(Qt.blue)
            filename_item.setData(Qt.UserRole, file_info["path"])  # Store full path
            self.table.setItem(row, self.COL_FILENAME, filename_item)

            # Device Name
            self.table.setItem(row, self.COL_NAME, QTableWidgetItem(file_info["device_name"]))

            # Test Type
            self.table.setItem(row, self.COL_TEST_TYPE, QTableWidgetItem(file_info["test_type"]))

            # Conditions
            self.table.setItem(row, self.COL_CONDITIONS, QTableWidgetItem(file_info["conditions"]))

            # Duration
            self.table.setItem(row, self.COL_DURATION, QTableWidgetItem(file_info["duration"]))

            # Summary
            self.table.setItem(row, self.COL_SUMMARY, QTableWidgetItem(file_info["summary"]))

            # View button
            view_item = QTableWidgetItem("View")
            view_font = QFont()
            view_font.setUnderline(True)
            view_item.setFont(view_font)
            view_item.setForeground(Qt.blue)
            view_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_VIEW, view_item)

        self.table.setSortingEnabled(True)
        self.table.viewport().setCursor(QCursor(Qt.ArrowCursor))

        # Update trash button label
        self._update_trash_button()

    def _update_trash_button(self) -> None:
        """Update the Empty Trash button label with count."""
        trash_files = list(self._trash_dir.glob("*.json")) if self._trash_dir.exists() else []
        if trash_files:
            self.empty_trash_btn.setText(f"Empty Trash ({len(trash_files)})...")
            self.empty_trash_btn.setEnabled(True)
        else:
            self.empty_trash_btn.setText("Empty Trash...")
            self.empty_trash_btn.setEnabled(False)

    def _table_key_press(self, event) -> None:
        """Handle key press in table — spacebar toggles checkboxes for selected rows."""
        if event.key() == Qt.Key_Space:
            selected_rows = sorted(set(index.row() for index in self.table.selectedIndexes()))
            for row in selected_rows:
                item = self.table.item(row, self.COL_CHECK)
                if item:
                    if item.checkState() == Qt.Checked:
                        item.setCheckState(Qt.Unchecked)
                    else:
                        item.setCheckState(Qt.Checked)
        else:
            QTableWidget.keyPressEvent(self.table, event)

    @Slot()
    def _clear_filters(self) -> None:
        """Reset all filters to defaults."""
        self.type_filter_combo.setCurrentIndex(0)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_to.setDate(QDate.currentDate())

    def _format_charger_conditions(self, test_config: dict) -> str:
        """Format conditions for battery charger tests showing overall voltage range."""
        starts = []
        ends = []

        # Stage 1 is always enabled
        s1_start = test_config.get('stage1_start')
        s1_end = test_config.get('stage1_end')
        if s1_start is not None:
            starts.append(s1_start)
        if s1_end is not None:
            ends.append(s1_end)

        # Stage 2
        if test_config.get('stage2_enabled'):
            s2_end = test_config.get('stage2_end')
            if s2_end is not None:
                ends.append(s2_end)

        # Stage 3
        if test_config.get('stage3_enabled'):
            s3_end = test_config.get('stage3_end')
            if s3_end is not None:
                ends.append(s3_end)

        if not starts and not ends:
            return "N/A"

        min_v = min(starts) if starts else 0
        max_v = max(ends) if ends else 0
        return f"{min_v:.2f} \u2013 {max_v:.2f} V"

    @Slot(int, int)
    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Handle cell click."""
        if column == self.COL_FILENAME:
            # Load test data
            if 0 <= row < len(self._visible_files):
                file_info = self._visible_files[row]
                file_path = file_info["path"]
                test_panel_type = file_info["test_panel_type"]
                self.json_file_selected.emit(file_path, test_panel_type)
        elif column == self.COL_VIEW:
            # Open JSON file in system text viewer
            if 0 <= row < len(self._visible_files):
                self._open_in_viewer(self._visible_files[row]["path"])

    def _open_in_viewer(self, file_path: str) -> None:
        """Open a JSON file in the system's default text editor."""
        import subprocess
        import platform

        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", "-t", file_path])
            elif system == "Windows":
                subprocess.Popen(["notepad", file_path])
            else:
                subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file: {e}")

    def _get_checked_rows(self) -> list[int]:
        """Get list of row indices that have their checkbox checked."""
        checked = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                checked.append(row)
        return checked

    @Slot()
    def _on_delete(self) -> None:
        """Move checked test file(s) to .trash."""
        rows_to_delete = self._get_checked_rows()

        if not rows_to_delete:
            QMessageBox.information(self, "Delete", "Please check the files you want to delete.")
            return

        # Get file info for selected rows
        files_to_delete = []
        for row in rows_to_delete:
            if 0 <= row < len(self._visible_files):
                files_to_delete.append(self._visible_files[row])

        if not files_to_delete:
            return

        # Move to trash without confirmation
        self._trash_dir.mkdir(parents=True, exist_ok=True)

        failed_files = []
        for file_info in files_to_delete:
            try:
                src = Path(file_info["path"])
                dst = self._trash_dir / src.name
                # Handle name collision in trash
                if dst.exists():
                    stem = dst.stem
                    suffix = dst.suffix
                    counter = 1
                    while dst.exists():
                        dst = self._trash_dir / f"{stem}_{counter}{suffix}"
                        counter += 1
                shutil.move(str(src), str(dst))
            except Exception as e:
                failed_files.append(f"{file_info['filename']}: {e}")

        self.refresh()

        if failed_files:
            QMessageBox.warning(
                self,
                "Delete Error",
                f"Failed to move some files:\n" + "\n".join(failed_files)
            )

    @Slot()
    def _on_empty_trash(self) -> None:
        """Empty the trash folder after confirmation."""
        if not self._trash_dir.exists():
            return

        trash_files = sorted(self._trash_dir.glob("*.json"))
        if not trash_files:
            QMessageBox.information(self, "Empty Trash", "Trash is already empty.")
            return

        # Get date range of trashed files
        dates = []
        for f in trash_files:
            try:
                with open(f, 'r') as fh:
                    data = json.load(fh)
                start_time_str = data.get("summary", {}).get("start_time", "")
                if start_time_str:
                    dt = datetime.fromisoformat(start_time_str)
                    dates.append(dt)
            except Exception:
                pass

        date_range_str = ""
        if dates:
            earliest = min(dates).strftime("%Y-%m-%d")
            latest = max(dates).strftime("%Y-%m-%d")
            if earliest == latest:
                date_range_str = f"\nDate: {earliest}"
            else:
                date_range_str = f"\nDate range: {earliest} to {latest}"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Empty Trash")
        msg_box.setText(f"Permanently delete {len(trash_files)} file(s) from trash?{date_range_str}\n\nThis cannot be undone.")
        msg_box.setIcon(QMessageBox.Question)
        empty_btn = msg_box.addButton("Empty Trash", QMessageBox.DestructiveRole)
        open_btn = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
        msg_box.addButton(QMessageBox.Cancel)
        msg_box.setDefaultButton(QMessageBox.Cancel)
        msg_box.exec()

        if msg_box.clickedButton() == open_btn:
            self._open_trash_folder()
        elif msg_box.clickedButton() == empty_btn:
            for f in trash_files:
                try:
                    f.unlink()
                except Exception:
                    pass
            self._update_trash_button()

    @Slot()
    def _on_restore(self) -> None:
        """Restore files from trash back to the test_data folder."""
        if not self._trash_dir.exists():
            QMessageBox.information(self, "Restore", "Trash folder is empty.")
            return

        from PySide6.QtWidgets import QFileDialog
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files to Restore",
            str(self._trash_dir),
            "JSON Files (*.json)",
        )

        if not files:
            return

        failed = []
        for file_path in files:
            try:
                src = Path(file_path)
                dst = self._test_data_dir / src.name
                if dst.exists():
                    stem = dst.stem
                    suffix = dst.suffix
                    counter = 1
                    while dst.exists():
                        dst = self._test_data_dir / f"{stem}_{counter}{suffix}"
                        counter += 1
                shutil.move(str(src), str(dst))
            except Exception as e:
                failed.append(f"{Path(file_path).name}: {e}")

        self.refresh()

        if failed:
            QMessageBox.warning(
                self,
                "Restore Error",
                f"Failed to restore some files:\n" + "\n".join(failed),
            )

    def _open_trash_folder(self) -> None:
        """Open the .trash folder in the system file manager."""
        import subprocess
        import platform

        self._trash_dir.mkdir(parents=True, exist_ok=True)
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(self._trash_dir)])
            elif system == "Windows":
                subprocess.run(["explorer", str(self._trash_dir)])
            else:
                subprocess.run(["xdg-open", str(self._trash_dir)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder: {e}")

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
            if 0 <= row < len(self._visible_files):
                selected_file = self._visible_files[row]["path"]

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
