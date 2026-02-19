"""Application entry point for Load Test Bench."""

import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from .gui.main_window import MainWindow


def _set_macos_app_name(name: str) -> None:
    """Set the application name in macOS menu bar and dock."""
    try:
        from AppKit import NSApplication, NSRunningApplication
        from Foundation import NSBundle, NSProcessInfo
        import objc

        # Get the shared application
        app = NSApplication.sharedApplication()

        # Set process name (affects dock name)
        process = NSProcessInfo.processInfo()
        process.setProcessName_(name)

        # Also set via NSRunningApplication
        running_app = NSRunningApplication.currentApplication()

        # Modify the bundle info to set both menu bar and dock names
        bundle = NSBundle.mainBundle()
        if bundle:
            info = bundle.infoDictionary()
            if info:
                # CFBundleName controls the menu bar name
                info['CFBundleName'] = name
                # CFBundleDisplayName controls the dock name on hover
                info['CFBundleDisplayName'] = name
                # Set the bundle identifier
                info['CFBundleIdentifier'] = 'com.loadtestbench.app'
                # Also set the localized name
                info['CFBundleExecutable'] = name

        # Also set the activation policy to ensure proper dock behavior
        app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular

    except ImportError:
        pass  # PyObjC not available
    except Exception as e:
        pass  # Silently fail if any issue


def _set_macos_dock_icon(icon_path: str) -> None:
    """Set the application icon in macOS dock."""
    try:
        from AppKit import NSApplication, NSImage

        # Load the icon
        ns_image = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if ns_image:
            # Set as application icon (dock icon)
            NSApplication.sharedApplication().setApplicationIconImage_(ns_image)

    except ImportError:
        pass  # PyObjC not available


def main():
    """Main entry point."""
    # Set application name for macOS menu bar (must be before QApplication)
    _set_macos_app_name("Load Test Bench")

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Load Test Bench")
    app.setApplicationDisplayName("Load Test Bench")
    app.setOrganizationName("LoadTestBench")
    app.setOrganizationDomain("loadtestbench.local")

    # Set application icon
    icon_path = Path(__file__).parent.parent / "resources" / "icons" / "app_icon.icns"
    if icon_path.exists():
        # Set Qt window icon
        app.setWindowIcon(QIcon(str(icon_path)))
        # Set macOS dock icon
        _set_macos_dock_icon(str(icon_path))

    # Set dark palette for better plot visibility
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
