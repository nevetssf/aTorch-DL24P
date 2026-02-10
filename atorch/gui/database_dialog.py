"""Database management dialog."""

import os
import subprocess
from pathlib import Path
from datetime import datetime
from platform import system

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QGridLayout,
    QMessageBox,
)
from PySide6.QtCore import Qt

from ..data.database import Database


class DatabaseDialog(QDialog):
    """Dialog for viewing database statistics and management."""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("Database Management")
        self.setModal(True)
        self.setMinimumWidth(500)

        self._setup_ui()
        self._load_statistics()

    def _setup_ui(self) -> None:
        """Setup the user interface."""
        layout = QVBoxLayout(self)

        # Statistics group
        stats_group = QGroupBox("Database Statistics")
        stats_layout = QGridLayout()

        # Location
        stats_layout.addWidget(QLabel("Location:"), 0, 0, Qt.AlignRight)
        self.location_label = QLabel()
        self.location_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.location_label.setWordWrap(True)
        stats_layout.addWidget(self.location_label, 0, 1)

        self.show_folder_btn = QPushButton("Show in Folder")
        self.show_folder_btn.clicked.connect(self._show_in_folder)
        stats_layout.addWidget(self.show_folder_btn, 0, 2)

        # File size
        stats_layout.addWidget(QLabel("File Size:"), 1, 0, Qt.AlignRight)
        self.size_label = QLabel()
        stats_layout.addWidget(self.size_label, 1, 1, 1, 2)

        # Created
        stats_layout.addWidget(QLabel("Created:"), 2, 0, Qt.AlignRight)
        self.created_label = QLabel()
        stats_layout.addWidget(self.created_label, 2, 1, 1, 2)

        # Last modified
        stats_layout.addWidget(QLabel("Last Modified:"), 3, 0, Qt.AlignRight)
        self.modified_label = QLabel()
        stats_layout.addWidget(self.modified_label, 3, 1, 1, 2)

        # Number of sessions
        stats_layout.addWidget(QLabel("Sessions:"), 4, 0, Qt.AlignRight)
        self.sessions_label = QLabel()
        stats_layout.addWidget(self.sessions_label, 4, 1, 1, 2)

        # Number of readings
        stats_layout.addWidget(QLabel("Total Readings:"), 5, 0, Qt.AlignRight)
        self.readings_label = QLabel()
        stats_layout.addWidget(self.readings_label, 5, 1, 1, 2)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

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
        purge_btn.clicked.connect(self._purge_database)
        mgmt_layout.addWidget(purge_btn)

        mgmt_group.setLayout(mgmt_layout)
        layout.addWidget(mgmt_group)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

    def _load_statistics(self) -> None:
        """Load and display database statistics."""
        db_path = Path(self.database.path)

        # Location
        self.location_label.setText(str(db_path))

        if not db_path.exists():
            self.size_label.setText("Database file not found")
            self.created_label.setText("N/A")
            self.modified_label.setText("N/A")
            self.sessions_label.setText("0")
            self.readings_label.setText("0")
            return

        # File size
        size_bytes = db_path.stat().st_size
        size_str = self._format_size(size_bytes)
        self.size_label.setText(size_str)

        # Created time (platform-dependent)
        try:
            if system() == "Darwin":  # macOS
                created_time = db_path.stat().st_birthtime
            else:  # Windows/Linux
                created_time = db_path.stat().st_ctime
            created_dt = datetime.fromtimestamp(created_time)
            self.created_label.setText(created_dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self.created_label.setText("Unknown")

        # Last modified
        modified_time = db_path.stat().st_mtime
        modified_dt = datetime.fromtimestamp(modified_time)
        self.modified_label.setText(modified_dt.strftime("%Y-%m-%d %H:%M:%S"))

        # Count sessions and readings
        try:
            cursor = self.database._conn.cursor()

            # Count sessions
            cursor.execute("SELECT COUNT(*) FROM sessions")
            session_count = cursor.fetchone()[0]
            self.sessions_label.setText(f"{session_count:,}")

            # Count readings
            cursor.execute("SELECT COUNT(*) FROM readings")
            reading_count = cursor.fetchone()[0]
            self.readings_label.setText(f"{reading_count:,}")

        except Exception as e:
            self.sessions_label.setText(f"Error: {e}")
            self.readings_label.setText("N/A")

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def _show_in_folder(self) -> None:
        """Show database file in file browser."""
        db_path = str(self.database.path)

        if system() == "Darwin":  # macOS
            subprocess.run(["open", "-R", db_path])
        elif system() == "Windows":
            subprocess.run(["explorer", f"/select,{db_path}"])
        else:  # Linux
            # Open containing folder
            subprocess.run(["xdg-open", str(Path(db_path).parent)])

    def _purge_database(self) -> None:
        """Purge all data from the database."""
        # First confirmation
        reply = QMessageBox.question(
            self,
            "Purge Database?",
            "Are you sure you want to purge the database?\n\n"
            "This will permanently delete ALL test sessions and readings.\n"
            "This action cannot be undone.\n\n"
            "Exported JSON/CSV files will not be affected.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Second confirmation (type verification)
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self,
            "Confirm Purge",
            "Type 'DELETE' (all caps) to confirm:",
        )

        if not ok or text != "DELETE":
            QMessageBox.information(
                self,
                "Cancelled",
                "Database purge cancelled."
            )
            return

        # Perform purge
        try:
            cursor = self.database._conn.cursor()
            cursor.execute("DELETE FROM readings")
            cursor.execute("DELETE FROM sessions")
            # Reset autoincrement counters
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='readings'")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='sessions'")
            self.database._conn.commit()

            QMessageBox.information(
                self,
                "Success",
                "Database has been purged successfully.\n"
                "All test sessions and readings have been deleted."
            )

            # Reload statistics
            self._load_statistics()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to purge database:\n{e}"
            )
