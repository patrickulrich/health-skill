#!/usr/bin/env python3
"""
Query food databases for calorie/macro data.
Supports multiple data sources: local SQLite, OpenNutrition, and USDA API.
Results are merged by relevance across all enabled sources.
"""

import sqlite3
import sys
import os
import re
import json
from urllib.request import Request, urlopen
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import DB_PATH, USDA_API_KEY, FOOD_SOURCES, OPENNUTRITION_DB_PATH


def _search_local_db(query, limit=20):
    """
    Search the local ComprehensiveFoodDatabase SQLite.
    Returns list of (description, calories, protein, carbs, fat, sodium, fiber, source, serving_size_g) tuples.
    """
    if not os.path.exists(DB_PATH):
        return []

    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.Error:
        return []

    cursor = conn.cursor()
    results = []

    tables = [
        ('usda_non_branded_column', 'USDA'),
        ('usda_branded_column', 'Branded'),
        ('menustat', 'Restaurant')
    ]

    for table_name, source in tables:
        try:
            if table_name == 'usda_non_branded_column':
                cursor.execute(f"""
                    SELECT description, energy_amount, protein_amount, carb_amount, fat_amount, '0', fiber_amount, serving_size
                    FROM {table_name}
                    WHERE description LIKE ?
                    LIMIT ?
                """, (f'%{query}%', limit))
            elif table_name == 'usda_branded_column':
                cursor.execute(f"""
                    SELECT description, energy_amount, protein_amount, carb_amount, fat_amount, sodiumna_amount, fiber_amount, serving_size, serving_size_unit
                    FROM {table_name}
                    WHERE description LIKE ?
                    LIMIT ?
                """, (f'%{query}%', limit))
            else:  # menustat
                cursor.execute(f"""
                    SELECT item_description, energy_amount, protein_amount, carb_amount, fat_amount, sodium_amount, fiber_amount, serving_size, serving_size_unit
                    FROM {table_name}
                    WHERE item_description LIKE ?
                    LIMIT ?
                """, (f'%{query}%', limit))

            for row in cursor.fetchall():
                if row[0] and row[1]:
                    try:
                        # Parse serving size in grams
                        if table_name == 'usda_non_branded_column':
                            # serving_size column is already in grams
                            serving_g = float(row[7]) if row[7] else 100.0
                        else:
                            # branded and menustat have serving_size + serving_size_unit
                            raw_size = float(row[7]) if row[7] else 100.0
                            unit = (row[8] or 'g').lower().strip()
                            if unit in ('ml', 'g', 'gram', 'grams'):
                                serving_g = raw_size
                            elif unit in ('oz', 'ounce', 'ounces'):
                                serving_g = raw_size * 28.35
                            else:
                                serving_g = raw_size  # assume grams
                        results.append((
                            row[0],
                            float(row[1]),
                            float(row[2]) if row[2] else 0,
                            float(row[3]) if row[3] else 0,
                            float(row[4]) if row[4] else 0,
                            float(row[5]) if row[5] else 0,
                            float(row[6]) if row[6] else 0,
                            source,
                            serving_g
                        ))
                    except (ValueError, TypeError):
                        continue

        except sqlite3.Error:
            continue

    conn.close()
    return results


def _parse_serving_grams(serving_text):
    """Parse serving text to extract grams. Returns 100.0 as default."""
    if not serving_text:
        return 100.0
    try:
        # Try JSON format first (e.g., '{"metric": {"quantity": 85, "unit": "g"}}')
        data = json.loads(serving_text)
        metric = data.get('metric', {})
        qty = metric.get('quantity')
        if qty:
            return float(qty)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Try plain text like "100g" or "85 g"
    m = re.search(r'(\d+(?:\.\d+)?)\s*g\b', serving_text)
    if m:
        return float(m.group(1))
    return 100.0


def _search_opennutrition(query, limit=20):
    """
    Search the OpenNutrition SQLite database.
    Returns list of (description, calories, protein, carbs, fat, sodium, fiber, source, serving_size_g) tuples.
    """
    if not os.path.exists(OPENNUTRITION_DB_PATH):
        return []

    try:
        conn = sqlite3.connect(OPENNUTRITION_DB_PATH)
    except sqlite3.Error:
        return []

    results = []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, calories, protein, carbohydrates, total_fat, sodium, dietary_fiber, serving
            FROM opennutrition
            WHERE name LIKE ?
            LIMIT ?
        """, (f'%{query}%', limit))

        for row in cursor.fetchall():
            if row[0] and row[1] is not None:
                try:
                    serving_g = _parse_serving_grams(row[7])
                    results.append((
                        row[0],
                        float(row[1]),
                        float(row[2]) if row[2] else 0,
                        float(row[3]) if row[3] else 0,
                        float(row[4]) if row[4] else 0,
                        float(row[5]) if row[5] else 0,
                        float(row[6]) if row[6] else 0,
                        'OpenNutrition',
                        serving_g
                    ))
                except (ValueError, TypeError):
                    continue
    except sqlite3.Error:
        pass
    finally:
        conn.close()

    return results


# USDA FoodData Central nutrient IDs
_USDA_NUTRIENT_IDS = {
    1008: 'calories',
    1003: 'protein',
    1005: 'carbs',
    1004: 'fat',
    1093: 'sodium',
    1079: 'fiber',
}


def _search_usda_api(query, limit=20):
    """
    Search USDA FoodData Central REST API.
    Returns list of (description, calories, protein, carbs, fat, sodium, fiber, source, serving_size_g) tuples.
    """
    if not USDA_API_KEY:
        return []

    url = (
        f'https://api.nal.usda.gov/fdc/v1/foods/search'
        f'?api_key={USDA_API_KEY}'
        f'&query={quote_plus(query)}'
        f'&pageSize={limit}'
    )

    try:
        req = Request(url)
        req.add_header('Accept', 'application/json')
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (URLError, HTTPError, OSError, json.JSONDecodeError, ValueError):
        return []

    results = []
    for food in data.get('foods', []):
        description = food.get('description', '')
        if not description:
            continue

        nutrients = {}
        for nutrient in food.get('foodNutrients', []):
            nid = nutrient.get('nutrientId')
            if nid in _USDA_NUTRIENT_IDS:
                nutrients[_USDA_NUTRIENT_IDS[nid]] = nutrient.get('value', 0) or 0

        calories = nutrients.get('calories', 0)
        if not calories:
            continue

        serving_g = float(food.get('servingSize', 100) or 100)

        results.append((
            description,
            float(calories),
            float(nutrients.get('protein', 0)),
            float(nutrients.get('carbs', 0)),
            float(nutrients.get('fat', 0)),
            float(nutrients.get('sodium', 0)),
            float(nutrients.get('fiber', 0)),
            'USDA-API',
            serving_g
        ))

    return results


# Map source names to search function names (looked up at call time for testability)
_SOURCE_FUNCTION_NAMES = {
    'local_db': '_search_local_db',
    'opennutrition': '_search_opennutrition',
    'usda_api': '_search_usda_api',
}


def search_foods(query, limit=5):
    """
    Search for foods across all enabled sources, merge by relevance.
    Returns list of (description, calories, protein, carbs, fat, sodium, fiber, source, serving_size_g) tuples.
    """
    query_lower = query.lower()
    all_results = []

    for source_name in FOOD_SOURCES:
        fn_name = _SOURCE_FUNCTION_NAMES.get(source_name)
        if fn_name:
            search_fn = globals()[fn_name]
            all_results.extend(search_fn(query, limit=20))

    # Sort by relevance (query match position in description, then shorter descriptions first)
    all_results.sort(key=lambda x: (
        x[0].lower().find(query_lower) if x[0].lower().find(query_lower) >= 0 else 1000,
        len(x[0])
    ))

    return all_results[:limit]


def calculate_meal_macros(food_items):
    """
    Calculate total macros from list of food items.
    food_items: list of (food_name, quantity, unit) triples or (food_name, quantity) tuples
    Returns dict with total macros.
    """
    totals = {
        'calories': 0,
        'protein': 0,
        'carbs': 0,
        'fat': 0,
        'sodium': 0,
        'fiber': 0,
        'items': [],
        'unrecognized': []
    }

    for item in food_items:
        if len(item) == 3:
            food_name, quantity, unit = item
        else:
            food_name, quantity = item
            unit = 'servings'

        results = search_foods(food_name, limit=1)

        if results:
            food_data = results[0]
            name, energy, protein, carbs, fat, sodium, fiber, source, serving_g = food_data

            # Determine multiplier based on unit
            if unit == 'g':
                multiplier = quantity / serving_g if serving_g > 0 else quantity / 100
            elif unit == 'oz':
                grams = quantity * 28.35
                multiplier = grams / serving_g if serving_g > 0 else quantity
            else:
                # pieces, cups, servings, bowls — use raw multiplier
                multiplier = quantity

            totals['calories'] += energy * multiplier
            totals['protein'] += protein * multiplier
            totals['carbs'] += carbs * multiplier
            totals['fat'] += fat * multiplier
            totals['sodium'] += sodium * multiplier
            totals['fiber'] += fiber * multiplier
            totals['items'].append({
                'name': name,
                'quantity': quantity,
                'unit': unit,
                'source': source
            })
        else:
            totals['unrecognized'].append(food_name)

    return totals


def format_macros(totals):
    """Format macro totals for display."""
    lines = [
        f"~{int(totals['calories'])} kcal",
        f"~{int(totals['protein'])}g protein",
        f"~{int(totals['carbs'])}g carbs",
        f"~{int(totals['fat'])}g fat",
    ]

    if totals['sodium'] > 0:
        lines.append(f"~{int(totals['sodium'])}mg sodium")

    if totals['fiber'] > 0:
        lines.append(f"~{int(totals['fiber'])}g fiber")

    return ' | '.join(lines)


def main():
    """CLI interface for testing."""
    if len(sys.argv) < 2:
        print("Usage: query_food_db.py 'food description'")
        print("Examples:")
        print("  query_food_db.py 'chicken breast'")
        print("  query_food_db.py 'Wendy burger'")
        print("  query_food_db.py 'brown rice'")
        sys.exit(1)

    query = ' '.join(sys.argv[1:])
    print(f"Searching for: {query}")
    print(f"Sources: {', '.join(FOOD_SOURCES)}\n")

    results = search_foods(query, limit=5)

    if not results:
        print("No foods found")
        sys.exit(1)

    print("Results:")
    for i, (desc, cal, pro, carb, fat, sod, fib, source, serv_g) in enumerate(results, 1):
        print(f"\n{i}. {desc[:80]}... ({source}, serving: {serv_g:.0f}g)")
        print(f"   {int(cal)} kcal | P: {int(pro)}g | C: {int(carb)}g | F: {int(fat)}g", end='')
        if sod > 0:
            print(f" | Na: {int(sod)}mg", end='')
        if fib > 0:
            print(f" | Fiber: {int(fib)}g", end='')
        print()

if __name__ == '__main__':
    main()
