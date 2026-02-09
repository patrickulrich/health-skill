"""
Centralized configuration for the health skill.

Resolution order for each setting:
1. Environment variable (HEALTH_SKILL_<KEY>)
2. config.json in the skill root
3. Default value
"""

import os
import json

# Skill directory (where this file lives)
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env file from skill root (lightweight, no dependency)
_env_file = os.path.join(SKILL_DIR, '.env')
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# Load user config if it exists
_config_file = os.path.join(SKILL_DIR, 'config.json')
_config = {}
if os.path.exists(_config_file):
    try:
        with open(_config_file) as f:
            _config = json.load(f)
    except (json.JSONDecodeError, IOError):
        pass


def _get(key, default=None):
    """Get config value: env var > config.json > default."""
    return os.environ.get(f'HEALTH_SKILL_{key}', _config.get(key, default))


# Workspace root directory
# Default assumes skill is installed at $WORKSPACE/skills/health-skill/
WORKSPACE = _get('WORKSPACE', os.path.dirname(os.path.dirname(SKILL_DIR)))

# Data directories for logs
FITNESS_DIR = _get('FITNESS_DIR', os.path.join(WORKSPACE, 'fitness'))
DIET_DIR = _get('DIET_DIR', os.path.join(WORKSPACE, 'diet'))

# Food database path (local SQLite file)
DB_PATH = _get('DB_PATH', os.path.join(
    SKILL_DIR, 'data', 'ComprehensiveFoodDatabase', 'extracted',
    'CompFoodCSV', 'CompFood.sqlite'
))

# USDA FoodData Central API key (optional, for API-based lookups)
USDA_API_KEY = _get('USDA_API_KEY')

# Multi-source food search configuration
# Enabled food data sources (queried in order, results merged by relevance)
# Accepts: list in config.json, or comma-separated string in env var
_food_sources_raw = _get('FOOD_SOURCES', ['local_db', 'opennutrition', 'usda_api'])
if isinstance(_food_sources_raw, str):
    FOOD_SOURCES = [s.strip() for s in _food_sources_raw.split(',') if s.strip()]
else:
    FOOD_SOURCES = list(_food_sources_raw)

# OpenNutrition SQLite database path
OPENNUTRITION_DB_PATH = _get('OPENNUTRITION_DB_PATH') or os.path.join(
    SKILL_DIR, 'data', 'opennutrition.sqlite'
)

# User goals — merged from config.json GOALS section
_DEFAULT_GOALS = {
    'goal_type': 'maintenance',
    'weight_kg': None,
    'height_cm': None,
    'age': None,
    'sex': 'male',
    'activity_level': 'moderate',
    'protein_per_kg': 0.8,
    'calorie_target': None,
    'sodium_limit_mg': 2300,
    'fiber_target_g': 38,
    'step_target': 10000,
    'sleep_target_h': 7.0,
}
GOALS = {**_DEFAULT_GOALS, **(_config.get('GOALS') or {})}

# Dietary profile — merged from config.json DIETARY_PROFILE section
_DEFAULT_DIETARY_PROFILE = {
    'allergies': [],
    'dietary_restrictions': [],
    'dislikes': [],
    'cuisine_preferences': [],
    'health_conditions': [],
    'cooking_skill': None,
    'budget': None,
    'meal_timing': None,
    'meal_variety': 'balanced',
    'notes': '',
}
DIETARY_PROFILE = {**_DEFAULT_DIETARY_PROFILE, **(_config.get('DIETARY_PROFILE') or {})}


def calculate_calorie_target():
    """
    Calculate daily calorie target using Mifflin-St Jeor equation.
    Returns int or None if weight/height/age not configured.
    If GOALS['calorie_target'] is set explicitly, returns that instead.
    """
    if GOALS['calorie_target']:
        return int(GOALS['calorie_target'])

    weight = GOALS['weight_kg']
    height = GOALS['height_cm']
    age = GOALS['age']
    if not all([weight, height, age]):
        return None

    # Mifflin-St Jeor BMR
    if GOALS['sex'] == 'female':
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age + 5

    # Activity multipliers
    multipliers = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very_active': 1.9,
    }
    tdee = bmr * multipliers.get(GOALS['activity_level'], 1.55)

    # Adjust for goal type
    goal = GOALS['goal_type']
    if goal == 'weight_loss':
        tdee -= 500
    elif goal == 'muscle_gain':
        tdee += 300

    return int(tdee)
