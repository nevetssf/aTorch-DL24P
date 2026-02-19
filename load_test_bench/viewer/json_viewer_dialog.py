"""Dialog for viewing raw JSON test data."""

import json
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class JsonViewerDialog(QDialog):
    """Dialog showing raw JSON test data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JSON Data Viewer")
        self.setMinimumSize(800, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)

        # File label
        self.file_label = QLabel()
        self.file_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.file_label)

        # JSON text display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Menlo", 11))
        self.text_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.text_edit)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def load_json_file(self, file_path: Path):
        """Load and display a JSON file.

        Args:
            file_path: Path to the JSON file
        """
        self.file_label.setText(f"File: {file_path.name}")
        self.setWindowTitle(f"JSON Data Viewer - {file_path.name}")

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            # Pretty-print JSON with indentation
            json_str = json.dumps(data, indent=2)
            self.text_edit.setPlainText(json_str)

        except Exception as e:
            self.text_edit.setPlainText(f"Error loading JSON file:\n{e}")

    def _copy_to_clipboard(self):
        """Copy JSON to clipboard."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
