#!/usr/bin/env python3
"""Automated screenshot capture for README documentation.

This script launches the Test Bench and Test Viewer applications,
waits for them to load, and captures screenshots for documentation.
"""

import subprocess
import time
import sys
from pathlib import Path
import platform


def create_screenshots_dir():
    """Create screenshots directory if it doesn't exist."""
    screenshots_dir = Path("screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    return screenshots_dir


def take_screenshot(output_path: Path, window_name: str = None):
    """Take a screenshot using platform-specific tools.

    Args:
        output_path: Path to save the screenshot
        window_name: Optional window name to capture (macOS only)
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        # Use screencapture with interactive window selection
        if window_name:
            # Try to capture specific window by name
            cmd = ["screencapture", "-l", "$(osascript -e 'tell app \"System Events\" to id of window 1 of process \"python\"')", str(output_path)]
        else:
            # Interactive mode - user selects window
            cmd = ["screencapture", "-W", str(output_path)]

        print(f"Taking screenshot: {output_path.name}")
        print("Click on the window you want to capture...")
        subprocess.run(cmd)

    elif system == "Windows":
        # Use PyAutoGUI for cross-platform screenshots
        try:
            import pyautogui
            print(f"Taking screenshot: {output_path.name}")
            print("Position the window and press Enter...")
            input()
            screenshot = pyautogui.screenshot()
            screenshot.save(str(output_path))
        except ImportError:
            print("Please install pyautogui: pip install pyautogui")
            sys.exit(1)

    elif system == "Linux":
        # Use scrot or gnome-screenshot
        try:
            cmd = ["scrot", "-s", str(output_path)]
            print(f"Taking screenshot: {output_path.name}")
            print("Select the window to capture...")
            subprocess.run(cmd)
        except FileNotFoundError:
            print("Please install scrot: sudo apt install scrot")
            sys.exit(1)


def launch_test_bench():
    """Launch the Test Bench application."""
    print("\n=== Launching Test Bench ===")
    proc = subprocess.Popen(
        [sys.executable, "-m", "load_test_bench.main"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("Waiting for application to load (8 seconds)...")
    time.sleep(8)
    return proc


def launch_test_viewer():
    """Launch the Test Viewer application."""
    print("\n=== Launching Test Viewer ===")
    proc = subprocess.Popen(
        [sys.executable, "-m", "load_test_bench.viewer"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("Waiting for application to load (5 seconds)...")
    time.sleep(5)
    return proc


def main():
    """Main screenshot capture workflow."""
    print("aTorch Screenshot Capture Tool")
    print("=" * 50)
    print("\nThis script will help you capture screenshots for the README.")
    print("Instructions:")
    print("1. Each application will launch automatically")
    print("2. Wait for the prompt, then click on the window to capture")
    print("3. Arrange the window nicely before clicking")
    print("\nPress Enter to start...")
    input()

    screenshots_dir = create_screenshots_dir()

    # Test Bench Screenshots
    test_bench_proc = None
    try:
        test_bench_proc = launch_test_bench()

        print("\n--- Screenshot 1: Test Bench Main Window ---")
        print("Show the main interface with all panels visible")
        take_screenshot(screenshots_dir / "test_bench_main.png")

        print("\n--- Screenshot 2: Battery Capacity Test ---")
        print("Navigate to Battery Capacity panel, show it configured")
        print("Press Enter when ready...")
        input()
        take_screenshot(screenshots_dir / "test_bench_battery_capacity.png")

        print("\n--- Screenshot 3: Real-time Plot ---")
        print("Show a test in progress with live plotting")
        print("Press Enter when ready...")
        input()
        take_screenshot(screenshots_dir / "test_bench_plotting.png")

    finally:
        if test_bench_proc:
            print("\nClosing Test Bench...")
            test_bench_proc.terminate()
            time.sleep(2)

    # Test Viewer Screenshots
    test_viewer_proc = None
    try:
        test_viewer_proc = launch_test_viewer()

        print("\n--- Screenshot 4: Test Viewer Main Window ---")
        print("Show the viewer with multiple tests selected and plotted")
        take_screenshot(screenshots_dir / "test_viewer_main.png")

        print("\n--- Screenshot 5: Test Viewer Comparison ---")
        print("Show comparison of multiple battery tests")
        print("Press Enter when ready...")
        input()
        take_screenshot(screenshots_dir / "test_viewer_comparison.png")

    finally:
        if test_viewer_proc:
            print("\nClosing Test Viewer...")
            test_viewer_proc.terminate()
            time.sleep(2)

    print("\n" + "=" * 50)
    print("✅ Screenshot capture complete!")
    print(f"\nScreenshots saved to: {screenshots_dir.absolute()}")
    print("\nFiles created:")
    for screenshot in sorted(screenshots_dir.glob("*.png")):
        print(f"  - {screenshot.name}")

    print("\nNext steps:")
    print("1. Review the screenshots")
    print("2. Optimize/crop if needed")
    print("3. Update README.md to reference them")
    print("4. Add screenshots/ to git and commit")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nScreenshot capture cancelled.")
        sys.exit(1)
