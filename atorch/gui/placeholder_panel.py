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


class BatteryChargerPanel(PlaceholderPanel):
    """Placeholder for Battery Charger testing."""

    def __init__(self):
        super().__init__(
            "Battery Charger Test",
            "Test and analyze battery charger performance"
        )


class CableResistancePanel(PlaceholderPanel):
    """Placeholder for Cable Resistance testing."""

    def __init__(self):
        super().__init__(
            "Cable Resistance Test",
            "Measure USB cable resistance and voltage drop"
        )


class ChargerPanel(PlaceholderPanel):
    """Placeholder for Charger (power adapter) testing."""

    def __init__(self):
        super().__init__(
            "Charger Test",
            "Test power adapter output and efficiency"
        )
