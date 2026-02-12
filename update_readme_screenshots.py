#!/usr/bin/env python3
"""Update README.md with screenshot references."""

from pathlib import Path


def update_readme_screenshots():
    """Update the Screenshots section in README.md."""
    readme_path = Path("README.md")

    # Read current README
    with open(readme_path, 'r') as f:
        content = f.read()

    # Define new screenshots section
    screenshots_section = """## Screenshots

### Test Bench Application

**Main Interface**
![Test Bench Main Window](screenshots/test_bench_main.png)
*Real-time device control with live plotting and status monitoring*

**Battery Capacity Test**
![Battery Capacity Test](screenshots/test_bench_battery_capacity.png)
*Configure discharge tests with battery presets and voltage cutoff*

**Live Data Plotting**
![Real-time Plotting](screenshots/test_bench_plotting.png)
*Multi-parameter plots with auto-scaling and time tracking*

### Test Viewer Application

**Multi-File Comparison**
![Test Viewer Main](screenshots/test_viewer_main.png)
*Compare multiple test results with publication-quality plots*

**Dataset Analysis**
![Test Comparison](screenshots/test_viewer_comparison.png)
*Color-coded datasets with legend and customizable axes*
"""

    # Replace the screenshots section
    if "## Screenshots" in content:
        # Find the section
        start = content.find("## Screenshots")
        # Find the next ## section
        next_section = content.find("\n## ", start + 1)

        if next_section != -1:
            # Replace the section
            new_content = content[:start] + screenshots_section + "\n" + content[next_section:]
        else:
            # Screenshots is the last section
            new_content = content[:start] + screenshots_section
    else:
        print("Warning: '## Screenshots' section not found in README.md")
        return False

    # Write updated README
    with open(readme_path, 'w') as f:
        f.write(new_content)

    print("✅ README.md updated with screenshot references!")
    return True


if __name__ == "__main__":
    if update_readme_screenshots():
        print("\nNext steps:")
        print("1. Review README.md")
        print("2. git add screenshots/ README.md")
        print("3. git commit -m 'Add application screenshots to README'")
    else:
        print("\nFailed to update README.md")
