#!/usr/bin/env python3
"""PyInstaller build script for aTorch DL24P Control."""

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
        "--name=aTorch DL24P",
        "--windowed",
        "--onefile",
        "--clean",
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
    ]

    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")

    # Platform-specific options
    if system == "Darwin":
        # macOS
        icon_path = Path("resources/icons/atorch.icns")
        if icon_path.exists():
            cmd.append(f"--icon={icon_path}")
        cmd.append("--osx-bundle-identifier=com.atorch.dl24p")
    elif system == "Windows":
        # Windows
        icon_path = Path("resources/icons/atorch.ico")
        if icon_path.exists():
            cmd.append(f"--icon={icon_path}")
        # Add version info
        cmd.append("--version-file=version_info.txt")

    # Add the main script
    cmd.append("atorch/main.py")

    print(f"Building for {system}...")
    print(f"Command: {' '.join(cmd)}")

    # Run PyInstaller
    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode == 0:
        print("\nBuild successful!")
        if system == "Darwin":
            print("Output: dist/aTorch DL24P.app")
        else:
            print("Output: dist/aTorch DL24P.exe")
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
            StringStruct('CompanyName', 'aTorch'),
            StringStruct('FileDescription', 'aTorch DL24P Control'),
            StringStruct('FileVersion', '0.1.0'),
            StringStruct('InternalName', 'atorch-dl24p'),
            StringStruct('LegalCopyright', 'MIT License'),
            StringStruct('OriginalFilename', 'aTorch DL24P.exe'),
            StringStruct('ProductName', 'aTorch DL24P Control'),
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
