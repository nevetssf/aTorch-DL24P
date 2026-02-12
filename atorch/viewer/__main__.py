"""Entry point for Test Viewer application."""

import sys
from PySide6.QtWidgets import QApplication
from .main_window import ViewerMainWindow


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
