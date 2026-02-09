"""Application entry point for aTorch DL24P Control."""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .gui.main_window import MainWindow


def _set_macos_app_name(name: str) -> None:
    """Set the application name in macOS menu bar."""
    try:
        from AppKit import NSApplication, NSApp
        from Foundation import NSBundle

        # Get the shared application
        NSApplication.sharedApplication()

        # Modify the bundle info
        bundle = NSBundle.mainBundle()
        info = bundle.infoDictionary()
        info['CFBundleName'] = name

    except ImportError:
        pass  # PyObjC not available


def main():
    """Main entry point."""
    # Set application name for macOS menu bar (must be before QApplication)
    _set_macos_app_name("DL24/P")

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("DL24/P")
    app.setApplicationDisplayName("DL24/P")
    app.setOrganizationName("aTorch")
    app.setOrganizationDomain("atorch.local")

    # Set dark palette for better plot visibility
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
