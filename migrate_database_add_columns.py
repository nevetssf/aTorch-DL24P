#!/usr/bin/env python3
"""Add missing columns to database readings table.

Adds:
- fan_speed_rpm INTEGER
- load_r_ohm REAL
- battery_r_ohm REAL
"""

import sqlite3
from pathlib import Path


def migrate_database():
    """Add missing columns to existing database."""
    db_path = Path.home() / ".atorch" / "tests.db"

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("No migration needed - database will be created with new schema")
        return

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check which columns need to be added
    cursor.execute("PRAGMA table_info(readings)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    columns_to_add = []
    if 'fan_speed_rpm' not in existing_columns:
        columns_to_add.append(('fan_speed_rpm', 'INTEGER DEFAULT 0'))
    if 'load_r_ohm' not in existing_columns:
        columns_to_add.append(('load_r_ohm', 'REAL'))
    if 'battery_r_ohm' not in existing_columns:
        columns_to_add.append(('battery_r_ohm', 'REAL'))

    if not columns_to_add:
        print("✓ All columns already exist!")
        conn.close()
        return

    # Add missing columns
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE readings ADD COLUMN {col_name} {col_type}")
            print(f"✓ Added column: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"  Column {col_name} already exists, skipping")
            else:
                raise

    conn.commit()
    conn.close()

    print("\n✅ Database migration complete!")
    print(f"Added {len(columns_to_add)} new columns to readings table")


if __name__ == "__main__":
    migrate_database()
