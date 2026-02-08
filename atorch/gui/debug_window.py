"""Debug console window for connection diagnostics."""

from datetime import datetime
from typing import Optional
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QCheckBox,
    QLabel,
    QLineEdit,
    QGroupBox,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor


class DebugWindow(QDialog):
    """Debug console showing connection activity."""

    send_raw_command = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Debug Console")
        self.setMinimumSize(700, 500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._create_ui()
        self._max_lines = 1000

    def _create_ui(self) -> None:
        """Create the debug window UI."""
        layout = QVBoxLayout(self)

        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Menlo", 11))
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        )
        layout.addWidget(self.log_text)

        # Raw command input
        cmd_group = QGroupBox("Send Raw Command (hex bytes, e.g., FF 55 11 02 01 00 00 00 00 57)")
        cmd_layout = QHBoxLayout(cmd_group)

        self.cmd_input = QLineEdit()
        self.cmd_input.setFont(QFont("Menlo", 11))
        self.cmd_input.setPlaceholderText("FF 55 11 02 01 00 00 00 00 57")
        self.cmd_input.returnPressed.connect(self._send_raw_command)
        cmd_layout.addWidget(self.cmd_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_raw_command)
        cmd_layout.addWidget(send_btn)

        layout.addWidget(cmd_group)

        # Controls
        controls = QHBoxLayout()

        self.show_raw_cb = QCheckBox("Show Raw Bytes")
        self.show_raw_cb.setChecked(True)
        controls.addWidget(self.show_raw_cb)

        self.show_parsed_cb = QCheckBox("Show Parsed Data")
        self.show_parsed_cb.setChecked(True)
        controls.addWidget(self.show_parsed_cb)

        self.autoscroll_cb = QCheckBox("Auto-scroll")
        self.autoscroll_cb.setChecked(True)
        controls.addWidget(self.autoscroll_cb)

        controls.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        controls.addWidget(clear_btn)

        layout.addLayout(controls)

    def log(self, message: str, level: str = "INFO") -> None:
        """Add a log message.

        Args:
            message: The message to log
            level: Log level (INFO, SEND, RECV, ERROR, DEBUG)
        """
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Color based on level
        colors = {
            "INFO": "#d4d4d4",   # Gray
            "SEND": "#569cd6",   # Blue
            "RECV": "#4ec9b0",   # Cyan
            "ERROR": "#f44747",  # Red
            "DEBUG": "#808080",  # Dark gray
            "PARSE": "#dcdcaa", # Yellow
        }
        color = colors.get(level, "#d4d4d4")

        html = f'<span style="color: #808080;">[{timestamp}]</span> '
        html += f'<span style="color: {color};">[{level}]</span> '
        html += f'<span style="color: {color};">{message}</span><br>'

        self.log_text.insertHtml(html)

        # Limit lines
        doc = self.log_text.document()
        if doc.lineCount() > self._max_lines:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 100)
            cursor.removeSelectedText()

        # Auto-scroll
        if self.autoscroll_cb.isChecked():
            self.log_text.moveCursor(QTextCursor.End)

    def log_bytes(self, data: bytes, direction: str) -> None:
        """Log raw bytes.

        Args:
            data: The bytes to log
            direction: 'SEND' or 'RECV'
        """
        if not self.show_raw_cb.isChecked():
            return

        hex_str = " ".join(f"{b:02X}" for b in data)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        self.log(f"{hex_str}  |  {ascii_str}", direction)

    def log_parsed(self, message: str) -> None:
        """Log parsed data."""
        if self.show_parsed_cb.isChecked():
            self.log(message, "PARSE")

    def log_error(self, message: str) -> None:
        """Log an error."""
        self.log(message, "ERROR")

    def log_info(self, message: str) -> None:
        """Log info message."""
        self.log(message, "INFO")

    def log_debug(self, message: str) -> None:
        """Log debug message."""
        self.log(message, "DEBUG")

    def clear(self) -> None:
        """Clear the log."""
        self.log_text.clear()

    def _send_raw_command(self) -> None:
        """Parse and send raw hex command."""
        hex_str = self.cmd_input.text().strip()
        if not hex_str:
            return

        try:
            # Parse hex string (accepts "FF 55" or "FF55" or "0xFF 0x55")
            hex_str = hex_str.replace("0x", "").replace(",", " ")
            byte_strs = hex_str.split()
            data = bytes([int(b, 16) for b in byte_strs])

            self.log(f"Sending raw command: {len(data)} bytes", "INFO")
            self.send_raw_command.emit(data)
            self.cmd_input.clear()

        except ValueError as e:
            self.log_error(f"Invalid hex format: {e}")
