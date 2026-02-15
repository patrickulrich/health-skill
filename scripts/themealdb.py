#!/usr/bin/env python3
"""
TheMealDB API client for recipe enrichment.
Free tier uses test key "1" (300+ recipes, 37 cuisines).
Non-critical dependency — all calls wrapped in try/except.
"""

import sys
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
    from urllib.parse import quote_plus
except ImportError:
    urlopen = None
    quote_plus = None

API_BASE = 'https://www.themealdb.com/api/json/v1/1'
_TIMEOUT = 5  # seconds


def _fetch(endpoint):
    """Fetch JSON from TheMealDB API endpoint."""
    if urlopen is None:
        return None
    url = f"{API_BASE}/{endpoint}"
    try:
        req = Request(url, headers={'User-Agent': 'health-skill/1.0'})
        with urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (URLError, json.JSONDecodeError, OSError, TimeoutError):
        return None


def search_meals(query):
    """Search meals by name. Returns list of meal dicts or empty list."""
    data = _fetch(f'search.php?s={quote_plus(query)}')
    if data and data.get('meals'):
        return data['meals']
    return []


def filter_by_cuisine(area):
    """Filter meals by cuisine/area (e.g., 'American', 'Italian')."""
    data = _fetch(f'filter.php?a={quote_plus(area)}')
    if data and data.get('meals'):
        return data['meals']
    return []


def filter_by_category(category):
    """Filter meals by category (e.g., 'Chicken', 'Seafood', 'Vegetarian')."""
    data = _fetch(f'filter.php?c={quote_plus(category)}')
    if data and data.get('meals'):
        return data['meals']
    return []


def filter_by_ingredient(ingredient):
    """Filter meals by main ingredient."""
    data = _fetch(f'filter.php?i={quote_plus(ingredient)}')
    if data and data.get('meals'):
        return data['meals']
    return []


def get_meal_by_id(meal_id):
    """Look up full meal details by TheMealDB ID."""
    data = _fetch(f'lookup.php?i={meal_id}')
    if data and data.get('meals'):
        return data['meals'][0]
    return None


def get_random_meal():
    """Get a random meal from the database."""
    data = _fetch('random.php')
    if data and data.get('meals'):
        return data['meals'][0]
    return None


def list_cuisines():
    """List all available cuisine areas."""
    data = _fetch('list.php?a=list')
    if data and data.get('meals'):
        return [m['strArea'] for m in data['meals']]
    return []


def parse_meal_to_template(meal):
    """
    Convert TheMealDB meal object to our meal_templates format.
    Extracts strIngredient1-20 + strMeasure1-20 into ingredients list.
    Macros set to 0 (must be calculated via our food DB).
    """
    if not meal:
        return None

    # Extract ingredients (TheMealDB uses strIngredient1 through strIngredient20)
    ingredients = []
    for i in range(1, 21):
        ingredient = meal.get(f'strIngredient{i}')
        if ingredient and ingredient.strip():
            measure = meal.get(f'strMeasure{i}', '').strip()
            if measure:
                ingredients.append(f"{measure} {ingredient.strip()}")
            else:
                ingredients.append(ingredient.strip())

    # Map TheMealDB category to meal_types
    category = (meal.get('strCategory') or '').lower()
    if category == 'breakfast':
        meal_types = ['breakfast']
    elif category in ('dessert', 'starter'):
        meal_types = ['snack']
    else:
        meal_types = ['lunch', 'dinner']

    # Map cuisine
    area = (meal.get('strArea') or 'unknown').lower()

    return {
        'name': meal.get('strMeal', 'Unknown'),
        'meal_types': meal_types,
        'calories': 0,
        'protein': 0,
        'carbs': 0,
        'fat': 0,
        'sodium': 0,
        'fiber': 0,
        'ingredients': ingredients,
        'allergens': [],  # Must be determined separately
        'tags': {
            'cuisines': [area],
            'dietary': [],
            'cooking_skill': 'intermediate',
            'budget': 'moderate',
            'prep_time_min': 30,
            'difficulty': 'medium',
            'seasons': ['all'],
        },
        'description': ', '.join(ingredients[:5]),
        'themealdb_id': meal.get('idMeal'),
        'instructions': meal.get('strInstructions', ''),
        'image': meal.get('strMealThumb', ''),
        'video': meal.get('strYoutube', ''),
    }


if __name__ == '__main__':
    # Quick test
    print("Searching for 'chicken'...")
    results = search_meals('chicken')
    print(f"Found {len(results)} meals")
    if results:
        template = parse_meal_to_template(results[0])
        print(f"\nFirst result as template:")
        print(json.dumps(template, indent=2))

    print(f"\nAvailable cuisines: {list_cuisines()}")
