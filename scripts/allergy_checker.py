#!/usr/bin/env python3
"""
Allergen detection for meal logging.
Checks food items against user allergens using allergen_map.json.
"""

import sys
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

# Module-level cache (same pattern as exercise_db.py)
_ALLERGEN_MAP = None


def load_allergen_map():
    """Load and cache allergen map from allergen_map.json."""
    global _ALLERGEN_MAP
    if _ALLERGEN_MAP is not None:
        return _ALLERGEN_MAP

    map_file = os.path.join(SKILL_DIR, 'allergen_map.json')
    try:
        with open(map_file) as f:
            _ALLERGEN_MAP = json.load(f)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        _ALLERGEN_MAP = {}

    return _ALLERGEN_MAP


def check_meal_allergens(food_items, raw_text):
    """
    Check parsed food items and raw meal text against user allergens.

    Args:
        food_items: list of (food_name, quantity, unit) tuples from parse_food_items
        raw_text: original meal description text

    Returns:
        list of warning dicts with: allergen, trigger, match_type, severity, message
    """
    try:
        from dietary_profile import get_allergies
    except ImportError:
        from scripts.dietary_profile import get_allergies

    user_allergies = get_allergies()
    if not user_allergies:
        return []

    allergen_map = load_allergen_map()
    warnings = []
    seen = set()  # Avoid duplicate warnings

    raw_lower = raw_text.lower()

    for allergen in user_allergies:
        allergen_lower = allergen.lower()
        if allergen_lower not in allergen_map:
            continue

        entry = allergen_map[allergen_lower]
        keywords = entry.get('keywords', [])
        also_check = entry.get('also_check', [])
        severity = entry.get('severity', 'moderate')

        # Check each parsed food item against keywords (direct match)
        for item in food_items:
            food_name = item[0].lower() if isinstance(item, (list, tuple)) else item.lower()
            for keyword in keywords:
                if keyword.lower() in food_name:
                    warn_key = (allergen_lower, keyword.lower())
                    if warn_key not in seen:
                        seen.add(warn_key)
                        warnings.append({
                            'allergen': allergen_lower,
                            'trigger': keyword,
                            'match_type': 'keyword',
                            'severity': severity,
                            'message': f"ALLERGY WARNING: {keyword} contains {allergen_lower}",
                        })

        # Check raw text against also_check entries (contextual match)
        for context_item in also_check:
            if context_item.lower() in raw_lower:
                warn_key = (allergen_lower, context_item.lower())
                if warn_key not in seen:
                    seen.add(warn_key)
                    warnings.append({
                        'allergen': allergen_lower,
                        'trigger': context_item,
                        'match_type': 'contextual',
                        'severity': severity,
                        'message': f"ALLERGY WARNING: {context_item} may contain {allergen_lower}",
                    })

    # Sort by severity (high first)
    severity_order = {'high': 0, 'moderate': 1, 'low': 2}
    warnings.sort(key=lambda w: severity_order.get(w['severity'], 9))

    return warnings


def check_single_food(food_name, allergens=None):
    """
    Check a single food name against specific allergens or user allergens.
    Used by meal planner for template filtering.

    Args:
        food_name: name of food to check
        allergens: list of allergens to check against (None = use user profile)

    Returns:
        list of matching allergen names
    """
    if allergens is None:
        try:
            from dietary_profile import get_allergies
        except ImportError:
            from scripts.dietary_profile import get_allergies
        allergens = get_allergies()

    if not allergens:
        return []

    allergen_map = load_allergen_map()
    matches = []
    food_lower = food_name.lower()

    for allergen in allergens:
        allergen_lower = allergen.lower()
        if allergen_lower not in allergen_map:
            continue

        entry = allergen_map[allergen_lower]
        keywords = entry.get('keywords', [])
        also_check = entry.get('also_check', [])

        for keyword in keywords + also_check:
            if keyword.lower() in food_lower:
                matches.append(allergen_lower)
                break

    return matches


def format_warnings(warnings):
    """Format warning list into human-readable string."""
    if not warnings:
        return ""

    lines = []
    for w in warnings:
        severity_prefix = "!!!" if w['severity'] == 'high' else "!!"
        lines.append(f"  {severity_prefix} {w['message']}")

    return '\n'.join(lines)


if __name__ == '__main__':
    # Quick test
    print("Allergen map loaded:", bool(load_allergen_map()))
    print("Allergens available:", list(load_allergen_map().keys()))
