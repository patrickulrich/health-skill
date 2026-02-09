#!/usr/bin/env python3
"""
Dietary profile management and gradual preference learning.
Manages user allergies, dietary restrictions, health conditions, and food preferences.
Preferences are learned gradually through coach note prompts over time.
"""

import sys
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

from config import DIETARY_PROFILE, SKILL_DIR as _SKILL_DIR

# State file for tracking gradual learning progress (separate from config.json)
_STATE_FILE = os.path.join(_SKILL_DIR, 'dietary_profile_state.json')

# Config file for saving profile updates
_CONFIG_FILE = os.path.join(_SKILL_DIR, 'config.json')

# Gradual learning schedule: {key: (trigger_count, priority)}
# trigger_count = number of meals logged before prompting
# Special value -1 means "only on meal plan request"
_PROMPT_SCHEDULE = {
    'allergies': (1, 'safety'),
    'health_conditions': (1, 'safety'),
    'dietary_restrictions': (5, 'coaching'),
    'dislikes': (10, 'comfort'),
    'cuisine_preferences': (15, 'planning'),
    'cooking_skill': (-1, 'planning'),
    'budget': (-1, 'planning'),
    'meal_timing': (20, 'optimization'),
    'meal_variety': (-1, 'planning'),
}

# Prompt questions for each preference
_PROMPT_QUESTIONS = {
    'allergies': "Do you have any food allergies? (e.g., peanuts, shellfish, dairy, gluten) Enter 'none' if not.",
    'health_conditions': "Do you have any health conditions that affect your diet? (e.g., diabetes, hypertension, high cholesterol) Enter 'none' if not.",
    'dietary_restrictions': "Do you follow any dietary restrictions? (e.g., vegetarian, vegan, keto, gluten-free)",
    'dislikes': "Are there any foods you dislike or want to avoid in meal suggestions?",
    'cuisine_preferences': "What cuisines do you enjoy most? (e.g., american, italian, mexican, asian, indian, mediterranean)",
    'cooking_skill': "How would you rate your cooking skill? (basic, intermediate, or advanced)",
    'budget': "What's your typical food budget? (budget, moderate, or premium)",
    'meal_timing': "When do you typically eat your meals? (e.g., 'breakfast 7am, lunch 12pm, dinner 7pm')",
    'meal_variety': "Do you prefer exploring new foods or sticking with favorites? (explore, balanced, or consistent)",
}

# Minimum interactions between prompts (anti-spam)
_MIN_INTERACTIONS_BETWEEN_PROMPTS = 3


def load_profile():
    """Returns the current DIETARY_PROFILE from config."""
    return dict(DIETARY_PROFILE)


def save_profile(profile):
    """
    Write DIETARY_PROFILE to config.json.
    Returns the updated profile.
    """
    try:
        with open(_CONFIG_FILE) as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        config = {}

    config['DIETARY_PROFILE'] = profile

    # Atomic write
    tmp = _CONFIG_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, _CONFIG_FILE)

    # Update in-memory config
    DIETARY_PROFILE.update(profile)

    return profile


def get_allergies():
    """Return list of user allergies."""
    return list(DIETARY_PROFILE.get('allergies') or [])


def has_allergy(allergen):
    """Check if user has a specific allergy."""
    return allergen.lower() in [a.lower() for a in get_allergies()]


def update_preference(key, value):
    """
    Update a single preference field, save to config.json.
    For list fields, value can be a comma-separated string.
    Returns the updated profile.
    """
    profile = load_profile()

    # List fields accept comma-separated strings
    list_fields = {'allergies', 'dietary_restrictions', 'dislikes',
                   'cuisine_preferences', 'health_conditions'}
    if key in list_fields and isinstance(value, str):
        if value.lower() in ('none', 'no', ''):
            value = []
        else:
            value = [v.strip().lower() for v in value.split(',') if v.strip()]

    profile[key] = value
    return save_profile(profile)


# --- Gradual Learning State ---

def _load_state():
    """Load gradual learning state from state file."""
    if not os.path.exists(_STATE_FILE):
        return {
            'total_meals_logged': 0,
            'last_prompt_at': 0,
            'meal_plan_requested': False,
        }
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            'total_meals_logged': 0,
            'last_prompt_at': 0,
            'meal_plan_requested': False,
        }


def _save_state(state):
    """Write gradual learning state to state file."""
    tmp = _STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, _STATE_FILE)


def increment_interactions():
    """Bump total_meals_logged counter."""
    state = _load_state()
    state['total_meals_logged'] = state.get('total_meals_logged', 0) + 1
    _save_state(state)
    return state['total_meals_logged']


def mark_meal_plan_requested():
    """Mark that a meal plan has been requested (triggers cooking_skill/budget prompts)."""
    state = _load_state()
    state['meal_plan_requested'] = True
    _save_state(state)


def should_prompt_preference(key):
    """
    Decision function: should we prompt for this preference?
    Returns True if the preference should be asked about now.
    """
    profile = load_profile()
    state = _load_state()

    # Already has data — don't prompt
    current_value = profile.get(key)
    if current_value:
        # Non-empty list or non-None/non-empty string
        if isinstance(current_value, list) and len(current_value) > 0:
            return False
        if isinstance(current_value, str) and current_value:
            return False
        if current_value is not None and not isinstance(current_value, (list, str)):
            return False

    # Already asked — don't prompt
    if state.get(f'{key}_asked'):
        return False

    trigger_count, priority = _PROMPT_SCHEDULE.get(key, (999, 'other'))
    meals = state.get('total_meals_logged', 0)

    # Meal-plan-only triggers
    if trigger_count == -1:
        return state.get('meal_plan_requested', False)

    # Not enough meals yet
    if meals < trigger_count:
        return False

    # Anti-spam: minimum interactions between prompts
    # Exception: allergies + health_conditions are asked together on 1st interaction
    if priority != 'safety':
        last_prompt = state.get('last_prompt_at', 0)
        if meals - last_prompt < _MIN_INTERACTIONS_BETWEEN_PROMPTS:
            return False

    return True


def get_next_prompt():
    """
    Returns the next preference prompt to show, or None.
    Returns: {key, question, priority} or None.
    Safety prompts (allergies + health_conditions) are returned together
    on the first interaction.
    """
    state = _load_state()
    profile = load_profile()

    # Priority order for prompting
    priority_order = [
        'allergies', 'health_conditions',
        'dietary_restrictions', 'dislikes',
        'cuisine_preferences', 'cooking_skill', 'budget',
        'meal_timing', 'meal_variety',
    ]

    # Special case: allergies and health_conditions together on 1st interaction
    if should_prompt_preference('allergies') and should_prompt_preference('health_conditions'):
        return {
            'key': 'allergies_and_health',
            'question': (
                "Before we continue, two quick safety questions:\n"
                f"1. {_PROMPT_QUESTIONS['allergies']}\n"
                f"2. {_PROMPT_QUESTIONS['health_conditions']}"
            ),
            'priority': 'safety',
        }

    for key in priority_order:
        if should_prompt_preference(key):
            _, priority = _PROMPT_SCHEDULE.get(key, (999, 'other'))
            # Mark as asked and update last_prompt_at
            state[f'{key}_asked'] = True
            state['last_prompt_at'] = state.get('total_meals_logged', 0)
            _save_state(state)
            return {
                'key': key,
                'question': _PROMPT_QUESTIONS[key],
                'priority': priority,
            }

    return None


def full_setup_prompts():
    """
    Return all unset preferences as prompts (for "let's configure" flow).
    Returns list of {key, question, priority} dicts.
    """
    profile = load_profile()
    prompts = []

    for key, (_, priority) in _PROMPT_SCHEDULE.items():
        current_value = profile.get(key)
        has_value = False
        if isinstance(current_value, list) and len(current_value) > 0:
            has_value = True
        elif isinstance(current_value, str) and current_value:
            has_value = True
        elif current_value is not None and not isinstance(current_value, (list, str)):
            has_value = True

        if not has_value:
            prompts.append({
                'key': key,
                'question': _PROMPT_QUESTIONS[key],
                'priority': priority,
            })

    return prompts


def format_profile_summary():
    """Human-readable summary of current dietary profile."""
    profile = load_profile()
    lines = ["Dietary Profile:"]

    def _fmt_list(items):
        if not items:
            return "not set"
        return ', '.join(str(i) for i in items)

    lines.append(f"  Allergies: {_fmt_list(profile.get('allergies'))}")
    lines.append(f"  Health conditions: {_fmt_list(profile.get('health_conditions'))}")
    lines.append(f"  Dietary restrictions: {_fmt_list(profile.get('dietary_restrictions'))}")
    lines.append(f"  Dislikes: {_fmt_list(profile.get('dislikes'))}")
    lines.append(f"  Cuisine preferences: {_fmt_list(profile.get('cuisine_preferences'))}")
    lines.append(f"  Cooking skill: {profile.get('cooking_skill') or 'not set'}")
    lines.append(f"  Budget: {profile.get('budget') or 'not set'}")
    lines.append(f"  Meal timing: {profile.get('meal_timing') or 'not set'}")
    lines.append(f"  Meal variety: {profile.get('meal_variety') or 'balanced'}")
    if profile.get('notes'):
        lines.append(f"  Notes: {profile['notes']}")

    state = _load_state()
    lines.append(f"\n  Meals logged: {state.get('total_meals_logged', 0)}")

    return '\n'.join(lines)


def main():
    """CLI interface for dietary profile management."""
    args = sys.argv[1:]

    if not args or '--help' in args:
        print("Usage:")
        print("  dietary_profile.py --show              Show current profile")
        print("  dietary_profile.py --set KEY VALUE      Set a preference")
        print("  dietary_profile.py --next-prompt        Get next gradual learning prompt")
        print("  dietary_profile.py --full-setup         Get all unset preference prompts")
        return

    if '--show' in args:
        print(format_profile_summary())
        return

    if '--set' in args:
        idx = args.index('--set')
        if idx + 2 < len(args):
            key = args[idx + 1]
            value = args[idx + 2]
            profile = update_preference(key, value)
            print(f"Updated {key}: {profile.get(key)}")
            print(f"\nSaved to {_CONFIG_FILE}")
        else:
            print("Usage: dietary_profile.py --set KEY VALUE")
            print("Keys: allergies, dietary_restrictions, dislikes, cuisine_preferences,")
            print("       health_conditions, cooking_skill, budget, meal_timing, notes")
        return

    if '--next-prompt' in args:
        prompt = get_next_prompt()
        if prompt:
            print(f"[{prompt['priority']}] {prompt['question']}")
        else:
            print("No prompts needed right now.")
        return

    if '--full-setup' in args:
        prompts = full_setup_prompts()
        if not prompts:
            print("All preferences are already configured!")
        else:
            for p in prompts:
                print(f"[{p['priority']}] {p['question']}\n")
        return


if __name__ == '__main__':
    main()
