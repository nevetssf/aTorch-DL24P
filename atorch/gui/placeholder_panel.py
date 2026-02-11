"""Placeholder panels for future test automation types."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class PlaceholderPanel(QWidget):
    """Placeholder panel for future test automation features."""

    def __init__(self, title: str, description: str = ""):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        font = title_label.font()
        font.setPointSize(16)
        font.setBold(True)
        title_label.setFont(font)
        layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignCenter)
            desc_label.setStyleSheet("color: gray;")
            layout.addWidget(desc_label)

        coming_soon = QLabel("Coming Soon")
        coming_soon.setAlignment(Qt.AlignCenter)
        coming_soon.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(coming_soon)


class CableResistancePanel(PlaceholderPanel):
    """Placeholder for Cable Resistance testing."""

    def __init__(self):
        super().__init__(
            "Cable Resistance Test",
            "Measure USB cable resistance and voltage drop"
        )


class PowerBankPanel(PlaceholderPanel):
    """Placeholder for Power Bank testing."""

    def __init__(self):
        super().__init__(
            "Power Bank Test",
            "Test power bank capacity, efficiency, and charging"
        )
