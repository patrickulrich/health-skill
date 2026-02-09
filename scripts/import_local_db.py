#!/usr/bin/env python3
"""
Download and set up the ComprehensiveFoodDatabase (local SQLite, ~450K foods).

Downloads the full database folder from Mega.nz into data/ComprehensiveFoodDatabase/,
then extracts CompFood.sqlite from CompFoodCSV.zip into the extracted/ subdirectory.

Requirements:
    megatools - install via: sudo apt install megatools (Debian/Ubuntu)
                             brew install megatools (macOS)

Usage:
    python3 import_local_db.py                           # download from Mega + extract
    python3 import_local_db.py /path/to/CompFoodCSV.zip  # extract from local ZIP only
"""

import os
import shutil
import subprocess
import sys
import zipfile

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import DB_PATH

MEGA_FOLDER_URL = 'https://mega.nz/folder/0elAXR6L#QuC3C95Od8wn_j0jcn-d4A'
DATA_DIR = os.path.join(SKILL_DIR, 'data', 'ComprehensiveFoodDatabase')
EXTRACTED_DIR = os.path.join(DATA_DIR, 'extracted', 'CompFoodCSV')
EXPECTED_ZIP = 'CompFoodCSV.zip'
EXPECTED_SQLITE = 'CompFood.sqlite'


def check_megatools():
    """Check if megatools is installed."""
    if shutil.which('megadl'):
        return True
    print("Error: megatools is not installed.")
    print()
    print("Install it with:")
    print("  sudo apt install megatools    # Debian/Ubuntu")
    print("  brew install megatools        # macOS")
    print("  sudo pacman -S megatools      # Arch")
    print()
    print("Then re-run this script.")
    return False


def download_from_mega():
    """Download entire Mega folder into data/ComprehensiveFoodDatabase/."""
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Downloading from {MEGA_FOLDER_URL}")
    print(f"Destination: {DATA_DIR}")
    print("(~1.4 GB total, may take several minutes)\n")

    result = subprocess.run(
        ['megadl', '--path', DATA_DIR, MEGA_FOLDER_URL],
    )

    if result.returncode != 0:
        sys.exit(1)

    # Show what was downloaded
    print("\nDownloaded files:")
    for f in sorted(os.listdir(DATA_DIR)):
        path = os.path.join(DATA_DIR, f)
        if os.path.isfile(path):
            size = os.path.getsize(path) / 1024 / 1024
            print(f"  {f} ({size:.1f} MB)")

    zip_path = os.path.join(DATA_DIR, EXPECTED_ZIP)
    if not os.path.exists(zip_path):
        print(f"\nError: {EXPECTED_ZIP} not found in downloaded files")
        sys.exit(1)

    return zip_path


def extract_sqlite(zip_path):
    """Extract CompFood.sqlite from CompFoodCSV.zip into extracted/CompFoodCSV/."""
    os.makedirs(EXTRACTED_DIR, exist_ok=True)

    print(f"\nExtracting {EXPECTED_SQLITE} from {os.path.basename(zip_path)} ...")

    with zipfile.ZipFile(zip_path, 'r') as zf:
        sqlite_entries = [f for f in zf.namelist() if f.endswith(EXPECTED_SQLITE)]
        if not sqlite_entries:
            print(f"Error: {EXPECTED_SQLITE} not found in ZIP")
            print("ZIP contents:")
            for name in zf.namelist()[:20]:
                print(f"  {name}")
            sys.exit(1)

        sqlite_entry = sqlite_entries[0]
        print(f"  Found: {sqlite_entry}")

        # Extract directly to the extracted directory
        zf.extract(sqlite_entry, EXTRACTED_DIR)
        extracted_path = os.path.join(EXTRACTED_DIR, sqlite_entry)

        # If it extracted into a subdirectory, move it up
        final_path = os.path.join(EXTRACTED_DIR, EXPECTED_SQLITE)
        if extracted_path != final_path:
            shutil.move(extracted_path, final_path)
            # Clean up empty subdirs
            leftover = os.path.dirname(extracted_path)
            if leftover != EXTRACTED_DIR and not os.listdir(leftover):
                os.rmdir(leftover)

    size_mb = os.path.getsize(final_path) / 1024 / 1024
    print(f"  Extracted: {final_path} ({size_mb:.1f} MB)")
    return final_path


def verify_db():
    """Quick verification that the database has the expected tables."""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        tables = {}
        for table in ['usda_non_branded_column', 'usda_branded_column', 'menustat']:
            try:
                cursor.execute(f'SELECT COUNT(*) FROM {table}')
                count = cursor.fetchone()[0]
                tables[table] = count
            except sqlite3.Error:
                tables[table] = 'MISSING'
        conn.close()

        print("\nDatabase verification:")
        total = 0
        for table, count in tables.items():
            if isinstance(count, int):
                print(f"  {table}: {count:,} rows")
                total += count
            else:
                print(f"  {table}: {count}")
        print(f"  Total: {total:,} foods")
        return total > 0
    except sqlite3.Error as e:
        print(f"\nVerification failed: {e}")
        return False


def main():
    if os.path.exists(DB_PATH):
        size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
        print(f"Database already exists at {DB_PATH} ({size_mb:.1f} MB)")
        print("Delete it first if you want to re-import.")
        verify_db()
        return

    if len(sys.argv) > 1:
        zip_path = sys.argv[1]
        if not os.path.exists(zip_path):
            print(f"Error: file not found: {zip_path}")
            sys.exit(1)
    else:
        if not check_megatools():
            sys.exit(1)
        zip_path = download_from_mega()

    extract_sqlite(zip_path)
    verify_db()
    print("\nDone.")


if __name__ == '__main__':
    main()
