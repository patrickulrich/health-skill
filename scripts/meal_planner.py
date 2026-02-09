#!/usr/bin/env python3
"""
Meal suggestion engine with scoring, filtering, and seasonal awareness.
Suggests meals based on remaining macros, user preferences, and dietary profile.
"""

import sys
import os
import json
import random
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

from config import DIET_DIR, GOALS, DIETARY_PROFILE, SKILL_DIR as _SKILL_DIR, calculate_calorie_target

try:
    from meal_history import get_history, detect_cuisines_from_foods
except ImportError:
    from scripts.meal_history import get_history, detect_cuisines_from_foods

# Season mapping by month
_MONTH_TO_SEASON = {
    1: 'winter', 2: 'winter', 3: 'spring', 4: 'spring', 5: 'spring',
    6: 'summer', 7: 'summer', 8: 'summer', 9: 'fall', 10: 'fall',
    11: 'fall', 12: 'winter',
}

# Difficulty limits per meal type
_DIFFICULTY_BY_MEAL_TYPE = {
    'breakfast': ['easy'],
    'lunch': ['easy', 'medium'],
    'dinner': ['easy', 'medium', 'hard'],
    'snack': ['easy'],
}

# Scoring weight profiles for variety modes (all weights sum to 1.0)
_VARIETY_WEIGHTS = {
    'explore': {
        'calorie_fit': 0.25, 'protein_fit': 0.20, 'sodium_ok': 0.05,
        'cuisine_bonus': 0.05, 'cuisine_diverse': 0.15, 'novelty_bonus': 0.15,
        'repetition_penalty': 0.05, 'familiarity_bonus': 0.00,
        'pattern_match': 0.00, 'random_factor': 0.10,
    },
    'balanced': {
        'calorie_fit': 0.25, 'protein_fit': 0.20, 'sodium_ok': 0.08,
        'cuisine_bonus': 0.10, 'cuisine_diverse': 0.08, 'novelty_bonus': 0.07,
        'repetition_penalty': 0.05, 'familiarity_bonus': 0.05,
        'pattern_match': 0.05, 'random_factor': 0.07,
    },
    'consistent': {
        'calorie_fit': 0.25, 'protein_fit': 0.20, 'sodium_ok': 0.08,
        'cuisine_bonus': 0.15, 'cuisine_diverse': 0.00, 'novelty_bonus': 0.00,
        'repetition_penalty': 0.02, 'familiarity_bonus': 0.15,
        'pattern_match': 0.10, 'random_factor': 0.05,
    },
}


def load_meal_templates():
    """Load curated meal templates from meal_templates.json."""
    path = os.path.join(_SKILL_DIR, 'meal_templates.json')
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get('meals', [])
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        return []


def get_remaining_macros(date=None):
    """
    Calculate remaining macro budget for today.
    Returns dict with remaining calories, protein, carbs, fat, sodium.
    """
    date = date or datetime.now().strftime('%Y-%m-%d')

    # Targets
    cal_target = calculate_calorie_target() or 2000
    weight = GOALS.get('weight_kg')
    protein_per_kg = GOALS.get('protein_per_kg', 0.8)
    protein_target = int(weight * protein_per_kg) if weight else 75
    sodium_limit = GOALS.get('sodium_limit_mg', 2300)

    # Rough macro targets (from calories if not explicit)
    # Standard split: 30% protein, 40% carbs, 30% fat
    carb_target = int(cal_target * 0.40 / 4)  # 4 cal/g
    fat_target = int(cal_target * 0.30 / 9)   # 9 cal/g

    # Get today's consumption
    consumed = {'calories': 0, 'protein': 0, 'carbs': 0, 'fat': 0, 'sodium': 0}
    try:
        from generate_daily_summary import parse_diet_log
        diet = parse_diet_log(date)
        if diet:
            consumed['calories'] = diet.get('calories_consumed', 0)
            consumed['protein'] = diet.get('protein', 0)
            consumed['carbs'] = diet.get('carbs', 0)
            consumed['fat'] = diet.get('fat', 0)
            consumed['sodium'] = diet.get('sodium', 0)
    except ImportError:
        pass

    # Infer meals remaining from time of day
    hour = datetime.now().hour
    if hour < 10:
        meals_remaining = 3  # breakfast, lunch, dinner
    elif hour < 14:
        meals_remaining = 2  # lunch, dinner
    elif hour < 18:
        meals_remaining = 1  # dinner
    else:
        meals_remaining = 1  # late snack/meal

    remaining = {
        'calories': max(0, cal_target - consumed['calories']),
        'protein': max(0, protein_target - consumed['protein']),
        'carbs': max(0, carb_target - consumed['carbs']),
        'fat': max(0, fat_target - consumed['fat']),
        'sodium': max(0, sodium_limit - consumed['sodium']),
        'cal_target': cal_target,
        'protein_target': protein_target,
        'carb_target': carb_target,
        'fat_target': fat_target,
        'sodium_limit': sodium_limit,
        'consumed': consumed,
        'meals_remaining': meals_remaining,
    }

    return remaining


def _get_current_season():
    """Get current season based on month."""
    return _MONTH_TO_SEASON.get(datetime.now().month, 'all')


def filter_templates(templates, profile=None, meal_type=None):
    """
    Filter meal templates by allergens, restrictions, dislikes, skill, budget, season, difficulty.
    NEVER relaxes allergen or restriction filters.
    Returns (filtered_list, relaxed_filters) tuple.
    """
    if profile is None:
        profile = dict(DIETARY_PROFILE)

    allergies = [a.lower() for a in (profile.get('allergies') or [])]
    restrictions = [r.lower() for r in (profile.get('dietary_restrictions') or [])]
    dislikes = [d.lower() for d in (profile.get('dislikes') or [])]
    cuisine_prefs = [c.lower() for c in (profile.get('cuisine_preferences') or [])]
    cooking_skill = (profile.get('cooking_skill') or '').lower()
    budget = (profile.get('budget') or '').lower()

    season = _get_current_season()

    # Skill levels ordered
    skill_levels = ['basic', 'intermediate', 'advanced']
    skill_idx = skill_levels.index(cooking_skill) if cooking_skill in skill_levels else 2

    # Budget levels ordered
    budget_levels = ['budget', 'moderate', 'premium']
    budget_idx = budget_levels.index(budget) if budget in budget_levels else 2

    # Allowed difficulties for meal type
    allowed_difficulties = _DIFFICULTY_BY_MEAL_TYPE.get(
        (meal_type or '').lower(), ['easy', 'medium', 'hard']
    )

    def _passes_hard_filters(meal):
        """Allergens and restrictions are NEVER relaxed."""
        # Allergen filter
        if allergies:
            meal_allergens = [a.lower() for a in (meal.get('allergens') or [])]
            if any(a in meal_allergens for a in allergies):
                return False

        # Dietary restriction filter
        if restrictions:
            dietary_tags = [t.lower() for t in (meal.get('tags', {}).get('dietary') or [])]
            for restriction in restrictions:
                # Map restriction to required tag
                restriction_tag_map = {
                    'vegetarian': 'vegetarian',
                    'vegan': 'vegan',
                    'gluten-free': 'gluten_free',
                    'gluten_free': 'gluten_free',
                    'dairy-free': 'dairy_free',
                    'dairy_free': 'dairy_free',
                    'keto': 'keto',
                    'low_sodium': 'low_sodium',
                }
                required_tag = restriction_tag_map.get(restriction)
                if required_tag and required_tag not in dietary_tags:
                    return False

        # Meal type filter
        if meal_type:
            if meal_type.lower() not in [t.lower() for t in (meal.get('meal_types') or [])]:
                return False

        return True

    def _passes_soft_filters(meal, relax=None):
        """Soft filters can be progressively relaxed."""
        relax = relax or set()
        tags = meal.get('tags', {})

        # Dislikes filter
        if 'dislikes' not in relax and dislikes:
            ingredients = [i.lower() for i in (meal.get('ingredients') or [])]
            if any(d in ' '.join(ingredients) for d in dislikes):
                return False

        # Season filter
        if 'seasons' not in relax:
            meal_seasons = [s.lower() for s in (tags.get('seasons') or ['all'])]
            if 'all' not in meal_seasons and season not in meal_seasons:
                return False

        # Difficulty filter
        if 'difficulty' not in relax:
            difficulty = (tags.get('difficulty') or 'easy').lower()
            if difficulty not in allowed_difficulties:
                return False

        # Cooking skill filter
        if 'cooking_skill' not in relax and cooking_skill:
            meal_skill = (tags.get('cooking_skill') or 'basic').lower()
            meal_skill_idx = skill_levels.index(meal_skill) if meal_skill in skill_levels else 0
            if meal_skill_idx > skill_idx:
                return False

        # Budget filter
        if 'budget' not in relax and budget:
            meal_budget = (tags.get('budget') or 'budget').lower()
            meal_budget_idx = budget_levels.index(meal_budget) if meal_budget in budget_levels else 0
            if meal_budget_idx > budget_idx:
                return False

        return True

    # First pass: hard + soft filters
    filtered = [m for m in templates if _passes_hard_filters(m) and _passes_soft_filters(m)]

    # Progressive relaxation if too few results
    relaxation_order = ['budget', 'cooking_skill', 'seasons', 'difficulty', 'dislikes']
    relaxed = set()

    for relax_key in relaxation_order:
        if len(filtered) >= 3:
            break
        relaxed.add(relax_key)
        filtered = [m for m in templates if _passes_hard_filters(m) and _passes_soft_filters(m, relaxed)]

    return filtered, relaxed


def score_template(template, remaining, profile=None, history=None):
    """
    Score a meal template against remaining macros, preferences, and history.
    Uses variety mode from profile to select scoring weights.
    Higher score = better match.
    """
    if profile is None:
        profile = dict(DIETARY_PROFILE)
    if history is None:
        history = {}

    # Select variety mode weights
    variety_mode = (profile.get('meal_variety') or 'balanced').lower()
    if variety_mode not in _VARIETY_WEIGHTS:
        variety_mode = 'balanced'
    weights = _VARIETY_WEIGHTS[variety_mode]

    meals_remaining = remaining.get('meals_remaining', 1)
    per_meal_cal = remaining['calories'] / max(meals_remaining, 1)
    per_meal_protein = remaining['protein'] / max(meals_remaining, 1)

    # 1. Calorie fit (0-1)
    if per_meal_cal > 0:
        calorie_fit = max(0, 1.0 - abs(template['calories'] - per_meal_cal) / per_meal_cal)
    else:
        calorie_fit = 0.5 if template['calories'] < 300 else 0.0

    # 2. Protein fit (0-1)
    if per_meal_protein > 0:
        protein_fit = max(0, 1.0 - abs(template['protein'] - per_meal_protein) / per_meal_protein)
    else:
        protein_fit = 0.5

    # 3. Sodium OK (1.0 or 0.0)
    sodium_ok = 1.0 if template.get('sodium', 0) <= remaining.get('sodium', 2300) else 0.0

    # 4. Cuisine preference bonus (0 or 1)
    cuisine_bonus = 0.0
    cuisine_prefs = [c.lower() for c in (profile.get('cuisine_preferences') or [])]
    template_cuisines = [c.lower() for c in (template.get('tags', {}).get('cuisines') or [])]
    if cuisine_prefs and any(c in cuisine_prefs for c in template_cuisines):
        cuisine_bonus = 1.0

    # 5. Cuisine diversity (0 or 1) — template cuisine NOT in recent detected cuisines
    cuisine_diverse = 0.0
    detected_cuisines = history.get('detected_cuisines', {})
    if template_cuisines and detected_cuisines:
        if not any(c in detected_cuisines for c in template_cuisines):
            cuisine_diverse = 1.0
    elif template_cuisines and not detected_cuisines:
        cuisine_diverse = 1.0  # No history = everything is diverse

    # 6. Novelty bonus — fraction of template ingredients NOT seen in recent foods
    novelty_bonus = 0.0
    recent_food_names = history.get('recent_foods', {}).get('all_food_names', [])
    template_ingredients = [i.lower() for i in (template.get('ingredients') or [])]
    if template_ingredients:
        if recent_food_names:
            novel_count = sum(1 for ing in template_ingredients
                              if not any(ing in food for food in recent_food_names))
            novelty_bonus = novel_count / len(template_ingredients)
        else:
            novelty_bonus = 1.0  # No history = everything is novel

    # 7. Repetition penalty — 1.0 if no overlap with today's foods, decreases with overlap
    repetition_penalty = 1.0
    today_food_names = history.get('today_food_names', [])
    if today_food_names and template_ingredients:
        overlap = sum(1 for f in today_food_names
                      if any(f in ing for ing in template_ingredients))
        if overlap > 0:
            repetition_penalty = max(0, 1.0 - overlap / len(template_ingredients))

    # 8. Familiarity bonus — fraction of template ingredients SEEN in recent foods
    familiarity_bonus = 0.0
    if template_ingredients and recent_food_names:
        familiar_count = sum(1 for ing in template_ingredients
                             if any(ing in food for food in recent_food_names))
        familiarity_bonus = familiar_count / len(template_ingredients)

    # 9. Pattern match — how well template calories match typical for this meal type
    pattern_match = 0.0
    typical_calories = history.get('typical_calories', {})
    if template.get('meal_types'):
        meal_type = template['meal_types'][0].lower()
        typical_cal = typical_calories.get(meal_type)
        if typical_cal and typical_cal > 0:
            pattern_match = max(0, 1.0 - abs(template['calories'] - typical_cal) / typical_cal)

    # 10. Random factor
    random_factor_val = random.random()

    # Weighted sum
    score = (
        weights['calorie_fit'] * calorie_fit
        + weights['protein_fit'] * protein_fit
        + weights['sodium_ok'] * sodium_ok
        + weights['cuisine_bonus'] * cuisine_bonus
        + weights['cuisine_diverse'] * cuisine_diverse
        + weights['novelty_bonus'] * novelty_bonus
        + weights['repetition_penalty'] * repetition_penalty
        + weights['familiarity_bonus'] * familiarity_bonus
        + weights['pattern_match'] * pattern_match
        + weights['random_factor'] * random_factor_val
    )

    return score


def suggest_meals(meal_type=None, count=5, date=None):
    """
    Suggest meals based on remaining macros and user preferences.
    Returns list of (template, score, remaining) tuples sorted by score descending.
    """
    templates = load_meal_templates()
    if not templates:
        return []

    profile = dict(DIETARY_PROFILE)
    remaining = get_remaining_macros(date)
    history = get_history()

    # Infer meal_type from time if not specified
    if not meal_type:
        hour = datetime.now().hour
        if hour < 10:
            meal_type = 'breakfast'
        elif hour < 14:
            meal_type = 'lunch'
        elif hour < 18:
            meal_type = 'dinner'
        else:
            meal_type = 'snack'

    # Filter
    filtered, relaxed = filter_templates(templates, profile, meal_type)

    # Score
    scored = []
    for t in filtered:
        s = score_template(t, remaining, profile, history)
        scored.append((t, s))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Return top N
    results = []
    for t, s in scored[:count]:
        results.append({
            'template': t,
            'score': round(s, 3),
            'remaining': remaining,
            'relaxed_filters': list(relaxed),
        })

    return results


def enrich_from_themealdb(query, cuisine=None):
    """
    Query TheMealDB for recipe ideas. Returns simplified template dicts.
    Non-critical — returns empty list on failure.
    """
    try:
        from themealdb import search_meals, filter_by_cuisine, parse_meal_to_template
    except ImportError:
        try:
            from scripts.themealdb import search_meals, filter_by_cuisine, parse_meal_to_template
        except ImportError:
            return []

    results = []
    try:
        if cuisine:
            meals = filter_by_cuisine(cuisine)
        else:
            meals = search_meals(query)

        for meal in (meals or [])[:5]:
            template = parse_meal_to_template(meal)
            if template:
                results.append(template)
    except Exception:
        pass

    return results


def format_suggestions(suggestions, remaining=None):
    """Format meal suggestions into human-readable output."""
    if remaining is None and suggestions:
        remaining = suggestions[0].get('remaining', {})

    lines = []

    if remaining:
        consumed = remaining.get('consumed', {})
        lines.append(f"Remaining today: ~{remaining['calories']} cal, "
                     f"{remaining['protein']}g protein, "
                     f"{remaining['carbs']}g carbs, "
                     f"{remaining['fat']}g fat")

        if remaining['calories'] <= 0:
            lines.append("Note: You've reached your calorie target for today.")
        lines.append("")

    if not suggestions:
        lines.append("No meal suggestions available matching your preferences.")
        return '\n'.join(lines)

    # Infer meal type from first suggestion
    meal_types = suggestions[0]['template'].get('meal_types', [])
    meal_label = meal_types[0].title() if meal_types else 'Meal'
    lines.append(f"Suggested meals for {meal_label.lower()}:\n")

    for i, s in enumerate(suggestions, 1):
        t = s['template']
        tags = t.get('tags', {})
        cuisines = ', '.join(c.title() for c in (tags.get('cuisines') or []))
        skill = (tags.get('cooking_skill') or 'basic').title()
        prep = tags.get('prep_time_min', '?')

        lines.append(f"{i}. {t['name']}")
        lines.append(f"   ~{t['calories']} cal | {t['protein']}g protein | "
                     f"{t['carbs']}g carbs | {t['fat']}g fat")
        lines.append(f"   Prep: {prep} min | Skill: {skill} | {cuisines}")

        if remaining and remaining['calories'] > 0:
            cal_pct = int(t['calories'] / remaining['calories'] * 100)
            prot_pct = int(t['protein'] / max(remaining['protein'], 1) * 100)
            lines.append(f"   Fills {cal_pct}% of remaining calories, "
                         f"{prot_pct}% of remaining protein")
        lines.append("")

    if suggestions and suggestions[0].get('relaxed_filters'):
        relaxed = suggestions[0]['relaxed_filters']
        lines.append(f"Note: Some filters were relaxed ({', '.join(relaxed)}) to provide suggestions.")

    return '\n'.join(lines)


def main():
    """CLI interface for meal planner."""
    args = sys.argv[1:]

    meal_type = None
    count = 5

    if '--type' in args:
        idx = args.index('--type')
        if idx + 1 < len(args):
            meal_type = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if '--count' in args:
        idx = args.index('--count')
        if idx + 1 < len(args):
            try:
                count = int(args[idx + 1])
            except ValueError:
                pass
            args = args[:idx] + args[idx + 2:]

    if '--remaining' in args:
        remaining = get_remaining_macros()
        consumed = remaining.get('consumed', {})
        print(f"Today's consumption: {consumed['calories']} cal, "
              f"{consumed['protein']}g protein, {consumed['carbs']}g carbs, "
              f"{consumed['fat']}g fat, {consumed['sodium']}mg sodium")
        print(f"\nRemaining: {remaining['calories']} cal, "
              f"{remaining['protein']}g protein, {remaining['carbs']}g carbs, "
              f"{remaining['fat']}g fat")
        print(f"\nTargets: {remaining['cal_target']} cal, "
              f"{remaining['protein_target']}g protein, "
              f"{remaining['sodium_limit']}mg sodium")
        print(f"\nMeals remaining: {remaining['meals_remaining']}")
        return

    if '--help' in args or '-h' in args:
        print("Usage: meal_planner.py [options]")
        print("  --type TYPE      Meal type (breakfast, lunch, dinner, snack)")
        print("  --count N        Number of suggestions (default: 5)")
        print("  --remaining      Show remaining macros only")
        return

    # Mark meal plan requested for gradual learning
    try:
        from dietary_profile import mark_meal_plan_requested
        mark_meal_plan_requested()
    except ImportError:
        try:
            from scripts.dietary_profile import mark_meal_plan_requested
            mark_meal_plan_requested()
        except ImportError:
            pass

    suggestions = suggest_meals(meal_type=meal_type, count=count)
    output = format_suggestions(suggestions)
    print(output)


if __name__ == '__main__':
    main()
