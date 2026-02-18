"""Entry point for Test Viewer application."""

import sys
from PySide6.QtWidgets import QApplication
from atorch.viewer.main_window import ViewerMainWindow


def main():
    """Main entry point for Test Viewer."""
    app = QApplication(sys.argv)
    app.setApplicationName("Load Test Viewer")
    app.setOrganizationName("LoadTestBench")

    window = ViewerMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
