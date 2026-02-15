"""Entry point for Test Viewer application."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from .main_window import ViewerMainWindow


def _set_macos_app_name(name: str) -> None:
    """Set the application name in macOS menu bar and dock."""
    try:
        from AppKit import NSApplication, NSRunningApplication
        from Foundation import NSBundle, NSProcessInfo

        # Get the shared application
        app = NSApplication.sharedApplication()

        # Set process name (affects dock name)
        process = NSProcessInfo.processInfo()
        process.setProcessName_(name)

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
                info['CFBundleIdentifier'] = 'com.atorch.dl24p.testviewer'
                # Also set the localized name
                info['CFBundleExecutable'] = name

        # Also set the activation policy to ensure proper dock behavior
        app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular

    except ImportError:
        pass  # PyObjC not available
    except Exception:
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
    _set_macos_app_name("DL24/P Test Viewer")

    app = QApplication(sys.argv)
    app.setApplicationName("DL24/P Test Viewer")
    app.setApplicationDisplayName("DL24/P Test Viewer")
    app.setOrganizationName("aTorch")

    # Set application icon
    icon_path = Path(__file__).parent.parent.parent / "resources" / "icons" / "app_icon.icns"
    if icon_path.exists():
        # Set Qt window icon
        app.setWindowIcon(QIcon(str(icon_path)))
        # Set macOS dock icon
        _set_macos_dock_icon(str(icon_path))

    window = ViewerMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
