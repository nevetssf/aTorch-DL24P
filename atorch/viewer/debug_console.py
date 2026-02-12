"""Debug console window for Test Viewer."""

from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor


class DebugConsole(QDialog):
    """Debug console for viewing application logs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DL24/P Test Viewer - Debug Console")
        self.setMinimumSize(800, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._max_lines = 1000
        self._create_ui()

    def _create_ui(self):
        """Create the UI."""
        layout = QVBoxLayout(self)

        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Menlo", 11))
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.log_text)

        # Controls
        controls = QHBoxLayout()

        self.autoscroll_cb = QCheckBox("Auto-scroll")
        self.autoscroll_cb.setChecked(True)
        controls.addWidget(self.autoscroll_cb)

        controls.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        controls.addWidget(clear_btn)

        layout.addLayout(controls)

    def log(self, message: str, level: str = "INFO"):
        """Add a log message.

        Args:
            message: Message to log
            level: Log level (INFO, ERROR, DEBUG, WARN)
        """
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Color coding by level
        colors = {
            "ERROR": "#f44747",  # Red
            "INFO": "#4ec9b0",   # Cyan
            "DEBUG": "#808080",  # Dark gray
            "WARN": "#dcdcaa",   # Yellow
        }
        color = colors.get(level, "#d4d4d4")

        # Format: [timestamp] [LEVEL] message
        html = f'<span style="color: #808080;">[{timestamp}]</span> '
        html += f'<span style="color: {color};">[{level}]</span> '
        html += f'<span style="color: {color};">{message}</span><br>'

        self.log_text.insertHtml(html)

        # Limit lines to prevent memory growth
        doc = self.log_text.document()
        if doc.lineCount() > self._max_lines:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 100)
            cursor.removeSelectedText()

        # Auto-scroll to bottom if enabled
        if self.autoscroll_cb.isChecked():
            self.log_text.moveCursor(QTextCursor.End)

    def clear(self):
        """Clear all log messages."""
        self.log_text.clear()
