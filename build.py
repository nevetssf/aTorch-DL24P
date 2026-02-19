#!/usr/bin/env python3
"""PyInstaller build script for Load Test Bench."""

import platform
import subprocess
import sys
from pathlib import Path


def build():
    """Build the application using PyInstaller."""
    # Determine platform-specific options
    system = platform.system()

    # Base PyInstaller command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=Load Test Bench",
        "--windowed",
        "--onefile",
        "--clean",
        "-y",  # Overwrite output directory without confirmation
    ]

    # Add hidden imports
    hidden_imports = [
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "pyqtgraph",
        "numpy",
        "pandas",
        "serial",
        "serial.tools.list_ports",
        "hid",
    ]

    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")

    # Add data files (resources directory)
    resources_dir = Path("resources")
    if resources_dir.exists():
        cmd.append(f"--add-data={resources_dir}:resources")

    # Add USB prepare script (needed for macOS device initialization)
    usb_prepare = Path("usb_prepare.py")
    if usb_prepare.exists():
        cmd.append(f"--add-data={usb_prepare}:.")

    # Platform-specific options
    if system == "Darwin":
        # macOS
        icon_path = Path("resources/icons/app_icon.icns")
        if icon_path.exists():
            cmd.append(f"--icon={icon_path}")
        cmd.append("--osx-bundle-identifier=com.loadtestbench.app")
    elif system == "Windows":
        # Windows
        icon_path = Path("resources/icons/atorch.ico")
        if icon_path.exists():
            cmd.append(f"--icon={icon_path}")
        # Add version info
        cmd.append("--version-file=version_info.txt")

    # Add the launcher script (handles package imports for frozen builds)
    cmd.append("run_load_test_bench.py")

    print(f"Building for {system}...")
    print(f"Command: {' '.join(cmd)}")

    # Run PyInstaller
    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode == 0:
        print("\nBuild successful!")
        if system == "Darwin":
            print("Output: dist/Load Test Bench.app")
        else:
            print("Output: dist/Load Test Bench.exe")
    else:
        print("\nBuild failed!")
        sys.exit(1)


def create_version_info():
    """Create Windows version info file."""
    version_info = '''
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0),
    prodvers=(0, 1, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'LoadTestBench'),
            StringStruct('FileDescription', 'Load Test Bench'),
            StringStruct('FileVersion', '0.1.0'),
            StringStruct('InternalName', 'load-test-bench'),
            StringStruct('LegalCopyright', 'MIT License'),
            StringStruct('OriginalFilename', 'Load Test Bench.exe'),
            StringStruct('ProductName', 'Load Test Bench'),
            StringStruct('ProductVersion', '0.1.0'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''
    with open("version_info.txt", "w") as f:
        f.write(version_info)


if __name__ == "__main__":
    if platform.system() == "Windows":
        create_version_info()
    build()
