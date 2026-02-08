"""Application entry point for aTorch DL24P Control."""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .gui.main_window import MainWindow


def main():
    """Main entry point."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("aTorch DL24P Control")
    app.setOrganizationName("aTorch")
    app.setOrganizationDomain("atorch.local")

    # Set dark palette for better plot visibility
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
