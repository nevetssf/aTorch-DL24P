#!/usr/bin/env python3
"""Migrate JSON files from serial_number to manufactured date field."""

import json
from pathlib import Path
from datetime import datetime


def try_parse_date(value: str) -> str | None:
    """Try to parse a string as a date."""
    if not value:
        return None

    # Try common date formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y%m%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            continue

    return None


def migrate_file(file_path: Path) -> bool:
    """Migrate a single JSON file.

    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        modified = False

        # Check battery_info section
        if "battery_info" in data:
            battery_info = data["battery_info"]

            if "serial_number" in battery_info:
                serial_num = battery_info.pop("serial_number")

                # Try to parse as date
                manufactured = try_parse_date(serial_num)
                battery_info["manufactured"] = manufactured
                modified = True
                print(f"  {file_path.name}: serial_number='{serial_num}' -> manufactured={manufactured}")

        if modified:
            # Write back to file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)

        return modified

    except Exception as e:
        print(f"  ERROR: {file_path.name}: {e}")
        return False


def main():
    """Migrate all JSON files in the test data directory."""
    # Test data directory
    test_data_dir = Path.home() / ".atorch" / "test_data"

    if not test_data_dir.exists():
        print(f"Test data directory does not exist: {test_data_dir}")
        return

    # Find all JSON files
    json_files = list(test_data_dir.glob("*.json"))
    print(f"Found {len(json_files)} JSON files in {test_data_dir}")

    if not json_files:
        print("No files to migrate")
        return

    # Migrate each file
    modified_count = 0
    for json_file in json_files:
        if migrate_file(json_file):
            modified_count += 1

    print(f"\nMigration complete: {modified_count}/{len(json_files)} files modified")


if __name__ == "__main__":
    main()
