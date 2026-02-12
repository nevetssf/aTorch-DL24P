# Screenshot Capture Guide

This guide explains how to capture screenshots for the README documentation.

## Quick Start

```bash
# 1. Run the automated screenshot tool
python take_screenshots.py

# 2. Follow the on-screen prompts to capture each screenshot

# 3. Update README.md with screenshot references
python update_readme_screenshots.py

# 4. Commit the screenshots
git add screenshots/ README.md
git commit -m "Add application screenshots to README"
git push
```

## What Gets Captured

The script will help you capture:

### Test Bench (3 screenshots)
1. **test_bench_main.png** - Main interface showing all panels
2. **test_bench_battery_capacity.png** - Battery Capacity test panel
3. **test_bench_plotting.png** - Real-time plotting in action

### Test Viewer (2 screenshots)
4. **test_viewer_main.png** - Main viewer with test file list
5. **test_viewer_comparison.png** - Multiple tests plotted together

## Instructions

### macOS
- Click on the window to capture when prompted
- Make sure window is nicely arranged before clicking
- Window will be captured with transparency/shadow

### Windows
- Position the window
- Press Enter when prompted
- Requires: `pip install pyautogui`

### Linux
- Select the window when prompted with crosshair
- Requires: `sudo apt install scrot`

## Tips for Good Screenshots

1. **Clean Desktop** - Hide other windows and desktop clutter
2. **Good Lighting** - Use the app's default theme
3. **Realistic Data** - Show actual test data, not empty screens
4. **Readable Text** - Ensure all text is legible
5. **Window Size** - Use a reasonable window size (not too small)

## For Test Bench Screenshots

**Screenshot 1 (Main Window):**
- Connect to device
- Show Status Panel with live data
- Show Plot Panel with some curves
- Show Control Panel and Automation Panel

**Screenshot 2 (Battery Capacity):**
- Click on Test Automation tab
- Load a battery preset (e.g., "Canon LP-E6NH")
- Configure test settings (current, voltage cutoff)
- Show the test configuration clearly

**Screenshot 3 (Plotting):**
- Start a test or load historical data
- Show multiple parameters plotted (Voltage, Current, Power)
- Show status bar with elapsed time and readings count

## For Test Viewer Screenshots

**Screenshot 4 (Main Window):**
- Open Test Viewer
- Show Battery Capacity tab with several test files listed
- Check 2-3 test files
- Show the file list with columns (Date, Manufacturer, Name, etc.)

**Screenshot 5 (Comparison):**
- Have multiple tests checked and plotted
- Show different colored curves with legend
- Show the plot controls (X-axis, Y-axis checkboxes)
- Display a meaningful comparison (e.g., different battery tests)

## Manual Alternative

If you prefer to take screenshots manually:

1. Launch applications: `python -m atorch.main` and `python -m atorch.viewer`
2. Arrange windows nicely
3. Use your system's screenshot tool:
   - **macOS:** Cmd+Shift+4, then Space (to capture window)
   - **Windows:** Windows+Shift+S
   - **Linux:** gnome-screenshot or spectacle
4. Save to `screenshots/` directory with the correct filenames
5. Run `python update_readme_screenshots.py` to update README

## Troubleshooting

**"screencapture command not found" (macOS)**
- This should be built-in, but try restarting Terminal

**"pyautogui not installed" (Windows)**
```bash
pip install pyautogui
```

**"scrot not found" (Linux)**
```bash
sudo apt install scrot
# or for Fedora
sudo dnf install scrot
```

**Application won't launch**
- Make sure you're in the project directory
- Ensure virtual environment is activated
- Check that dependencies are installed: `pip install -r requirements.txt`

## After Capturing

1. Review all screenshots in `screenshots/` directory
2. Crop or optimize if needed (keep file sizes reasonable)
3. Run the README update script
4. Preview README.md to verify images display correctly
5. Commit and push

```bash
git add screenshots/ README.md
git commit -m "Add application screenshots to README"
git push
```

The screenshots will now appear in your GitHub repository's README!
