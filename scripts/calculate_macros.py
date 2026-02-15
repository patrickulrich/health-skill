#!/usr/bin/env python3
"""
Calculate macros from food items using comprehensive food database.
Uses database for accurate calorie/macro data including sodium and fiber.
"""

import sys
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)
import json
from config import DIET_DIR, SKILL_DIR
from query_food_db import search_foods, calculate_meal_macros, format_macros

# Beverages tracked for hydration
BEVERAGE_KEYWORDS = [
    'water', 'coffee', 'tea', 'soda', 'juice', 'smoothie',
    'beer', 'wine', 'milk', 'lemonade', 'sparkling',
]


def is_beverage(name):
    """Check if a food name is a beverage."""
    name_lower = name.lower()
    return any(re.search(r'\b' + re.escape(bev) + r'\b', name_lower) for bev in BEVERAGE_KEYWORDS)


def _load_saved_meals():
    """Load saved meal shortcuts from saved_meals.json."""
    path = os.path.join(SKILL_DIR, 'saved_meals.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_meal_shortcut(name, description):
    """Save a meal shortcut to saved_meals.json."""
    path = os.path.join(SKILL_DIR, 'saved_meals.json')
    meals = _load_saved_meals()
    meals[name.lower()] = description
    with open(path, 'w') as f:
        json.dump(meals, f, indent=2)
    return path

def extract_meal_type(text):
    """Extract meal type (breakfast, lunch, dinner, snack) from text."""
    text_lower = text.lower()

    meal_patterns = [
        (r'\bbreakfast\b', 'Breakfast'),
        (r'\blunch\b', 'Lunch'),
        (r'\bdinner\b', 'Dinner'),
        (r'\bsnack\b', 'Snack'),
    ]

    for pattern, meal_name in meal_patterns:
        if re.search(pattern, text_lower):
            return meal_name

    return 'Meal'

def extract_time(text):
    """Extract time from text (e.g., "2:30 PM", "9:00 AM", "2 PM")."""
    # Try HH:MM am/pm first (3 groups)
    match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)', text, re.IGNORECASE)
    if match:
        hour = match.group(1)
        minute = match.group(2)
        period = match.group(3).upper()
        return f"{hour}:{minute} {period}"

    # Try H am/pm (2 groups)
    match = re.search(r'(\d{1,2})\s*(am|pm)', text, re.IGNORECASE)
    if match:
        hour = match.group(1)
        period = match.group(2).upper()
        return f"{hour}:00 {period}"

    return None

WORD_NUMBERS = {
    'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'half': 0.5, 'quarter': 0.25, 'some': 1, 'couple': 2,
}

# Units that imply gram-based scaling
_GRAM_UNITS = {'g', 'gram', 'grams'}
_OZ_UNITS = {'oz', 'ounce', 'ounces'}
_SERVING_UNITS = {'piece', 'pieces', 'slice', 'slices', 'serving', 'servings'}
_VOLUME_UNITS = {'cup', 'cups', 'bowl', 'bowls', 'glass', 'glasses', 'tablespoon', 'tablespoons', 'tbsp'}

_WORD_NUM_PATTERN = '|'.join(re.escape(w) for w in WORD_NUMBERS)


def _extract_quantity_and_unit(before_text, food_text):
    """
    Extract quantity and unit from context immediately before a food keyword.
    Only looks at the nearby context (last ~30 chars of before_text) to avoid
    picking up quantities from earlier, unrelated food items.
    Returns (quantity, unit) tuple.
    """
    # Use only the nearby context to avoid cross-food matching
    # e.g., "200g chicken breast and a cup of " — for "rice", only check "a cup of "
    nearby = before_text[-40:] if len(before_text) > 40 else before_text

    # Pattern 1: numeric with explicit unit — "200g", "3 oz", "2 cups"
    # Search nearby context only
    unit_patterns = [
        (r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\s*$', 'g'),
        (r'(\d+(?:\.\d+)?)\s*(?:oz|ounces?)\s+$', 'oz'),
        (r'(\d+(?:\.\d+)?)\s*(?:cups?)\s+(?:of\s+)?$', 'cups'),
        (r'(\d+(?:\.\d+)?)\s*(?:bowls?)\s+(?:of\s+)?$', 'bowls'),
        (r'(\d+(?:\.\d+)?)\s*(?:glasses?)\s+(?:of\s+)?$', 'glasses'),
        (r'(\d+(?:\.\d+)?)\s*(?:servings?)\s+(?:of\s+)?$', 'servings'),
        (r'(\d+(?:\.\d+)?)\s*(?:pieces?)\s+(?:of\s+)?$', 'pieces'),
        (r'(\d+(?:\.\d+)?)\s*(?:slices?)\s+(?:of\s+)?$', 'slices'),
        (r'(\d+(?:\.\d+)?)\s*(?:tablespoons?|tbsp)\s+(?:of\s+)?$', 'tbsp'),
    ]

    for pattern, unit in unit_patterns:
        match = re.search(pattern, nearby)
        if match:
            try:
                return float(match.group(1)), unit
            except ValueError:
                pass

    # Also check for unit directly attached to the food word: "200g chicken"
    attached = re.match(r'(\d+(?:\.\d+)?)\s*(?:g|grams?)\b', food_text)
    if attached:
        try:
            return float(attached.group(1)), 'g'
        except ValueError:
            pass

    # Pattern 2: word number with unit — "a cup of", "two slices of", "half a"
    word_unit_pattern = r'(?:' + _WORD_NUM_PATTERN + r')\s+(?:an?\s+)?(?:cups?|bowls?|glasses?|servings?|pieces?|slices?)\s+(?:of\s+)?$'
    match = re.search(word_unit_pattern, nearby)
    if match:
        matched = match.group(0)
        for word, val in WORD_NUMBERS.items():
            if re.search(r'\b' + re.escape(word) + r'\b', matched):
                unit_match = re.search(r'(cups?|bowls?|glasses?|servings?|pieces?|slices?)', matched)
                unit = unit_match.group(1) if unit_match else 'servings'
                return val, unit

    # Pattern 3: bare number before food — "2 eggs", "3 chicken breast"
    bare_num = re.search(r'(\d+(?:\.\d+)?)\s*$', nearby)
    if bare_num:
        try:
            return float(bare_num.group(1)), 'servings'
        except ValueError:
            pass

    # Pattern 4: word number before food — "two eggs", "half an avocado", "some broccoli"
    word_num_before = re.search(r'(?:^|\s)(' + _WORD_NUM_PATTERN + r')\s+(?:an?\s+)?$', nearby)
    if word_num_before:
        word = word_num_before.group(1).lower()
        if word in WORD_NUMBERS:
            return WORD_NUMBERS[word], 'servings'

    return 1.0, 'servings'


def parse_food_items(text):
    """
    Parse natural language food text into food items.
    Returns list of (food_name, quantity, unit) triples.
    """
    text_lower = text.lower()

    # Look for common multi-word food phrases first (more specific)
    food_phrases = [
        'chicken breast', 'chicken nugget', 'chicken tender', 'chicken wing',
        'ground beef', 'beef patty', 'ribeye steak', 'sirloin steak',
        'salmon fillet', 'tuna steak', 'white rice', 'brown rice', 'fried rice',
        'wheat bread', 'whole wheat bread', 'mashed potato', 'french fries',
        'greek yogurt', 'cottage cheese', 'cheddar cheese', 'blue cheese',
        'almond milk', 'soy milk', 'oat milk',
        'wendy burger', 'wendy fries', 'wendy nugget',
        'mcdonald burger', 'burger king burger',
        'peanut butter', 'almond butter',
        'apple pie', 'fruit salad',
    ]

    # Then single keywords
    food_keywords = [
        'chicken', 'beef', 'fish', 'salmon', 'tuna', 'steak', 'pork',
        'rice', 'pasta', 'bread', 'potato', 'fries', 'pizza',
        'salad', 'vegetables', 'broccoli', 'spinach', 'peas', 'corn',
        'egg', 'eggs', 'yogurt', 'milk', 'cheese', 'butter', 'avocado',
        'nuts', 'almonds', 'peanuts', 'cashews',
        'burger', 'sandwich', 'taco', 'wrap',
        'wendy', 'mcdonald', 'burger king', 'kfc', 'subway', 'taco bell',
        'coffee', 'tea', 'soda', 'juice',
        'nugget', 'fry', 'cake', 'cookie', 'chips',
        'apple', 'banana', 'orange', 'berries', 'fruit',
    ]

    food_items = []
    found_positions = []  # track (start, end) of matched food text

    def _overlaps(start, end):
        for s, e in found_positions:
            if start < e and end > s:
                return True
        return False

    # First check for multi-word phrases (all occurrences)
    for phrase in food_phrases:
        for match in re.finditer(re.escape(phrase), text_lower):
            idx = match.start()
            end = match.end()
            if not _overlaps(idx, end):
                before_context = text_lower[:idx]
                quantity, unit = _extract_quantity_and_unit(before_context, phrase)
                food_items.append((phrase, quantity, unit))
                found_positions.append((idx, end))

    # Then check for single keywords (all occurrences)
    for keyword in food_keywords:
        for match in re.finditer(re.escape(keyword), text_lower):
            idx = match.start()
            end = match.end()
            if not _overlaps(idx, end):
                before_context = text_lower[:idx]
                quantity, unit = _extract_quantity_and_unit(before_context, keyword)
                food_items.append((keyword, quantity, unit))
                found_positions.append((idx, end))

    return food_items

def analyze_meal(text):
    """
    Analyze meal text and return meal data.
    Expands saved meal shortcuts before parsing.
    Returns dict with meal info and macros.
    """
    meal_type = extract_meal_type(text)
    meal_time = extract_time(text)

    # Expand saved meal shortcuts
    saved_meals = _load_saved_meals()
    expanded = text
    for name, expansion in saved_meals.items():
        if re.search(r'\b' + re.escape(name) + r'\b', expanded, re.IGNORECASE):
            expanded = re.sub(r'\b' + re.escape(name) + r'\b', expansion, expanded, flags=re.IGNORECASE)
            break

    food_items = parse_food_items(expanded)

    # Calculate macros
    totals = calculate_meal_macros(food_items)

    # Track beverages for hydration
    beverages = [item for item in totals.get('items', []) if is_beverage(item['name'])]
    totals['beverages'] = len(beverages)

    # Add meal metadata
    result = {
        'meal_type': meal_type,
        'meal_time': meal_time,
        'food_items': food_items,
        'macros': totals,
    }

    # Check for allergen warnings
    try:
        from scripts.allergy_checker import check_meal_allergens
        warnings = check_meal_allergens(food_items, text)
        result['allergy_warnings'] = warnings
    except ImportError:
        try:
            from allergy_checker import check_meal_allergens
            warnings = check_meal_allergens(food_items, text)
            result['allergy_warnings'] = warnings
        except ImportError:
            result['allergy_warnings'] = []

    return result

def log_meal_to_file(result, date=None):
    """Append meal to today's diet log file."""
    from datetime import datetime
    date = date or datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(DIET_DIR, f'{date}.md')

    os.makedirs(DIET_DIR, exist_ok=True)

    # Create file with header if new
    if not os.path.exists(log_file):
        with open(log_file, 'w') as f:
            f.write(f'# Diet Log - {date}\n\n')

    time_str = result['meal_time'] or datetime.now().strftime('%-I:%M %p')
    macros = result['macros']

    with open(log_file, 'a') as f:
        f.write(f"\n### {result['meal_type']} (~{time_str})\n")
        for item in macros['items']:
            qty = item['quantity']
            unit = item.get('unit', 'servings')
            if unit == 'g':
                f.write(f"- {item['name']} ({qty:.0f}g)\n")
            elif unit == 'oz':
                f.write(f"- {item['name']} ({qty:.0f}oz)\n")
            else:
                f.write(f"- {item['name']} (x{qty})\n")
        f.write(f"  - Est. calories: ~{int(macros['calories'])}\n")
        f.write(f"  - Macros: ~{int(macros['protein'])}g protein, "
                f"~{int(macros['carbs'])}g carbs, ~{int(macros['fat'])}g fat\n")
        if macros['sodium'] > 0:
            f.write(f"  - Sodium: ~{int(macros['sodium'])}mg\n")
        if macros['fiber'] > 0:
            f.write(f"  - Fiber: ~{int(macros['fiber'])}g\n")
        if macros.get('unrecognized'):
            f.write(f"  - Not found: {', '.join(macros['unrecognized'])}\n")
        if macros.get('beverages', 0) > 0:
            f.write(f"  - Hydration: {macros['beverages']} beverage(s)\n")
        if result.get('allergy_warnings'):
            for w in result['allergy_warnings']:
                f.write(f"  - {w['message']}\n")

    return log_file


def update_daily_totals(date=None):
    """Recalculate daily totals from all meals in the day's diet log."""
    from datetime import datetime
    date = date or datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(DIET_DIR, f'{date}.md')

    if not os.path.exists(log_file):
        return

    with open(log_file, 'r') as f:
        content = f.read()

    # Sum up all "Est. calories" and macro lines
    total_cal = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'Est\. calories: ~([\d,]+)', content))
    total_pro = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'~([\d,]+)g protein', content))
    total_carbs = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'~([\d,]+)g carbs', content))
    total_fat = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'~([\d,]+)g fat', content))

    # Sum sodium and fiber from per-meal entries
    total_sodium = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'Sodium: ~([\d,]+)\s*mg', content))
    total_fiber = sum(int(m.group(1).replace(',', '')) for m in re.finditer(r'Fiber: ~([\d,]+)g', content))

    # Count hydration from beverage lines
    total_beverages = sum(int(m.group(1)) for m in re.finditer(r'Hydration: (\d+) beverage', content))

    totals_section = (
        f"\n## Daily Totals\n"
        f"- Calories: ~{total_cal} kcal\n"
        f"- Protein: ~{total_pro}g\n"
        f"- Carbs: ~{total_carbs}g\n"
        f"- Fat: ~{total_fat}g\n"
    )
    if total_sodium > 0:
        totals_section += f"- Sodium: ~{total_sodium}mg\n"
    if total_fiber > 0:
        totals_section += f"- Fiber: ~{total_fiber}g\n"
    if total_beverages > 0:
        totals_section += f"- Hydration: {total_beverages} beverages\n"

    # Remove existing Daily Totals section if present
    content = re.sub(r'\n## Daily Totals\n(?:- .*\n)*', '', content)

    with open(log_file, 'w') as f:
        f.write(content.rstrip('\n') + '\n' + totals_section)


def main():
    """CLI interface for testing."""
    args = sys.argv[1:]
    do_log = '--log' in args
    if do_log:
        args.remove('--log')

    # Handle --save "meal name" flag
    save_name = None
    if '--save' in args:
        save_idx = args.index('--save')
        if save_idx + 1 < len(args):
            save_name = args[save_idx + 1]
            args = args[:save_idx] + args[save_idx + 2:]
        else:
            args.remove('--save')

    if not args:
        print("Usage: calculate_macros.py [--log] [--save 'name'] 'meal description'")
        print("Examples:")
        print("  calculate_macros.py 'I had chicken breast and rice for lunch at 2:30 PM'")
        print("  calculate_macros.py --log 'chicken breast and rice for lunch at 2:30 PM'")
        print("  calculate_macros.py --save 'my usual lunch' 'chicken breast and rice'")
        print("  calculate_macros.py 'Just finished a burger and fries for dinner'")
        sys.exit(1)

    text = ' '.join(args)

    # Save as shortcut if requested
    if save_name:
        path = _save_meal_shortcut(save_name, text)
        print(f"Saved '{save_name}' -> '{text}'")
        print(f"Written to {path}")
        return

    print(f"Analyzing: {text}\n")

    result = analyze_meal(text)

    print(f"Meal Type: {result['meal_type']}")
    if result['meal_time']:
        print(f"Time: {result['meal_time']}")
    print()

    if result['food_items']:
        print("Foods detected:")
        for food_name, quantity, unit in result['food_items']:
            if unit == 'g':
                print(f"  - {food_name} ({quantity:.0f}g)")
            elif unit == 'oz':
                print(f"  - {food_name} ({quantity:.0f}oz)")
            else:
                print(f"  - {food_name} (x{quantity})")
        print()

    macros = result['macros']
    if macros.get('beverages', 0) > 0:
        print(f"Hydration: {macros['beverages']} beverage(s) detected")

    if macros.get('unrecognized'):
        print(f"\nUnrecognized foods: {', '.join(macros['unrecognized'])}")

    if macros['calories'] > 0:
        print(f"Total: {format_macros(macros)}")

        # Allergy warnings to terminal
        if result.get('allergy_warnings'):
            for w in result['allergy_warnings']:
                print(f"  {w['message']}")

        if do_log:
            log_file = log_meal_to_file(result)
            update_daily_totals()
            print(f"\nLogged to {log_file}")

        # Gradual preference learning
        try:
            from scripts.dietary_profile import increment_interactions, get_next_prompt
            increment_interactions()
            prompt = get_next_prompt()
            if prompt:
                print(f"\nTip: {prompt['question']}")
        except ImportError:
            try:
                from dietary_profile import increment_interactions, get_next_prompt
                increment_interactions()
                prompt = get_next_prompt()
                if prompt:
                    print(f"\nTip: {prompt['question']}")
            except ImportError:
                pass
    else:
        print("No foods recognized from database")
        print("Try being more specific with food names (e.g., 'chicken breast' instead of 'chicken')")

if __name__ == '__main__':
    main()
