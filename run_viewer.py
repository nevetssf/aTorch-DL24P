#!/usr/bin/env python3
"""Simple launcher for Test Viewer application."""

import sys
from pathlib import Path

# Add parent directory to path so we can import atorch
sys.path.insert(0, str(Path(__file__).parent))

from atorch.viewer.main_window import ViewerMainWindow
from PySide6.QtWidgets import QApplication


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("DL24/P Test Viewer")
    app.setOrganizationName("aTorch")

    window = ViewerMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
