#!/usr/bin/env python3
"""Migrate parameter names in all JSON test files to standardized naming with units.

Changes:
- voltage → voltage_v
- current → current_a
- power → power_w
- runtime_seconds → runtime_s
- temperature_c → mosfet_temp_c
- ext_temperature_c → ext_temp_c
- fan_rpm → fan_speed_rpm (if present)
- load_resistance_ohm → load_r_ohm (if present)
- battery_resistance_ohm → battery_r_ohm (if present)
- Add mosfet_temp_c as null if missing
- Add ext_temp_c as null if missing
"""

import json
from pathlib import Path
from datetime import datetime


def migrate_reading(reading: dict) -> tuple[dict, list[str]]:
    """Migrate a single reading dict to new parameter names.

    Returns:
        (migrated_reading, list_of_changes)
    """
    changes = []
    migrated = reading.copy()

    # voltage → voltage_v
    if "voltage" in migrated and "voltage_v" not in migrated:
        migrated["voltage_v"] = migrated.pop("voltage")
        changes.append("voltage → voltage_v")

    # current → current_a
    if "current" in migrated and "current_a" not in migrated:
        migrated["current_a"] = migrated.pop("current")
        changes.append("current → current_a")

    # power → power_w
    if "power" in migrated and "power_w" not in migrated:
        migrated["power_w"] = migrated.pop("power")
        changes.append("power → power_w")

    # runtime_seconds → runtime_s
    if "runtime_seconds" in migrated and "runtime_s" not in migrated:
        migrated["runtime_s"] = migrated.pop("runtime_seconds")
        changes.append("runtime_seconds → runtime_s")

    # temperature_c → mosfet_temp_c
    if "temperature_c" in migrated and "mosfet_temp_c" not in migrated:
        migrated["mosfet_temp_c"] = migrated.pop("temperature_c")
        changes.append("temperature_c → mosfet_temp_c")

    # ext_temperature_c → ext_temp_c
    if "ext_temperature_c" in migrated and "ext_temp_c" not in migrated:
        migrated["ext_temp_c"] = migrated.pop("ext_temperature_c")
        changes.append("ext_temperature_c → ext_temp_c")

    # fan_rpm → fan_speed_rpm
    if "fan_rpm" in migrated and "fan_speed_rpm" not in migrated:
        migrated["fan_speed_rpm"] = migrated.pop("fan_rpm")
        changes.append("fan_rpm → fan_speed_rpm")

    # load_resistance_ohm → load_r_ohm
    if "load_resistance_ohm" in migrated and "load_r_ohm" not in migrated:
        migrated["load_r_ohm"] = migrated.pop("load_resistance_ohm")
        changes.append("load_resistance_ohm → load_r_ohm")

    # battery_resistance_ohm → battery_r_ohm
    if "battery_resistance_ohm" in migrated and "battery_r_ohm" not in migrated:
        migrated["battery_r_ohm"] = migrated.pop("battery_resistance_ohm")
        changes.append("battery_resistance_ohm → battery_r_ohm")

    # Add missing temperature fields as null
    if "mosfet_temp_c" not in migrated:
        migrated["mosfet_temp_c"] = None
        changes.append("added mosfet_temp_c (null)")

    if "ext_temp_c" not in migrated:
        migrated["ext_temp_c"] = None
        changes.append("added ext_temp_c (null)")

    return migrated, changes


def migrate_file(file_path: Path) -> tuple[bool, int, list[str]]:
    """Migrate a single JSON file.

    Returns:
        (modified, num_readings_migrated, unique_changes)
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {file_path.name}: {e}")
        return False, 0, []

    modified = False
    all_changes = set()
    readings_migrated = 0

    # Migrate readings array
    if "readings" in data and isinstance(data["readings"], list):
        new_readings = []
        for reading in data["readings"]:
            migrated_reading, changes = migrate_reading(reading)
            new_readings.append(migrated_reading)
            if changes:
                modified = True
                readings_migrated += 1
                all_changes.update(changes)

        if modified:
            data["readings"] = new_readings

    # Write back if modified
    if modified:
        # Create backup
        backup_path = file_path.with_suffix('.json.backup')
        if not backup_path.exists():
            with open(backup_path, 'w') as f:
                json.dump(data, f, indent=2)

        # Write migrated data
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

        return True, readings_migrated, sorted(all_changes)

    return False, 0, []


def main():
    """Main migration function."""
    print("=" * 70)
    print("Parameter Name Migration Script")
    print("=" * 70)
    print("\nThis script will migrate parameter names in all JSON test files")
    print("to use standardized naming with unit suffixes.\n")
    print("Changes:")
    print("  - temperature_c → mosfet_temp_c")
    print("  - ext_temperature_c → ext_temp_c")
    print("  - fan_rpm → fan_speed_rpm")
    print("  - load_resistance_ohm → load_r_ohm")
    print("  - battery_resistance_ohm → battery_r_ohm")
    print("\nBackups will be created as .json.backup files.")
    print("=" * 70)

    # Get test data directory
    test_data_dir = Path.home() / ".atorch" / "test_data"

    if not test_data_dir.exists():
        print(f"\n❌ Test data directory not found: {test_data_dir}")
        return

    # Find all JSON files
    json_files = sorted(test_data_dir.glob("*.json"))

    if not json_files:
        print(f"\n❌ No JSON files found in {test_data_dir}")
        return

    print(f"\nFound {len(json_files)} JSON files in {test_data_dir}")
    print("\nPress Enter to start migration, or Ctrl+C to cancel...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled")
        return

    print("\nMigrating files...")
    print("-" * 70)

    total_modified = 0
    total_readings = 0
    failed_files = []

    for json_file in json_files:
        try:
            modified, readings_migrated, changes = migrate_file(json_file)

            if modified:
                total_modified += 1
                total_readings += readings_migrated
                print(f"✓ {json_file.name}")
                print(f"  Migrated {readings_migrated} readings")
                for change in changes:
                    print(f"    • {change}")
            else:
                print(f"• {json_file.name} - no changes needed")

        except Exception as e:
            failed_files.append((json_file.name, str(e)))
            print(f"✗ {json_file.name} - ERROR: {e}")

    print("-" * 70)
    print(f"\n✅ Migration complete!")
    print(f"  • Files modified: {total_modified}/{len(json_files)}")
    print(f"  • Total readings migrated: {total_readings}")

    if failed_files:
        print(f"\n❌ Failed files ({len(failed_files)}):")
        for filename, error in failed_files:
            print(f"  • {filename}: {error}")

    print(f"\n💾 Backups saved as .json.backup files")
    print(f"📁 Location: {test_data_dir}")

    print("\n" + "=" * 70)
    print("Next steps:")
    print("1. Test the applications with migrated data")
    print("2. If everything works, delete .backup files")
    print("3. Commit the updated code changes")
    print("=" * 70)


if __name__ == "__main__":
    main()
