#!/usr/bin/env python3
"""Launcher script for PyInstaller builds."""

import sys
import os

# Add the package directory to path for frozen builds
if getattr(sys, 'frozen', False):
    # Running in PyInstaller bundle
    bundle_dir = sys._MEIPASS
    sys.path.insert(0, bundle_dir)

from atorch.main import main

if __name__ == "__main__":
    main()
