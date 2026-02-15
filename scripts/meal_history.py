#!/usr/bin/env python3
"""
Meal history analysis with ingredient-based cuisine detection and caching.
Provides multi-day food history, cuisine detection, and typical calorie patterns.
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

try:
    from config import DIET_DIR, SKILL_DIR as _SKILL_DIR
except ImportError:
    _SKILL_DIR = SKILL_DIR
    DIET_DIR = os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), 'diet')

_CUISINE_MAP_FILE = os.path.join(_SKILL_DIR, 'ingredient_cuisine_map.json')
_CACHE_FILE = os.path.join(_SKILL_DIR, 'meal_history_cache.json')
_CUISINE_MAP = None

# Regex for food items: "- food_name" or "- food_name (quantity)"
# Matches non-indented list items, stops before summary sections
_FOOD_LINE_RE = re.compile(r'^- ([^\(]+?)(?:\s*\(.*\))?\s*$', re.MULTILINE)

# Meal type header pattern
_MEAL_HEADER_RE = re.compile(r'^### (Breakfast|Lunch|Dinner|Snack|Meal)', re.MULTILINE | re.IGNORECASE)

# Calorie pattern in metadata lines
_CALORIE_RE = re.compile(r'Est\.\s*calories?:\s*~?(\d+)', re.IGNORECASE)


def _load_cuisine_map():
    """Lazy-load and cache the ingredient→cuisine map."""
    global _CUISINE_MAP
    if _CUISINE_MAP is not None:
        return _CUISINE_MAP
    try:
        with open(_CUISINE_MAP_FILE) as f:
            _CUISINE_MAP = json.load(f)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        _CUISINE_MAP = {}
    return _CUISINE_MAP


def parse_foods_from_diet_log(date):
    """
    Parse a single diet log file for the given date.
    Returns list of dicts: [{name, meal_type, calories}]
    """
    diet_file = os.path.join(DIET_DIR, f'{date}.md')
    if not os.path.exists(diet_file):
        return []

    try:
        with open(diet_file, 'r') as f:
            content = f.read()
    except IOError:
        return []

    # Stop before Daily Health Summary section
    summary_idx = content.find('## Daily Health Summary')
    if summary_idx != -1:
        content = content[:summary_idx]

    foods = []
    current_meal_type = 'meal'

    for line in content.split('\n'):
        # Check for meal type header
        header_match = _MEAL_HEADER_RE.match(line)
        if header_match:
            current_meal_type = header_match.group(1).lower()
            continue

        # Skip indented lines (metadata like "  - Est. calories", "  - Macros")
        if line.startswith('  '):
            # But extract calories from metadata
            cal_match = _CALORIE_RE.search(line)
            if cal_match and foods:
                foods[-1]['calories'] = int(cal_match.group(1))
            continue

        # Check for food item line
        food_match = _FOOD_LINE_RE.match(line)
        if food_match:
            food_name = food_match.group(1).strip()
            if food_name:
                foods.append({
                    'name': food_name.lower(),
                    'meal_type': current_meal_type,
                    'calories': None,
                })

    return foods


def detect_cuisines_from_foods(foods):
    """
    Detect cuisines from a list of food items using ingredient substring matching.
    Returns dict: {cuisine: confidence} with confidence capped at 1.0.
    """
    cuisine_map = _load_cuisine_map()
    if not cuisine_map or not foods:
        return {}

    food_names = [f['name'].lower() if isinstance(f, dict) else str(f).lower() for f in foods]
    all_text = ' '.join(food_names)

    detected = {}
    for ingredient, info in cuisine_map.items():
        if ingredient.lower() in all_text:
            cuisine = info['cuisine']
            confidence = info['confidence']
            detected[cuisine] = min(1.0, detected.get(cuisine, 0) + confidence)

    return detected


def get_recent_foods(days=3):
    """
    Get food items from the last N days.
    Returns dict: {by_date, all_food_names, by_meal_type}
    """
    today = datetime.now()
    by_date = {}
    all_food_names = []
    by_meal_type = {}

    for i in range(days):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        foods = parse_foods_from_diet_log(date)
        by_date[date] = foods

        for food in foods:
            all_food_names.append(food['name'])
            meal_type = food.get('meal_type', 'meal')
            by_meal_type.setdefault(meal_type, []).append(food)

    return {
        'by_date': by_date,
        'all_food_names': all_food_names,
        'by_meal_type': by_meal_type,
    }


def get_typical_calories(meal_type, days=7):
    """
    Calculate average calories for a meal type over the last N days.
    Returns int or None if fewer than 2 data points.
    """
    today = datetime.now()
    calorie_values = []

    for i in range(days):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        foods = parse_foods_from_diet_log(date)
        meal_cals = sum(f['calories'] for f in foods
                        if f.get('meal_type') == meal_type and f.get('calories'))
        if meal_cals > 0:
            calorie_values.append(meal_cals)

    if len(calorie_values) < 2:
        return None

    return int(sum(calorie_values) / len(calorie_values))


def build_history(days=3):
    """
    Build full meal history analysis.
    Returns dict with recent_foods, detected_cuisines, today_food_names, typical_calories.
    """
    recent = get_recent_foods(days)
    detected_cuisines = detect_cuisines_from_foods(
        [{'name': name} for name in recent['all_food_names']]
    )

    today = datetime.now().strftime('%Y-%m-%d')
    today_foods = recent['by_date'].get(today, [])
    today_food_names = [f['name'] for f in today_foods]

    typical_calories = {}
    for meal_type in ['breakfast', 'lunch', 'dinner', 'snack']:
        typical_calories[meal_type] = get_typical_calories(meal_type, days=7)

    return {
        'recent_foods': recent,
        'detected_cuisines': detected_cuisines,
        'today_food_names': today_food_names,
        'typical_calories': typical_calories,
        'days_analyzed': days,
        'built_date': today,
    }


def _load_cache():
    """Load cache if it exists and is from today."""
    if not os.path.exists(_CACHE_FILE):
        return None
    try:
        with open(_CACHE_FILE) as f:
            cache = json.load(f)
        if cache.get('built_date') == datetime.now().strftime('%Y-%m-%d'):
            return cache
        return None
    except (json.JSONDecodeError, IOError):
        return None


def _save_cache(history):
    """Save history to cache file with atomic write."""
    try:
        tmp = _CACHE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(history, f, indent=2)
        os.replace(tmp, _CACHE_FILE)
    except IOError:
        pass


def get_history(force_refresh=False, days=3):
    """
    Main public API. Returns cached history or builds fresh.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached and cached.get('days_analyzed') == days:
            return cached

    history = build_history(days)
    _save_cache(history)
    return history
