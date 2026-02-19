#!/usr/bin/env python3
"""Simple launcher for Test Viewer application."""

import sys
from pathlib import Path

# Add parent directory to path so we can import load_test_bench
sys.path.insert(0, str(Path(__file__).parent))

from load_test_bench.viewer.main_window import ViewerMainWindow
from PySide6.QtWidgets import QApplication


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("Load Test Viewer")
    app.setOrganizationName("LoadTestBench")

    window = ViewerMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
