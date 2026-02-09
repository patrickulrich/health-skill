#!/usr/bin/env python3
"""
Import OpenNutrition dataset into SQLite for fast food lookups.

Downloads the OpenNutrition TSV dataset (or accepts a local path),
parses nutrition_100g JSON, and creates a searchable SQLite database.

Usage:
    python3 import_opennutrition.py                    # download and import
    python3 import_opennutrition.py /path/to/foods.tsv # import from local file
"""

import csv
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from urllib.request import Request, urlopen

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import OPENNUTRITION_DB_PATH

DOWNLOAD_URL = 'https://downloads.opennutrition.app/opennutrition-dataset-2025.1.zip'
BATCH_SIZE = 10_000


def download_dataset(dest_dir):
    """Download and extract the OpenNutrition ZIP. Returns path to TSV file."""
    zip_path = os.path.join(dest_dir, 'opennutrition.zip')
    print(f"Downloading {DOWNLOAD_URL} ...")

    req = Request(DOWNLOAD_URL)
    req.add_header('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) Python/3')
    with urlopen(req, timeout=120) as resp, open(zip_path, 'wb') as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    print(f"Downloaded {os.path.getsize(zip_path) / 1024 / 1024:.1f} MB")

    print("Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        tsv_files = [f for f in zf.namelist() if f.endswith('.tsv')]
        if not tsv_files:
            print("Error: no TSV file found in ZIP")
            sys.exit(1)
        zf.extract(tsv_files[0], dest_dir)
        tsv_path = os.path.join(dest_dir, tsv_files[0])

    os.remove(zip_path)
    print(f"Extracted: {tsv_path}")
    return tsv_path


def parse_nutrition(nutrition_json_str):
    """Parse nutrition_100g JSON string into flat dict."""
    if not nutrition_json_str:
        return {}
    try:
        return json.loads(nutrition_json_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def import_tsv(tsv_path, db_path):
    """Import TSV into SQLite database."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Idempotent: drop and recreate
    cursor.execute('DROP TABLE IF EXISTS opennutrition')
    cursor.execute('''
        CREATE TABLE opennutrition (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            calories REAL,
            protein REAL,
            carbohydrates REAL,
            total_fat REAL,
            sodium REAL,
            dietary_fiber REAL,
            serving TEXT,
            source TEXT,
            type TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_opennutrition_name ON opennutrition(name)')

    print(f"Importing from {tsv_path} ...")
    batch = []
    total = 0
    skipped = 0

    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')

        for row in reader:
            name = row.get('name', '').strip()
            if not name:
                skipped += 1
                continue

            nutrition = parse_nutrition(row.get('nutrition_100g', ''))

            calories = nutrition.get('calories')
            if calories is None:
                skipped += 1
                continue

            try:
                record = (
                    row.get('id', ''),
                    name,
                    float(calories) if calories else 0,
                    float(nutrition.get('protein', 0) or 0),
                    float(nutrition.get('carbohydrates', 0) or 0),
                    float(nutrition.get('total_fat', 0) or 0),
                    float(nutrition.get('sodium', 0) or 0),
                    float(nutrition.get('dietary_fiber', 0) or 0),
                    row.get('serving', ''),
                    row.get('source', ''),
                    row.get('type', ''),
                )
                batch.append(record)
            except (ValueError, TypeError):
                skipped += 1
                continue

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(
                    'INSERT OR REPLACE INTO opennutrition VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    batch
                )
                total += len(batch)
                print(f"  Imported {total:,} rows...")
                batch = []

    # Final batch
    if batch:
        cursor.executemany(
            'INSERT OR REPLACE INTO opennutrition VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            batch
        )
        total += len(batch)

    conn.commit()
    conn.close()

    print(f"\nDone: {total:,} foods imported, {skipped:,} skipped")
    print(f"Database: {db_path} ({os.path.getsize(db_path) / 1024 / 1024:.1f} MB)")


def main():
    if len(sys.argv) > 1:
        tsv_path = sys.argv[1]
        if not os.path.exists(tsv_path):
            print(f"Error: file not found: {tsv_path}")
            sys.exit(1)
    else:
        tmp_dir = tempfile.mkdtemp(prefix='opennutrition_')
        tsv_path = download_dataset(tmp_dir)

    import_tsv(tsv_path, OPENNUTRITION_DB_PATH)


if __name__ == '__main__':
    main()
