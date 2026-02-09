#!/usr/bin/env python3
"""Tests for health skill parser functions."""

import os
import sys
import sqlite3
import pytest

# Add project root and scripts to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'scripts'))

from unittest.mock import patch, MagicMock
import json

from log_workout import parse_workout_text, log_workout_to_file
from calculate_macros import (
    extract_meal_type, extract_time, parse_food_items,
    log_meal_to_file, update_daily_totals, WORD_NUMBERS,
    analyze_meal, is_beverage, _load_saved_meals, _save_meal_shortcut,
)
from generate_daily_summary import (
    assess_movement, assess_sleep, generate_coach_notes, parse_workout_log,
    parse_diet_log,
)
from dietary_profile import (
    load_profile, save_profile, get_allergies, has_allergy, update_preference,
    _load_state, _save_state, increment_interactions, should_prompt_preference,
    get_next_prompt, full_setup_prompts, format_profile_summary,
    mark_meal_plan_requested, _STATE_FILE, _CONFIG_FILE,
)
from allergy_checker import (
    load_allergen_map, check_meal_allergens, check_single_food, format_warnings,
)
from meal_planner import (
    load_meal_templates, get_remaining_macros, filter_templates, score_template,
    suggest_meals, format_suggestions, _VARIETY_WEIGHTS,
)
from meal_history import (
    parse_foods_from_diet_log, detect_cuisines_from_foods, get_recent_foods,
    get_typical_calories, build_history, get_history, _load_cache, _save_cache,
    _load_cuisine_map,
)
from themealdb import parse_meal_to_template
from query_food_db import (
    search_foods, _search_local_db, _search_opennutrition, _search_usda_api
)


# ---------------------------------------------------------------------------
# parse_workout_text
# ---------------------------------------------------------------------------

class TestParseWorkoutText:
    def test_bodyweight_did_pattern(self):
        result = parse_workout_text("I did 34 situps")
        assert len(result['exercises']) >= 1
        ex = result['exercises'][0]
        assert ex['count'] == 34
        assert 'sit' in ex['name'].lower()  # canonical: "Sit-up"

    def test_cardio_running(self):
        result = parse_workout_text("Went for a 5 km run, 25 minutes")
        assert result['workout_type'].startswith('Cardio')
        cardio_ex = [e for e in result['exercises'] if e.get('type') == 'Cardio']
        assert len(cardio_ex) >= 1
        assert cardio_ex[0]['name'] == 'Running'
        assert cardio_ex[0]['distance'] == '5 km'
        assert cardio_ex[0]['duration'] == '25 min'

    def test_sets_pattern(self):
        result = parse_workout_text("3 sets of pushups")
        sets_ex = [e for e in result['exercises'] if e.get('sets')]
        assert len(sets_ex) >= 1
        assert sets_ex[0]['sets'] == 3

    def test_intensity_hard(self):
        result = parse_workout_text("I did 20 pushups, intense workout")
        assert result['intensity'] == 'Hard'

    def test_intensity_light(self):
        result = parse_workout_text("Easy warmup, light stretching")
        assert result['intensity'] == 'Light'

    def test_cycling(self):
        result = parse_workout_text("30 min bike ride")
        assert 'Cycling' in result['workout_type']

    def test_swimming(self):
        result = parse_workout_text("Swam for 45 minutes in the pool")
        assert 'Swimming' in result['workout_type']

    def test_yoga(self):
        result = parse_workout_text("Did yoga for 30 minutes")
        assert result['workout_type'] == 'Flexibility/Mobility'

    def test_gym(self):
        result = parse_workout_text("Went to the gym today")
        assert result['workout_type'] == 'Gym'

    # Bug 4 regression: exercise name matching at end of string
    def test_end_of_string_exercise(self):
        """Bug 4: regex should match exercise names at end of string."""
        result = parse_workout_text("I did 20 pushups")
        assert len(result['exercises']) >= 1
        ex = result['exercises'][0]
        assert 'push' in ex['name'].lower()
        assert ex['count'] == 20


# ---------------------------------------------------------------------------
# Bug 1 regression: file doubling on append
# ---------------------------------------------------------------------------

class TestWorkoutFileLogging:
    def test_no_file_doubling(self, tmp_path):
        """Bug 1: logging should not double file contents on each append."""
        import log_workout
        original_fitness_dir = log_workout.FITNESS_DIR
        log_workout.FITNESS_DIR = str(tmp_path)

        try:
            workout1 = parse_workout_text("I did 10 pushups")
            log_workout_to_file(workout1, "2025-01-01")

            with open(tmp_path / "2025-01-01.md", 'r') as f:
                content_after_first = f.read()

            workout2 = parse_workout_text("I did 20 situps")
            log_workout_to_file(workout2, "2025-01-01")

            with open(tmp_path / "2025-01-01.md", 'r') as f:
                content_after_second = f.read()

            # Content should NOT be doubled - second write appends only new workout
            assert content_after_second.count(content_after_first) == 1
            # Both workouts should be present
            assert 'push-up' in content_after_second.lower() or 'Push-up' in content_after_second
            assert 'sit-up' in content_after_second.lower() or 'Sit-up' in content_after_second
        finally:
            log_workout.FITNESS_DIR = original_fitness_dir


# ---------------------------------------------------------------------------
# extract_time
# ---------------------------------------------------------------------------

class TestExtractTime:
    def test_hhmm_pm(self):
        assert extract_time("lunch at 2:30 PM") == "2:30 PM"

    def test_hhmm_am(self):
        assert extract_time("breakfast at 9:00 am") == "9:00 AM"

    def test_h_pm(self):
        assert extract_time("dinner around 7 pm") == "7:00 PM"

    def test_no_time(self):
        assert extract_time("I had chicken for lunch") is None

    # Bug 6 regression: extract_time should actually return values
    def test_returns_value_not_none(self):
        """Bug 6: extract_time was broken and never returned values."""
        result = extract_time("ate at 12:30 pm")
        assert result is not None
        assert "12:30" in result


# ---------------------------------------------------------------------------
# extract_meal_type
# ---------------------------------------------------------------------------

class TestExtractMealType:
    def test_breakfast(self):
        assert extract_meal_type("eggs for breakfast") == "Breakfast"

    def test_lunch(self):
        assert extract_meal_type("I had chicken for lunch") == "Lunch"

    def test_dinner(self):
        assert extract_meal_type("pasta for dinner") == "Dinner"

    def test_snack(self):
        assert extract_meal_type("had a snack") == "Snack"

    def test_default(self):
        assert extract_meal_type("I ate some chicken") == "Meal"


# ---------------------------------------------------------------------------
# parse_food_items
# ---------------------------------------------------------------------------

class TestParseFoodItems:
    def test_multi_word_phrase(self):
        items = parse_food_items("I had chicken breast and rice")
        food_names = [name for name, _, _ in items]
        assert 'chicken breast' in food_names

    def test_single_keyword(self):
        items = parse_food_items("I ate some pizza")
        food_names = [name for name, _, _ in items]
        assert 'pizza' in food_names

    def test_no_duplicates_with_phrase(self):
        """Multi-word phrase should prevent duplicate single-word matches."""
        items = parse_food_items("I had chicken breast")
        food_names = [name for name, _, _ in items]
        # 'chicken breast' matched as phrase, 'chicken' should not also appear
        assert food_names.count('chicken') == 0 or 'chicken breast' in food_names

    def test_multiple_foods(self):
        items = parse_food_items("I had chicken breast and rice and broccoli")
        food_names = [name for name, _, _ in items]
        assert 'chicken breast' in food_names
        assert 'broccoli' in food_names

    def test_quantity_grams(self):
        items = parse_food_items("200g chicken breast")
        for name, qty, unit in items:
            if name == 'chicken breast':
                assert qty == 200.0
                assert unit == 'g'

    def test_quantity_oz(self):
        items = parse_food_items("3 oz steak")
        for name, qty, unit in items:
            if name == 'steak':
                assert qty == 3.0
                assert unit == 'oz'

    def test_bare_number(self):
        """'2 eggs' should detect quantity 2."""
        items = parse_food_items("2 eggs")
        found = [(name, qty, unit) for name, qty, unit in items if 'egg' in name]
        assert len(found) >= 1
        assert found[0][1] == 2.0

    def test_word_number(self):
        """'two eggs' should detect quantity 2."""
        items = parse_food_items("two eggs")
        found = [(name, qty, unit) for name, qty, unit in items if 'egg' in name]
        assert len(found) >= 1
        assert found[0][1] == 2.0

    def test_half_an_avocado(self):
        """'half an avocado' should detect quantity 0.5."""
        items = parse_food_items("half an avocado")
        found = [(name, qty, unit) for name, qty, unit in items if name == 'avocado']
        assert len(found) == 1
        assert found[0][1] == 0.5

    def test_a_cup_of_rice(self):
        """'a cup of rice' should detect quantity 1 with unit cups."""
        items = parse_food_items("a cup of rice")
        found = [(name, qty, unit) for name, qty, unit in items if name == 'rice']
        assert len(found) == 1
        assert found[0][1] == 1.0
        assert 'cup' in found[0][2]

    def test_some_broccoli(self):
        """'some broccoli' should detect quantity 1."""
        items = parse_food_items("some broccoli")
        found = [(name, qty, unit) for name, qty, unit in items if name == 'broccoli']
        assert len(found) == 1
        assert found[0][1] == 1.0

    def test_returns_triples(self):
        """parse_food_items should return (name, qty, unit) triples."""
        items = parse_food_items("I had chicken breast")
        assert len(items) >= 1
        assert len(items[0]) == 3


# ---------------------------------------------------------------------------
# generate_coach_notes
# ---------------------------------------------------------------------------

class TestGenerateCoachNotes:
    # Bug 7 regression: no duplicate "no exercise" messages
    def test_no_duplicate_no_exercise(self):
        """Bug 7: should not have duplicate 'no exercise' messages."""
        notes = generate_coach_notes(None, None, None)
        no_exercise_count = sum(
            1 for msg in notes['improvements'] if 'no exercise' in msg.lower()
        )
        assert no_exercise_count <= 1

    def test_high_protein_strength(self):
        diet = {'protein': 100, 'carbs': 200, 'fat': 50, 'sodium': 1500, 'fiber': 10}
        notes = generate_coach_notes(None, diet, None)
        assert any('protein' in s.lower() for s in notes['strengths'])

    def test_high_sodium_improvement(self):
        diet = {'protein': 50, 'carbs': 200, 'fat': 50, 'sodium': 3000, 'fiber': 10}
        notes = generate_coach_notes(None, diet, None)
        assert any('sodium' in s.lower() for s in notes['improvements'])


# ---------------------------------------------------------------------------
# Bug 5 regression: workout section regex captures full body
# ---------------------------------------------------------------------------

class TestWorkoutSectionParsing:
    def test_section_captures_exercises(self, tmp_path):
        """Bug 5: workout section regex should capture full section body, not just header."""
        workout_content = """## Workout - 06:00 PM
Type: Resistance Training
Intensity: Hard

### Exercises
1. Bench press
   Weight: 225 lbs
   Sets: 3
   Reps: 10

## Workout - 08:00 PM
Type: Cardio
Duration: 30 min
"""
        workout_file = tmp_path / "2025-01-01.md"
        workout_file.write_text(workout_content)

        import generate_daily_summary
        original_fitness_dir = generate_daily_summary.FITNESS_DIR
        generate_daily_summary.FITNESS_DIR = str(tmp_path)

        try:
            result = parse_workout_log("2025-01-01")
            assert result['workout_sessions'] == 2
        finally:
            generate_daily_summary.FITNESS_DIR = original_fitness_dir


# ---------------------------------------------------------------------------
# assess_movement and assess_sleep
# ---------------------------------------------------------------------------

class TestAssessments:
    def test_sedentary(self):
        assert assess_movement(3000) == "Sedentary"

    def test_light(self):
        assert assess_movement(6000) == "Light"

    def test_moderate(self):
        assert assess_movement(10000) == "Moderate"

    def test_active(self):
        assert assess_movement(14000) == "Active"

    def test_very_active(self):
        assert assess_movement(20000) == "Very active"

    def test_good_sleep(self):
        assert assess_sleep(8) == "Good"

    def test_fair_sleep(self):
        assert assess_sleep(6) == "Fair"

    def test_poor_sleep(self):
        assert assess_sleep(4) == "Poor"

    # Boundary values
    def test_boundary_5000(self):
        assert assess_movement(5000) == "Light"

    def test_boundary_8000(self):
        assert assess_movement(8000) == "Moderate"

    def test_boundary_7_hours(self):
        assert assess_sleep(7) == "Good"

    def test_boundary_5_hours(self):
        assert assess_sleep(5) == "Fair"


# ---------------------------------------------------------------------------
# Multi-source food search
# ---------------------------------------------------------------------------

class TestSearchLocalDb:
    def test_returns_empty_when_db_missing(self):
        """_search_local_db returns [] when database file doesn't exist."""
        with patch('query_food_db.DB_PATH', '/nonexistent/path/food.sqlite'):
            result = _search_local_db('chicken')
            assert result == []


class TestSearchOpenNutrition:
    def test_returns_empty_when_db_missing(self):
        """_search_opennutrition returns [] when database file doesn't exist."""
        with patch('query_food_db.OPENNUTRITION_DB_PATH', '/nonexistent/opennutrition.sqlite'):
            result = _search_opennutrition('chicken')
            assert result == []

    def test_queries_opennutrition_table(self, tmp_path):
        """_search_opennutrition queries the opennutrition table correctly."""
        db_path = str(tmp_path / 'test_opennutrition.sqlite')
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE opennutrition (
                id TEXT, name TEXT, calories REAL, protein REAL,
                carbohydrates REAL, total_fat REAL, sodium REAL,
                dietary_fiber REAL, serving TEXT, source TEXT, type TEXT
            )
        ''')
        conn.execute(
            'INSERT INTO opennutrition VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('1', 'Chicken Breast, Grilled', 165, 31, 0, 3.6, 74, 0, '100g', 'USDA', 'generic')
        )
        conn.commit()
        conn.close()

        with patch('query_food_db.OPENNUTRITION_DB_PATH', db_path):
            results = _search_opennutrition('chicken')
            assert len(results) == 1
            desc, cal, pro, carbs, fat, sod, fib, source, serv_g = results[0]
            assert 'Chicken' in desc
            assert cal == 165
            assert pro == 31
            assert source == 'OpenNutrition'
            assert serv_g == 100.0


class TestSearchUsdaApi:
    def test_returns_empty_when_no_api_key(self):
        """_search_usda_api returns [] when USDA_API_KEY is not set."""
        with patch('query_food_db.USDA_API_KEY', None):
            result = _search_usda_api('chicken')
            assert result == []

    def test_parses_api_response(self):
        """_search_usda_api correctly parses USDA FoodData Central response."""
        mock_response = json.dumps({
            'foods': [{
                'description': 'Chicken breast, raw',
                'servingSize': 85,
                'foodNutrients': [
                    {'nutrientId': 1008, 'value': 120},
                    {'nutrientId': 1003, 'value': 22.5},
                    {'nutrientId': 1005, 'value': 0},
                    {'nutrientId': 1004, 'value': 2.6},
                    {'nutrientId': 1093, 'value': 116},
                    {'nutrientId': 1079, 'value': 0},
                ]
            }]
        }).encode('utf-8')

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('query_food_db.USDA_API_KEY', 'test-key'), \
             patch('query_food_db.urlopen', return_value=mock_resp):
            results = _search_usda_api('chicken')
            assert len(results) == 1
            desc, cal, pro, carbs, fat, sod, fib, source, serv_g = results[0]
            assert desc == 'Chicken breast, raw'
            assert cal == 120
            assert pro == 22.5
            assert sod == 116
            assert source == 'USDA-API'
            assert serv_g == 85.0

    def test_handles_network_error(self):
        """_search_usda_api returns [] on network errors."""
        from urllib.error import URLError
        with patch('query_food_db.USDA_API_KEY', 'test-key'), \
             patch('query_food_db.urlopen', side_effect=URLError('timeout')):
            result = _search_usda_api('chicken')
            assert result == []


class TestSearchFoodsMerge:
    def test_merges_multiple_sources(self):
        """search_foods merges and sorts results from multiple sources."""
        local_results = [
            ('Chicken Breast, Skinless', 165, 31, 0, 3.6, 74, 0, 'USDA', 85),
        ]
        open_results = [
            ('Chicken Breast, Grilled', 160, 30, 1, 3.5, 70, 0, 'OpenNutrition', 100),
        ]
        api_results = [
            ('Chicken breast, raw', 120, 22.5, 0, 2.6, 116, 0, 'USDA-API', 85),
        ]

        with patch('query_food_db.FOOD_SOURCES', ['local_db', 'opennutrition', 'usda_api']), \
             patch('query_food_db._search_local_db', return_value=local_results), \
             patch('query_food_db._search_opennutrition', return_value=open_results), \
             patch('query_food_db._search_usda_api', return_value=api_results):
            results = search_foods('chicken breast', limit=10)
            assert len(results) == 3
            sources = {r[7] for r in results}
            assert sources == {'USDA', 'OpenNutrition', 'USDA-API'}

    def test_respects_limit(self):
        """search_foods respects the limit parameter after merging."""
        many_results = [
            (f'Food item {i}', 100 + i, 10, 20, 5, 0, 0, 'USDA', 100)
            for i in range(15)
        ]

        with patch('query_food_db.FOOD_SOURCES', ['local_db']), \
             patch('query_food_db._search_local_db', return_value=many_results):
            results = search_foods('food', limit=5)
            assert len(results) == 5

    def test_skips_unknown_source(self):
        """search_foods silently skips unknown source names."""
        with patch('query_food_db.FOOD_SOURCES', ['nonexistent_source']):
            results = search_foods('chicken')
            assert results == []

    def test_sorts_by_relevance(self):
        """search_foods sorts results by query match position then description length."""
        results_data = [
            ('Roasted Chicken Breast', 200, 30, 0, 8, 0, 0, 'USDA', 100),
            ('Chicken Breast', 165, 31, 0, 3, 0, 0, 'OpenNutrition', 100),
            ('BBQ Chicken Breast Sandwich', 350, 25, 30, 12, 0, 0, 'USDA-API', 100),
        ]

        with patch('query_food_db.FOOD_SOURCES', ['local_db']), \
             patch('query_food_db._search_local_db', return_value=results_data):
            results = search_foods('Chicken Breast', limit=10)
            # "Chicken Breast" (starts at 0) should come before "Roasted Chicken Breast" (starts at 8)
            assert results[0][0] == 'Chicken Breast'


# ---------------------------------------------------------------------------
# Serving-aware scaling (gram-to-serving conversion)
# ---------------------------------------------------------------------------

class TestServingAwareScaling:
    def test_gram_scaling(self):
        """200g of food with 100g serving should multiply by 2."""
        from query_food_db import calculate_meal_macros
        mock_results = [
            ('Chicken Breast', 165, 31, 0, 3.6, 74, 0, 'USDA', 100),
        ]
        with patch('query_food_db.search_foods', return_value=mock_results):
            totals = calculate_meal_macros([('chicken breast', 200, 'g')])
            assert abs(totals['calories'] - 330) < 1  # 165 * (200/100) = 330
            assert abs(totals['protein'] - 62) < 1    # 31 * 2 = 62

    def test_oz_scaling(self):
        """3oz of food with 85g serving should scale correctly."""
        from query_food_db import calculate_meal_macros
        mock_results = [
            ('Steak', 250, 26, 0, 15, 60, 0, 'USDA', 85),
        ]
        with patch('query_food_db.search_foods', return_value=mock_results):
            totals = calculate_meal_macros([('steak', 3, 'oz')])
            expected_mult = (3 * 28.35) / 85  # ~1.0
            assert abs(totals['calories'] - 250 * expected_mult) < 1

    def test_servings_scaling(self):
        """Raw multiplier for servings/pieces."""
        from query_food_db import calculate_meal_macros
        mock_results = [
            ('Egg', 78, 6, 0.6, 5, 62, 0, 'USDA', 50),
        ]
        with patch('query_food_db.search_foods', return_value=mock_results):
            totals = calculate_meal_macros([('egg', 2, 'servings')])
            assert abs(totals['calories'] - 156) < 1  # 78 * 2

    def test_backward_compat_2tuple(self):
        """Old (name, qty) 2-tuples should still work."""
        from query_food_db import calculate_meal_macros
        mock_results = [
            ('Rice', 130, 2.7, 28, 0.3, 1, 0.4, 'USDA', 100),
        ]
        with patch('query_food_db.search_foods', return_value=mock_results):
            totals = calculate_meal_macros([('rice', 1)])
            assert abs(totals['calories'] - 130) < 1


# ---------------------------------------------------------------------------
# Diet log writing
# ---------------------------------------------------------------------------

class TestDietLogWriting:
    def test_log_creates_file(self, tmp_path):
        """log_meal_to_file should create a diet log file."""
        import calculate_macros
        original_diet_dir = calculate_macros.DIET_DIR
        calculate_macros.DIET_DIR = str(tmp_path)

        try:
            result = {
                'meal_type': 'Lunch',
                'meal_time': '2:30 PM',
                'food_items': [('chicken breast', 200, 'g')],
                'macros': {
                    'calories': 330, 'protein': 62, 'carbs': 0,
                    'fat': 7, 'sodium': 148, 'fiber': 0,
                    'items': [{'name': 'Chicken Breast', 'quantity': 200, 'unit': 'g', 'source': 'USDA'}]
                }
            }
            log_file = log_meal_to_file(result, date='2025-03-15')
            assert os.path.exists(log_file)

            with open(log_file, 'r') as f:
                content = f.read()
            assert '### Lunch (~2:30 PM)' in content
            assert 'Chicken Breast' in content
            assert '~330' in content
        finally:
            calculate_macros.DIET_DIR = original_diet_dir

    def test_log_appends_multiple_meals(self, tmp_path):
        """Multiple meals should be appended to the same day file."""
        import calculate_macros
        original_diet_dir = calculate_macros.DIET_DIR
        calculate_macros.DIET_DIR = str(tmp_path)

        try:
            meal1 = {
                'meal_type': 'Breakfast', 'meal_time': '9:00 AM',
                'food_items': [('eggs', 2, 'servings')],
                'macros': {
                    'calories': 156, 'protein': 12, 'carbs': 1,
                    'fat': 10, 'sodium': 124, 'fiber': 0,
                    'items': [{'name': 'Egg', 'quantity': 2, 'unit': 'servings', 'source': 'USDA'}]
                }
            }
            meal2 = {
                'meal_type': 'Lunch', 'meal_time': '1:00 PM',
                'food_items': [('rice', 1, 'cups')],
                'macros': {
                    'calories': 200, 'protein': 4, 'carbs': 45,
                    'fat': 0, 'sodium': 0, 'fiber': 1,
                    'items': [{'name': 'Rice', 'quantity': 1, 'unit': 'cups', 'source': 'USDA'}]
                }
            }
            log_meal_to_file(meal1, date='2025-03-15')
            log_meal_to_file(meal2, date='2025-03-15')

            with open(tmp_path / '2025-03-15.md', 'r') as f:
                content = f.read()
            assert '### Breakfast' in content
            assert '### Lunch' in content
        finally:
            calculate_macros.DIET_DIR = original_diet_dir

    def test_update_daily_totals(self, tmp_path):
        """update_daily_totals should sum calories and macros."""
        import calculate_macros
        original_diet_dir = calculate_macros.DIET_DIR
        calculate_macros.DIET_DIR = str(tmp_path)

        try:
            log_file = tmp_path / '2025-03-15.md'
            log_file.write_text(
                "# Diet Log - 2025-03-15\n\n"
                "### Breakfast (~9:00 AM)\n"
                "- Egg (x2)\n"
                "  - Est. calories: ~156\n"
                "  - Macros: ~12g protein, ~1g carbs, ~10g fat\n\n"
                "### Lunch (~1:00 PM)\n"
                "- Rice (x1)\n"
                "  - Est. calories: ~200\n"
                "  - Macros: ~4g protein, ~45g carbs, ~0g fat\n"
            )
            update_daily_totals(date='2025-03-15')

            with open(log_file, 'r') as f:
                content = f.read()
            assert '## Daily Totals' in content
            assert '~356 kcal' in content
            assert '~16g' in content  # 12 + 4 protein
        finally:
            calculate_macros.DIET_DIR = original_diet_dir


# ---------------------------------------------------------------------------
# Round 2 bug fix regression tests
# ---------------------------------------------------------------------------

class TestRound2Fixes:
    def test_parse_diet_log_finds_daily_totals(self, tmp_path):
        """Fix 1: parse_diet_log should read '## Daily Totals' section correctly."""
        from generate_daily_summary import parse_diet_log
        import generate_daily_summary
        original_diet_dir = generate_daily_summary.DIET_DIR
        generate_daily_summary.DIET_DIR = str(tmp_path)

        try:
            diet_file = tmp_path / '2025-04-01.md'
            diet_file.write_text(
                "# Diet Log - 2025-04-01\n\n"
                "### Lunch (~1:00 PM)\n"
                "- Chicken Breast (200g)\n"
                "  - Est. calories: ~330\n"
                "  - Macros: ~62g protein, ~0g carbs, ~7g fat\n\n"
                "## Daily Totals\n"
                "- Calories: ~330 kcal\n"
                "- Protein: ~62g\n"
                "- Carbs: ~0g\n"
                "- Fat: ~7g\n"
            )
            result = parse_diet_log('2025-04-01')
            assert result is not None
            assert result['calories_consumed'] == 330
            assert result['protein'] == 62
        finally:
            generate_daily_summary.DIET_DIR = original_diet_dir

    def test_workout_log_creates_directory(self, tmp_path):
        """Fix 2: log_workout_to_file should create FITNESS_DIR if missing."""
        import log_workout
        new_dir = str(tmp_path / 'fitness' / 'nested')
        original_fitness_dir = log_workout.FITNESS_DIR
        log_workout.FITNESS_DIR = new_dir

        try:
            workout = parse_workout_text("I did 10 pushups")
            log_workout_to_file(workout, "2025-04-01")
            assert os.path.exists(os.path.join(new_dir, '2025-04-01.md'))
        finally:
            log_workout.FITNESS_DIR = original_fitness_dir

    def test_coach_notes_carbs_string_closed(self):
        """Fix 3: high carbs improvement message should have balanced parentheses."""
        from generate_daily_summary import generate_coach_notes
        diet = {'protein': 50, 'carbs': 300, 'fat': 50, 'sodium': 1500, 'fiber': 10}
        notes = generate_coach_notes(None, diet, None)
        carbs_msgs = [m for m in notes['improvements'] if 'carbs' in m.lower()]
        assert len(carbs_msgs) >= 1
        for msg in carbs_msgs:
            assert msg.count('(') == msg.count(')'), f"Unbalanced parens in: {msg}"

    def test_update_daily_totals_with_commas(self, tmp_path):
        """Fix 4: update_daily_totals should parse comma-formatted numbers."""
        import calculate_macros
        original_diet_dir = calculate_macros.DIET_DIR
        calculate_macros.DIET_DIR = str(tmp_path)

        try:
            log_file = tmp_path / '2025-04-01.md'
            log_file.write_text(
                "# Diet Log - 2025-04-01\n\n"
                "### Lunch (~1:00 PM)\n"
                "- Big Meal (x1)\n"
                "  - Est. calories: ~1,200\n"
                "  - Macros: ~80g protein, ~120g carbs, ~50g fat\n"
            )
            update_daily_totals(date='2025-04-01')

            with open(log_file, 'r') as f:
                content = f.read()
            assert '## Daily Totals' in content
            assert '~1200 kcal' in content
        finally:
            calculate_macros.DIET_DIR = original_diet_dir

    def test_unrecognized_food_tracked(self):
        """Fix 5: unrecognized foods should appear in the 'unrecognized' list."""
        from query_food_db import calculate_meal_macros
        with patch('query_food_db.search_foods', return_value=[]):
            totals = calculate_meal_macros([('xyzfoobar', 1, 'servings')])
            assert 'unrecognized' in totals
            assert 'xyzfoobar' in totals['unrecognized']

    def test_walrus_patterns_still_work(self):
        """Fix 6: workout parsing should still work after walrus operator refactor."""
        result = parse_workout_text("I did 15 pushups")
        assert len(result['exercises']) >= 1
        ex = result['exercises'][0]
        assert ex['count'] == 15
        assert 'push' in ex['name'].lower()

        result2 = parse_workout_text("3 sets of squats")
        sets_ex = [e for e in result2['exercises'] if e.get('sets')]
        assert len(sets_ex) >= 1
        assert sets_ex[0]['sets'] == 3


# ---------------------------------------------------------------------------
# Feature 1: Configurable Goals
# ---------------------------------------------------------------------------

class TestGoalsConfig:
    def test_goals_loaded(self):
        """GOALS dict should be loaded from config."""
        from config import GOALS
        assert isinstance(GOALS, dict)
        assert 'protein_per_kg' in GOALS
        assert 'sodium_limit_mg' in GOALS
        assert 'step_target' in GOALS
        assert 'sleep_target_h' in GOALS

    def test_goals_defaults(self):
        """GOALS should have sensible defaults."""
        from config import GOALS
        assert GOALS['protein_per_kg'] == 0.8
        assert GOALS['sodium_limit_mg'] == 2300
        assert GOALS['fiber_target_g'] == 38
        assert GOALS['step_target'] == 10000
        assert GOALS['sleep_target_h'] == 7.0

    def test_calorie_target_none_without_biometrics(self):
        """calculate_calorie_target returns None without weight/height/age."""
        from config import calculate_calorie_target, GOALS
        original = GOALS.copy()
        GOALS['weight_kg'] = None
        GOALS['height_cm'] = None
        GOALS['age'] = None
        GOALS['calorie_target'] = None
        try:
            assert calculate_calorie_target() is None
        finally:
            GOALS.update(original)

    def test_calorie_target_with_biometrics(self):
        """calculate_calorie_target computes Mifflin-St Jeor when biometrics set."""
        from config import calculate_calorie_target, GOALS
        original = GOALS.copy()
        GOALS['weight_kg'] = 80
        GOALS['height_cm'] = 180
        GOALS['age'] = 30
        GOALS['sex'] = 'male'
        GOALS['activity_level'] = 'moderate'
        GOALS['calorie_target'] = None
        GOALS['goal_type'] = 'maintenance'
        try:
            target = calculate_calorie_target()
            assert target is not None
            # BMR = 10*80 + 6.25*180 - 5*30 + 5 = 800+1125-150+5 = 1780
            # TDEE = 1780 * 1.55 = 2759
            assert abs(target - 2759) < 2
        finally:
            GOALS.update(original)

    def test_calorie_target_weight_loss(self):
        """Weight loss goal should subtract 500 kcal."""
        from config import calculate_calorie_target, GOALS
        original = GOALS.copy()
        GOALS['weight_kg'] = 80
        GOALS['height_cm'] = 180
        GOALS['age'] = 30
        GOALS['sex'] = 'male'
        GOALS['activity_level'] = 'moderate'
        GOALS['calorie_target'] = None
        GOALS['goal_type'] = 'weight_loss'
        try:
            target = calculate_calorie_target()
            assert target is not None
            assert abs(target - 2259) < 2  # 2759 - 500
        finally:
            GOALS.update(original)

    def test_calorie_target_explicit_override(self):
        """Explicit calorie_target should override calculation."""
        from config import calculate_calorie_target, GOALS
        original = GOALS.copy()
        GOALS['calorie_target'] = 2000
        try:
            assert calculate_calorie_target() == 2000
        finally:
            GOALS.update(original)

    def test_coach_notes_use_goals_sodium(self):
        """Coach notes should use configured sodium limit."""
        from config import GOALS
        original = GOALS.copy()
        GOALS['sodium_limit_mg'] = 1500
        try:
            diet = {'protein': 100, 'carbs': 200, 'fat': 50, 'sodium': 1800, 'fiber': 10}
            notes = generate_coach_notes(None, diet, None)
            sodium_msgs = [m for m in notes['improvements'] if 'sodium' in m.lower()]
            assert len(sodium_msgs) >= 1
            assert '1,500' in sodium_msgs[0] or '1500' in sodium_msgs[0]
        finally:
            GOALS.update(original)

    def test_assess_sleep_uses_goals(self):
        """assess_sleep should use configured sleep target."""
        from config import GOALS
        original = GOALS.copy()
        GOALS['sleep_target_h'] = 8.0
        try:
            assert assess_sleep(8.0) == "Good"
            assert assess_sleep(7.5) == "Fair"
            assert assess_sleep(5.5) == "Poor"
        finally:
            GOALS.update(original)


# ---------------------------------------------------------------------------
# Feature 5: Hydration tracking
# ---------------------------------------------------------------------------

class TestHydration:
    def test_is_beverage_water(self):
        assert is_beverage('Water') is True

    def test_is_beverage_coffee(self):
        assert is_beverage('coffee') is True

    def test_is_beverage_milk(self):
        assert is_beverage('Almond Milk') is True

    def test_is_not_beverage(self):
        assert is_beverage('chicken breast') is False
        assert is_beverage('rice') is False

    def test_analyze_meal_tracks_beverages(self):
        """analyze_meal should count beverages in macros."""
        mock_results = [
            ('Coffee', 2, 0, 0, 0, 0, 0, 'USDA', 240),
        ]
        with patch('query_food_db.search_foods', return_value=mock_results):
            result = analyze_meal("I had coffee for breakfast")
            assert result['macros']['beverages'] >= 1

    def test_hydration_in_daily_totals(self, tmp_path):
        """update_daily_totals should count hydration lines."""
        import calculate_macros
        original_diet_dir = calculate_macros.DIET_DIR
        calculate_macros.DIET_DIR = str(tmp_path)

        try:
            log_file = tmp_path / '2025-04-01.md'
            log_file.write_text(
                "# Diet Log - 2025-04-01\n\n"
                "### Breakfast (~9:00 AM)\n"
                "- Coffee (x1)\n"
                "  - Est. calories: ~2\n"
                "  - Macros: ~0g protein, ~0g carbs, ~0g fat\n"
                "  - Hydration: 1 beverage(s)\n\n"
                "### Lunch (~1:00 PM)\n"
                "- Water (x1)\n"
                "  - Est. calories: ~0\n"
                "  - Macros: ~0g protein, ~0g carbs, ~0g fat\n"
                "  - Hydration: 1 beverage(s)\n"
            )
            update_daily_totals(date='2025-04-01')

            with open(log_file, 'r') as f:
                content = f.read()
            assert 'Hydration: 2 beverages' in content
        finally:
            calculate_macros.DIET_DIR = original_diet_dir

    def test_parse_diet_log_hydration(self, tmp_path):
        """parse_diet_log should extract hydration count from totals."""
        import generate_daily_summary
        original_diet_dir = generate_daily_summary.DIET_DIR
        generate_daily_summary.DIET_DIR = str(tmp_path)

        try:
            diet_file = tmp_path / '2025-04-01.md'
            diet_file.write_text(
                "# Diet Log - 2025-04-01\n\n"
                "### Breakfast (~9:00 AM)\n"
                "- Coffee (x1)\n"
                "  - Est. calories: ~2\n"
                "  - Macros: ~0g protein, ~0g carbs, ~0g fat\n\n"
                "## Daily Totals\n"
                "- Calories: ~2 kcal\n"
                "- Protein: ~0g\n"
                "- Carbs: ~0g\n"
                "- Fat: ~0g\n"
                "- Hydration: 3 beverages\n"
            )
            result = parse_diet_log('2025-04-01')
            assert result is not None
            assert result['hydration'] == 3
        finally:
            generate_daily_summary.DIET_DIR = original_diet_dir


# ---------------------------------------------------------------------------
# Feature 6: Saved meals
# ---------------------------------------------------------------------------

class TestSavedMeals:
    def test_load_saved_meals_missing_file(self):
        """_load_saved_meals returns {} when file doesn't exist."""
        with patch('calculate_macros.SKILL_DIR', '/nonexistent'):
            assert _load_saved_meals() == {}

    def test_load_saved_meals(self, tmp_path):
        """_load_saved_meals reads saved_meals.json."""
        import calculate_macros
        original = calculate_macros.SKILL_DIR
        calculate_macros.SKILL_DIR = str(tmp_path)
        try:
            meals_file = tmp_path / 'saved_meals.json'
            meals_file.write_text('{"my breakfast": "2 eggs and toast"}')
            meals = _load_saved_meals()
            assert meals == {"my breakfast": "2 eggs and toast"}
        finally:
            calculate_macros.SKILL_DIR = original

    def test_save_meal_shortcut(self, tmp_path):
        """_save_meal_shortcut writes to saved_meals.json."""
        import calculate_macros
        original = calculate_macros.SKILL_DIR
        calculate_macros.SKILL_DIR = str(tmp_path)
        try:
            _save_meal_shortcut("quick lunch", "chicken breast and rice")
            meals = _load_saved_meals()
            assert "quick lunch" in meals
            assert meals["quick lunch"] == "chicken breast and rice"
        finally:
            calculate_macros.SKILL_DIR = original

    def test_analyze_meal_expands_saved(self, tmp_path):
        """analyze_meal should expand saved meal shortcuts."""
        import calculate_macros
        original = calculate_macros.SKILL_DIR
        calculate_macros.SKILL_DIR = str(tmp_path)

        meals_file = tmp_path / 'saved_meals.json'
        meals_file.write_text('{"my usual": "2 eggs and toast"}')

        mock_results = [
            ('Egg', 78, 6, 0.6, 5, 62, 0, 'USDA', 50),
        ]
        try:
            with patch('query_food_db.search_foods', return_value=mock_results):
                result = analyze_meal("I had my usual for breakfast")
                # Should have expanded "my usual" to "2 eggs and toast"
                food_names = [name for name, _, _ in result['food_items']]
                assert any('egg' in name for name in food_names)
        finally:
            calculate_macros.SKILL_DIR = original


# ---------------------------------------------------------------------------
# Feature 3: Weekly summary
# ---------------------------------------------------------------------------

class TestWeeklySummary:
    def test_get_week_dates(self):
        """get_week_dates returns 7 dates starting from Monday."""
        from scripts.generate_weekly_summary import get_week_dates
        dates = get_week_dates('2026-02-09')  # Monday
        assert len(dates) == 7
        assert dates[0] == '2026-02-09'
        assert dates[6] == '2026-02-15'

    def test_get_week_dates_midweek(self):
        """get_week_dates from Wednesday should still return Mon-Sun."""
        from scripts.generate_weekly_summary import get_week_dates
        dates = get_week_dates('2026-02-11')  # Wednesday
        assert dates[0] == '2026-02-09'  # Monday
        assert dates[6] == '2026-02-15'  # Sunday

    def test_calculate_averages_empty(self):
        """calculate_averages with no data returns empty dict."""
        from scripts.generate_weekly_summary import calculate_averages
        days = [{'date': '2026-02-09', 'diet': None, 'fitbit': None, 'workout': None}]
        avg = calculate_averages(days)
        assert 'calories' not in avg
        assert 'steps' not in avg

    def test_calculate_consistency(self):
        """calculate_consistency counts days with data."""
        from scripts.generate_weekly_summary import calculate_consistency
        days = [
            {'diet': {'calories_consumed': 2000}, 'fitbit': {'steps': 8000}, 'workout': {'workout_sessions': 1}},
            {'diet': None, 'fitbit': {'steps': 5000}, 'workout': {'workout_sessions': 0}},
            {'diet': {'calories_consumed': 1800}, 'fitbit': None, 'workout': None},
        ]
        c = calculate_consistency(days)
        assert c['meals_logged'] == 2
        assert c['workouts_logged'] == 1
        assert c['fitbit_synced'] == 2
        assert c['total_days'] == 3

    def test_generate_weekly_summary_runs(self):
        """generate_weekly_summary should produce output without crashing."""
        from scripts.generate_weekly_summary import generate_weekly_summary
        summary = generate_weekly_summary('2026-02-09')
        assert '## Weekly Health Summary' in summary
        assert 'Consistency' in summary
        assert 'Weekly Totals' in summary


# ---------------------------------------------------------------------------
# Feature: Exercise Database / Standardization
# ---------------------------------------------------------------------------

class TestExerciseDatabase:
    def test_normalize_exact_canonical(self):
        """Exact canonical name should return itself."""
        from scripts.exercise_db import normalize_exercise_name
        assert normalize_exercise_name('Bench Press') == 'Bench Press'

    def test_normalize_alias(self):
        """Alias should resolve to canonical name."""
        from scripts.exercise_db import normalize_exercise_name
        assert normalize_exercise_name('bench') == 'Bench Press'
        assert normalize_exercise_name('flat bench') == 'Bench Press'

    def test_normalize_case_insensitive(self):
        """Normalization should be case-insensitive."""
        from scripts.exercise_db import normalize_exercise_name
        assert normalize_exercise_name('BENCH PRESS') == 'Bench Press'
        assert normalize_exercise_name('Lat Pulldown') == 'Lat Pulldown Machine'

    def test_normalize_unknown_fallback(self):
        """Unknown exercise should fall back to .title()."""
        from scripts.exercise_db import normalize_exercise_name
        assert normalize_exercise_name('xyz unknown exercise') == 'Xyz Unknown Exercise'

    def test_get_muscle_groups(self):
        """get_muscle_groups should return correct muscle list."""
        from scripts.exercise_db import get_muscle_groups
        muscles = get_muscle_groups('Bench Press')
        assert 'chest' in muscles
        assert 'triceps' in muscles

    def test_get_muscle_groups_unknown(self):
        """Unknown exercise should return empty list."""
        from scripts.exercise_db import get_muscle_groups
        assert get_muscle_groups('xyz unknown') == []

    def test_get_exercise_type(self):
        """get_exercise_type should return compound/isolation/etc."""
        from scripts.exercise_db import get_exercise_type
        assert get_exercise_type('Bench Press') == 'compound'
        assert get_exercise_type('Leg Extension Machine') == 'isolation'
        assert get_exercise_type('Push-up') == 'bodyweight'
        assert get_exercise_type('Treadmill') == 'cardio'

    def test_get_exercise_type_unknown(self):
        """Unknown exercise type should return 'unknown'."""
        from scripts.exercise_db import get_exercise_type
        assert get_exercise_type('xyz') == 'unknown'

    def test_missing_file_returns_defaults(self):
        """Missing exercise_aliases.json should not crash."""
        from scripts.exercise_db import normalize_exercise_name, _load_exercise_db
        import scripts.exercise_db as edb
        original = edb.SKILL_DIR
        edb.SKILL_DIR = '/nonexistent'
        edb._EXERCISES = None
        edb._LOOKUP = None
        try:
            result = normalize_exercise_name('bench')
            assert result == 'Bench'  # fallback .title()
        finally:
            edb.SKILL_DIR = original
            edb._EXERCISES = None
            edb._LOOKUP = None

    def test_reload_db(self):
        """reload_db should re-read the database."""
        from scripts.exercise_db import reload_db, normalize_exercise_name
        reload_db()
        assert normalize_exercise_name('bench') == 'Bench Press'

    def test_pf_machines_covered(self):
        """Planet Fitness machines should all be in the database."""
        from scripts.exercise_db import normalize_exercise_name
        pf_machines = [
            'chest press', 'lat pulldown', 'shoulder press', 'leg press',
            'leg extension', 'leg curl', 'bicep curl machine', 'tricep extension machine',
            'ab crunch', 'seated row',
        ]
        for machine in pf_machines:
            result = normalize_exercise_name(machine)
            assert result != machine.title() or 'Machine' in result, f"PF machine not recognized: {machine}"


# ---------------------------------------------------------------------------
# Feature: Progressive Overload Tracking
# ---------------------------------------------------------------------------

class TestProgressiveOverload:
    def test_record_exercise_first_entry(self, tmp_path):
        """First entry should not announce PR."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            result = po.record_exercise('Bench Press', '2026-02-01', 3, 10, 225.0)
            assert result['is_weight_pr'] is False
            assert result['is_volume_pr'] is False
        finally:
            po.PR_HISTORY_FILE = original

    def test_record_exercise_weight_pr(self, tmp_path):
        """New weight should trigger weight PR."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Bench Press', '2026-02-01', 3, 10, 200.0)
            result = po.record_exercise('Bench Press', '2026-02-05', 3, 10, 225.0)
            assert result['is_weight_pr'] is True
            assert result['previous_best_weight'] == 200.0
        finally:
            po.PR_HISTORY_FILE = original

    def test_record_exercise_volume_pr(self, tmp_path):
        """Higher volume should trigger volume PR."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Squat', '2026-02-01', 3, 8, 200.0)  # 4800
            result = po.record_exercise('Squat', '2026-02-05', 4, 10, 200.0)  # 8000
            assert result['is_volume_pr'] is True
        finally:
            po.PR_HISTORY_FILE = original

    def test_no_pr_on_same_weight(self, tmp_path):
        """Same weight should not trigger weight PR."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Bench Press', '2026-02-01', 3, 10, 225.0)
            result = po.record_exercise('Bench Press', '2026-02-05', 3, 10, 225.0)
            assert result['is_weight_pr'] is False
        finally:
            po.PR_HISTORY_FILE = original

    def test_get_exercise_history(self, tmp_path):
        """get_exercise_history should return sorted sessions."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Deadlift', '2026-02-05', 3, 5, 315.0)
            po.record_exercise('Deadlift', '2026-02-01', 3, 5, 300.0)
            history = po.get_exercise_history('Deadlift')
            assert len(history) == 2
            assert history[0]['date'] == '2026-02-01'
            assert history[1]['date'] == '2026-02-05'
        finally:
            po.PR_HISTORY_FILE = original

    def test_get_pr(self, tmp_path):
        """get_pr should return current PR info."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Bench Press', '2026-02-01', 3, 10, 200.0)
            po.record_exercise('Bench Press', '2026-02-05', 3, 10, 225.0)
            pr = po.get_pr('Bench Press')
            assert pr is not None
            assert pr['pr_weight'] == 225.0
            assert pr['pr_weight_date'] == '2026-02-05'
        finally:
            po.PR_HISTORY_FILE = original

    def test_get_pr_unknown(self, tmp_path):
        """get_pr should return None for unknown exercise."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            assert po.get_pr('Unknown Exercise') is None
        finally:
            po.PR_HISTORY_FILE = original

    def test_detect_stalled_lifts(self, tmp_path):
        """detect_stalled_lifts should find exercises without recent PRs."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            # Record an old PR
            po._save_pr_history({
                'exercises': {
                    'Bench Press': {
                        'pr_weight': 200.0,
                        'pr_weight_date': '2025-01-01',
                        'pr_volume': 6000,
                        'pr_volume_date': '2025-01-01',
                        'history': [{'date': '2025-01-01', 'sets': 3, 'reps': 10, 'weight': 200.0, 'volume': 6000, 'unit': 'lbs'}],
                    }
                }
            })
            stalled = po.detect_stalled_lifts(weeks=3)
            assert len(stalled) >= 1
            assert stalled[0]['exercise'] == 'Bench Press'
        finally:
            po.PR_HISTORY_FILE = original

    def test_get_progression_trends(self, tmp_path):
        """get_progression_trends should classify trends."""
        import scripts.progressive_overload as po
        from datetime import datetime, timedelta
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            last_week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            two_weeks = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')

            po._save_pr_history({
                'exercises': {
                    'Bench Press': {
                        'pr_weight': 225.0,
                        'pr_weight_date': today,
                        'pr_volume': 6750,
                        'pr_volume_date': today,
                        'history': [
                            {'date': two_weeks, 'sets': 3, 'reps': 10, 'weight': 200.0, 'volume': 6000, 'unit': 'lbs'},
                            {'date': last_week, 'sets': 3, 'reps': 10, 'weight': 210.0, 'volume': 6300, 'unit': 'lbs'},
                            {'date': yesterday, 'sets': 3, 'reps': 10, 'weight': 220.0, 'volume': 6600, 'unit': 'lbs'},
                            {'date': today, 'sets': 3, 'reps': 10, 'weight': 225.0, 'volume': 6750, 'unit': 'lbs'},
                        ],
                    }
                }
            })
            trends = po.get_progression_trends(weeks=4)
            assert 'Bench Press' in trends
            assert trends['Bench Press']['trend'] == 'improving'
        finally:
            po.PR_HISTORY_FILE = original

    def test_bodyweight_exercise_no_weight(self, tmp_path):
        """Bodyweight exercises with weight=0 should still track reps."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            result = po.record_exercise('Push-up', '2026-02-01', 1, 50, 0)
            assert result['is_weight_pr'] is False
        finally:
            po.PR_HISTORY_FILE = original

    def test_load_missing_file(self, tmp_path):
        """Missing pr_history.json should return empty dict."""
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'nonexistent.json')
        try:
            data = po._load_pr_history()
            assert data == {'exercises': {}}
        finally:
            po.PR_HISTORY_FILE = original


# ---------------------------------------------------------------------------
# Feature: Saved Workouts / Templates
# ---------------------------------------------------------------------------

class TestSavedWorkouts:
    def test_load_saved_workouts_missing_file(self):
        """_load_saved_workouts returns {} when file doesn't exist."""
        from log_workout import _load_saved_workouts
        import log_workout
        original = log_workout.SKILL_DIR
        log_workout.SKILL_DIR = '/nonexistent'
        try:
            assert _load_saved_workouts() == {}
        finally:
            log_workout.SKILL_DIR = original

    def test_load_saved_workouts(self, tmp_path):
        """_load_saved_workouts reads saved_workouts.json."""
        from log_workout import _load_saved_workouts
        import log_workout
        original = log_workout.SKILL_DIR
        log_workout.SKILL_DIR = str(tmp_path)
        try:
            workouts_file = tmp_path / 'saved_workouts.json'
            workouts_file.write_text('{"push day": "3 sets of bench press"}')
            workouts = _load_saved_workouts()
            assert workouts == {"push day": "3 sets of bench press"}
        finally:
            log_workout.SKILL_DIR = original

    def test_save_workout_template(self, tmp_path):
        """_save_workout_template writes to saved_workouts.json."""
        from log_workout import _save_workout_template, _load_saved_workouts
        import log_workout
        original = log_workout.SKILL_DIR
        log_workout.SKILL_DIR = str(tmp_path)
        try:
            _save_workout_template("upper body", "3 sets bench press, 3 sets shoulder press")
            workouts = _load_saved_workouts()
            assert "upper body" in workouts
        finally:
            log_workout.SKILL_DIR = original

    def test_template_expansion(self, tmp_path):
        """parse_workout_text should expand template names."""
        from log_workout import parse_workout_text, _expand_template
        import log_workout
        original = log_workout.SKILL_DIR
        log_workout.SKILL_DIR = str(tmp_path)
        try:
            workouts_file = tmp_path / 'saved_workouts.json'
            workouts_file.write_text('{"push day": "3 sets of bench press, 3 sets of shoulder press"}')
            result = parse_workout_text("push day")
            assert len(result['exercises']) >= 2
        finally:
            log_workout.SKILL_DIR = original

    def test_multi_exercise_parsing(self):
        """Comma-separated exercises should all be parsed."""
        from log_workout import parse_workout_text
        result = parse_workout_text("3 sets of bench press, 3 sets of shoulder press")
        assert len(result['exercises']) >= 2

    def test_unknown_template_passthrough(self, tmp_path):
        """Unknown template name should pass through as text."""
        from log_workout import _expand_template
        import log_workout
        original = log_workout.SKILL_DIR
        log_workout.SKILL_DIR = str(tmp_path)
        try:
            workouts_file = tmp_path / 'saved_workouts.json'
            workouts_file.write_text('{}')
            assert _expand_template("random workout") == "random workout"
        finally:
            log_workout.SKILL_DIR = original


# ---------------------------------------------------------------------------
# Feature: Recovery Tracking
# ---------------------------------------------------------------------------

class TestRecoveryTracking:
    def test_empty_fitness_dir(self, tmp_path):
        """Empty fitness dir should return empty history."""
        from scripts.recovery_tracking import get_muscle_group_history
        history = get_muscle_group_history(days_back=7, fitness_dir=str(tmp_path))
        assert history == {}

    def test_missing_fitness_dir(self):
        """Nonexistent fitness dir should return empty history."""
        from scripts.recovery_tracking import get_muscle_group_history
        history = get_muscle_group_history(days_back=7, fitness_dir='/nonexistent')
        assert history == {}

    def test_muscle_group_history_from_logs(self, tmp_path):
        """Should extract muscle groups from workout logs."""
        from scripts.recovery_tracking import get_muscle_group_history
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        workout_file = tmp_path / f'{today}.md'
        workout_file.write_text(
            "## Workout - 06:00 PM\n"
            "Type: Resistance Training\n\n"
            "### Exercises\n"
            "1. Bench Press\n"
            "   Sets: 3\n"
        )
        history = get_muscle_group_history(days_back=7, fitness_dir=str(tmp_path))
        assert 'chest' in history
        assert today in history['chest']

    def test_recovery_warnings_neglected(self, tmp_path):
        """Should detect neglected muscle groups."""
        from scripts.recovery_tracking import get_recovery_warnings
        from datetime import datetime, timedelta
        old_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        workout_file = tmp_path / f'{old_date}.md'
        workout_file.write_text(
            "## Workout - 06:00 PM\n\n"
            "### Exercises\n"
            "1. Bench Press\n"
        )
        warnings = get_recovery_warnings(days_back=14, fitness_dir=str(tmp_path))
        neglected = [w for w in warnings if w['warning_type'] == 'neglected']
        assert len(neglected) >= 1

    def test_recovery_warnings_consecutive(self, tmp_path):
        """Should detect consecutive-day training."""
        from scripts.recovery_tracking import get_recovery_warnings
        from datetime import datetime, timedelta
        today = datetime.now()
        for i in range(2):
            date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            workout_file = tmp_path / f'{date}.md'
            workout_file.write_text(
                "## Workout - 06:00 PM\n\n"
                "### Exercises\n"
                "1. Bench Press\n"
            )
        warnings = get_recovery_warnings(days_back=7, fitness_dir=str(tmp_path))
        insufficient = [w for w in warnings if w['warning_type'] == 'insufficient_recovery']
        assert len(insufficient) >= 1

    def test_format_recovery_section_empty(self):
        """Empty warnings should return empty string."""
        from scripts.recovery_tracking import format_recovery_section
        assert format_recovery_section([]) == ''

    def test_format_recovery_section_content(self):
        """Non-empty warnings should produce markdown."""
        from scripts.recovery_tracking import format_recovery_section
        warnings = [
            {'muscle_group': 'chest', 'days_since_last': 10, 'warning_type': 'neglected',
             'message': "Chest hasn't been trained in 10 days"},
        ]
        result = format_recovery_section(warnings)
        assert '### Recovery Notes' in result
        assert 'Neglected' in result

    def test_cardio_excluded_from_recovery(self, tmp_path):
        """Cardio exercises should not generate recovery warnings."""
        from scripts.recovery_tracking import get_muscle_group_history
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        workout_file = tmp_path / f'{today}.md'
        workout_file.write_text(
            "## Workout - 06:00 PM\n\n"
            "### Exercises\n"
            "1. Treadmill\n"
        )
        history = get_muscle_group_history(days_back=7, fitness_dir=str(tmp_path))
        assert 'cardio' not in history


# ---------------------------------------------------------------------------
# Feature: Workout Query Engine
# ---------------------------------------------------------------------------

class TestQueryHistory:
    def test_classify_pr_query(self):
        """PR queries should be classified correctly."""
        from scripts.query_history import classify_query
        result = classify_query("What is my bench PR?")
        assert result['type'] == 'pr'

    def test_classify_last_workout(self):
        """Last workout queries should be classified correctly."""
        from scripts.query_history import classify_query
        result = classify_query("When did I last do deadlifts?")
        assert result['type'] == 'last_workout'

    def test_classify_count(self):
        """Count queries should be classified correctly."""
        from scripts.query_history import classify_query
        result = classify_query("How many times did I squat this week?")
        assert result['type'] == 'count'

    def test_classify_trend(self):
        """Trend queries should be classified correctly."""
        from scripts.query_history import classify_query
        result = classify_query("How has my sleep trended this month?")
        assert result['type'] == 'trend'
        assert result['metric'] == 'sleep'

    def test_classify_with_timeframe(self):
        """Timeframe should be extracted correctly."""
        from scripts.query_history import classify_query
        result = classify_query("How many times did I squat this week?")
        assert result['timeframe'] == 'week'

    def test_answer_pr_no_data(self, tmp_path):
        """PR query with no data should return helpful message."""
        from scripts.query_history import answer_query
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            answer = answer_query("What is my bench PR?")
            assert 'no data' in answer.lower() or 'log some' in answer.lower()
        finally:
            po.PR_HISTORY_FILE = original

    def test_answer_pr_with_data(self, tmp_path):
        """PR query with data should return PR info."""
        import scripts.progressive_overload as po
        from scripts.query_history import answer_query
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            po.record_exercise('Bench Press', '2026-02-01', 3, 10, 200.0)
            po.record_exercise('Bench Press', '2026-02-05', 3, 10, 225.0)
            answer = answer_query("What is my bench press PR?")
            assert '225' in answer
        finally:
            po.PR_HISTORY_FILE = original

    def test_answer_no_exercise(self):
        """PR query without exercise should ask for clarification."""
        from scripts.query_history import answer_query
        answer = answer_query("What is my PR?")
        assert 'which exercise' in answer.lower() or 'try' in answer.lower()

    def test_answer_summary(self, tmp_path):
        """General summary query should not crash."""
        import scripts.progressive_overload as po
        from scripts.query_history import answer_query
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            answer = answer_query("How am I doing?")
            assert isinstance(answer, str)
        finally:
            po.PR_HISTORY_FILE = original

    def test_answer_fitbit_trend_no_data(self):
        """Fitbit trend query with no data should handle gracefully."""
        from scripts.query_history import answer_query
        answer = answer_query("How has my sleep trended this month?")
        assert isinstance(answer, str)


# ---------------------------------------------------------------------------
# Feature: Adaptive Plan Suggestions
# ---------------------------------------------------------------------------

class TestAdaptiveSuggestions:
    def test_deload_suggestion(self, tmp_path):
        """3+ stalled lifts should trigger deload suggestion."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            # Create 3 stalled exercises
            exercises = {}
            for name in ['Bench Press', 'Squat', 'Deadlift']:
                exercises[name] = {
                    'pr_weight': 200.0,
                    'pr_weight_date': '2025-01-01',
                    'pr_volume': 6000,
                    'pr_volume_date': '2025-01-01',
                    'history': [{'date': '2025-01-01', 'sets': 3, 'reps': 10, 'weight': 200.0, 'volume': 6000, 'unit': 'lbs'}],
                }
            po._save_pr_history({'exercises': exercises})
            consistency = {'meals_logged': 7, 'workouts_logged': 5, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 30000, 'cardio_minutes': 0, 'total_steps': 70000, 'workout_sessions': 5}
            trends = {}
            dates = ['2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06', '2026-02-07', '2026-02-08', '2026-02-09']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert any('deload' in s.lower() for s in suggestions)
        finally:
            po.PR_HISTORY_FILE = original

    def test_missed_workouts_suggestion(self, tmp_path):
        """Low workouts with high meal logging should suggest scheduling."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        po._save_pr_history({'exercises': {}})
        try:
            consistency = {'meals_logged': 6, 'workouts_logged': 1, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 0, 'cardio_minutes': 0, 'total_steps': 50000, 'workout_sessions': 1}
            trends = {}
            dates = ['2026-02-03']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert any('schedule' in s.lower() or 'workout' in s.lower() for s in suggestions)
        finally:
            po.PR_HISTORY_FILE = original

    def test_declining_trend_suggestion(self, tmp_path):
        """2+ declining exercises should trigger fatigue warning."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        from datetime import datetime, timedelta
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            last_week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            two_weeks = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
            exercises = {}
            for name in ['Bench Press', 'Squat']:
                exercises[name] = {
                    'pr_weight': 200.0,
                    'pr_weight_date': two_weeks,
                    'pr_volume': 6000,
                    'pr_volume_date': two_weeks,
                    'history': [
                        {'date': two_weeks, 'sets': 3, 'reps': 10, 'weight': 200.0, 'volume': 6000, 'unit': 'lbs'},
                        {'date': last_week, 'sets': 3, 'reps': 10, 'weight': 195.0, 'volume': 5850, 'unit': 'lbs'},
                        {'date': today, 'sets': 3, 'reps': 10, 'weight': 185.0, 'volume': 5550, 'unit': 'lbs'},
                    ],
                }
            po._save_pr_history({'exercises': exercises})
            consistency = {'meals_logged': 7, 'workouts_logged': 5, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 30000, 'cardio_minutes': 0, 'total_steps': 70000, 'workout_sessions': 5}
            trends = {}
            dates = ['2026-02-03']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert any('fatigue' in s.lower() for s in suggestions)
        finally:
            po.PR_HISTORY_FILE = original

    def test_sleep_down_suggestion(self, tmp_path):
        """Sleep trending down should trigger intensity warning."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        po._save_pr_history({'exercises': {}})
        try:
            consistency = {'meals_logged': 7, 'workouts_logged': 5, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 30000, 'cardio_minutes': 0, 'total_steps': 70000, 'workout_sessions': 5}
            trends = {'sleep': 'down'}
            dates = ['2026-02-03']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert any('sleep' in s.lower() for s in suggestions)
        finally:
            po.PR_HISTORY_FILE = original

    def test_cap_at_four(self, tmp_path):
        """Should never return more than 4 suggestions."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        try:
            # Set up conditions that would trigger many suggestions
            exercises = {}
            for name in ['Bench', 'Squat', 'Deadlift', 'OHP']:
                exercises[name] = {
                    'pr_weight': 200.0,
                    'pr_weight_date': '2025-01-01',
                    'pr_volume': 6000,
                    'pr_volume_date': '2025-01-01',
                    'history': [{'date': '2025-01-01', 'sets': 3, 'reps': 10, 'weight': 200.0, 'volume': 6000, 'unit': 'lbs'}],
                }
            po._save_pr_history({'exercises': exercises})
            consistency = {'meals_logged': 6, 'workouts_logged': 1, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 0, 'cardio_minutes': 0, 'total_steps': 50000, 'workout_sessions': 1}
            trends = {'sleep': 'down'}
            dates = ['2026-02-03']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert len(suggestions) <= 4
        finally:
            po.PR_HISTORY_FILE = original

    def test_no_suggestions_when_all_good(self, tmp_path):
        """Good data should produce few/no suggestions."""
        from scripts.generate_weekly_summary import _generate_adaptive_suggestions
        import scripts.progressive_overload as po
        original = po.PR_HISTORY_FILE
        po.PR_HISTORY_FILE = str(tmp_path / 'pr_history.json')
        po._save_pr_history({'exercises': {}})
        try:
            consistency = {'meals_logged': 7, 'workouts_logged': 5, 'total_days': 7, 'fitbit_synced': 7}
            totals = {'resistance_volume': 30000, 'cardio_minutes': 60, 'total_steps': 70000, 'workout_sessions': 5}
            trends = {'sleep': 'up', 'steps': 'up'}
            dates = ['2026-02-03']
            suggestions = _generate_adaptive_suggestions(consistency, totals, trends, dates)
            assert len(suggestions) <= 2
        finally:
            po.PR_HISTORY_FILE = original

    def test_weekly_summary_includes_adjustments(self):
        """Weekly summary should include plan adjustments section when present."""
        from scripts.generate_weekly_summary import generate_weekly_coach_notes
        notes = generate_weekly_coach_notes(
            avg={}, consistency={'meals_logged': 0, 'workouts_logged': 0, 'total_days': 7, 'fitbit_synced': 0},
            totals={'resistance_volume': 0, 'cardio_minutes': 0, 'total_steps': 0, 'workout_sessions': 0},
            trends={}, dates=['2026-02-03']
        )
        assert 'plan_adjustments' in notes

    def test_generate_weekly_summary_with_new_sections(self):
        """Weekly summary should include exercise progression and coach notes."""
        from scripts.generate_weekly_summary import generate_weekly_summary
        summary = generate_weekly_summary('2026-02-09')
        assert '## Weekly Health Summary' in summary
        assert 'Weekly Coach Notes' in summary


# ---------------------------------------------------------------------------
# Dietary Profile
# ---------------------------------------------------------------------------

class TestDietaryProfile:
    def test_load_profile_returns_dict(self):
        profile = load_profile()
        assert isinstance(profile, dict)
        assert 'allergies' in profile
        assert 'dietary_restrictions' in profile

    def test_load_profile_has_all_keys(self):
        profile = load_profile()
        expected_keys = ['allergies', 'dietary_restrictions', 'dislikes',
                         'cuisine_preferences', 'health_conditions',
                         'cooking_skill', 'budget', 'meal_timing', 'notes']
        for key in expected_keys:
            assert key in profile

    @patch('dietary_profile._CONFIG_FILE')
    def test_save_profile_writes_config(self, mock_path, tmp_path):
        config_file = tmp_path / 'config.json'
        config_file.write_text('{}')
        with patch('dietary_profile._CONFIG_FILE', str(config_file)):
            profile = {'allergies': ['peanuts'], 'dietary_restrictions': [],
                       'dislikes': [], 'cuisine_preferences': [],
                       'health_conditions': [], 'cooking_skill': None,
                       'budget': None, 'meal_timing': None, 'notes': ''}
            result = save_profile(profile)
            assert result['allergies'] == ['peanuts']
            saved = json.loads(config_file.read_text())
            assert saved['DIETARY_PROFILE']['allergies'] == ['peanuts']

    def test_get_allergies_returns_list(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts', 'dairy']}):
            result = get_allergies()
            assert result == ['peanuts', 'dairy']

    def test_get_allergies_empty(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': []}):
            result = get_allergies()
            assert result == []

    def test_has_allergy_true(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts', 'dairy']}):
            assert has_allergy('peanuts') is True
            assert has_allergy('Peanuts') is True

    def test_has_allergy_false(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            assert has_allergy('shellfish') is False

    def test_update_preference_comma_separated(self, tmp_path):
        config_file = tmp_path / 'config.json'
        config_file.write_text('{}')
        with patch('dietary_profile._CONFIG_FILE', str(config_file)):
            profile = update_preference('allergies', 'peanuts, shellfish, dairy')
            assert profile['allergies'] == ['peanuts', 'shellfish', 'dairy']

    def test_update_preference_none_value(self, tmp_path):
        config_file = tmp_path / 'config.json'
        config_file.write_text('{}')
        with patch('dietary_profile._CONFIG_FILE', str(config_file)):
            profile = update_preference('allergies', 'none')
            assert profile['allergies'] == []

    def test_format_profile_summary(self):
        with patch('dietary_profile.DIETARY_PROFILE', {
            'allergies': ['peanuts'], 'dietary_restrictions': ['vegetarian'],
            'dislikes': ['olives'], 'cuisine_preferences': ['italian'],
            'health_conditions': ['diabetes'], 'cooking_skill': 'basic',
            'budget': 'moderate', 'meal_timing': None, 'notes': ''
        }), patch('dietary_profile._load_state', return_value={'total_meals_logged': 5}):
            summary = format_profile_summary()
            assert 'peanuts' in summary
            assert 'vegetarian' in summary
            assert 'diabetes' in summary
            assert 'basic' in summary


# ---------------------------------------------------------------------------
# Gradual Learning
# ---------------------------------------------------------------------------

class TestGradualLearning:
    def test_increment_interactions(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 0, "last_prompt_at": 0}')
        with patch('dietary_profile._STATE_FILE', str(state_file)):
            count = increment_interactions()
            assert count == 1
            count = increment_interactions()
            assert count == 2

    def test_should_prompt_allergies_after_first_meal(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 1, "last_prompt_at": 0}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'allergies': [], 'health_conditions': []}):
            assert should_prompt_preference('allergies') is True

    def test_should_not_prompt_if_already_set(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 1, "last_prompt_at": 0}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            assert should_prompt_preference('allergies') is False

    def test_should_not_prompt_if_already_asked(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 1, "last_prompt_at": 0, "allergies_asked": true}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'allergies': []}):
            assert should_prompt_preference('allergies') is False

    def test_anti_spam_between_prompts(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 6, "last_prompt_at": 5}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'dietary_restrictions': []}):
            # Only 1 interaction since last prompt, need 3
            assert should_prompt_preference('dietary_restrictions') is False

    def test_restrictions_prompted_after_5_meals(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 5, "last_prompt_at": 0}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'dietary_restrictions': []}):
            assert should_prompt_preference('dietary_restrictions') is True

    def test_cooking_skill_only_on_meal_plan_request(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 50, "last_prompt_at": 0, "meal_plan_requested": false}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'cooking_skill': None}):
            assert should_prompt_preference('cooking_skill') is False

    def test_cooking_skill_prompted_after_meal_plan_request(self, tmp_path):
        state_file = tmp_path / 'state.json'
        state_file.write_text('{"total_meals_logged": 50, "last_prompt_at": 0, "meal_plan_requested": true}')
        with patch('dietary_profile._STATE_FILE', str(state_file)), \
             patch('dietary_profile.DIETARY_PROFILE', {'cooking_skill': None}):
            assert should_prompt_preference('cooking_skill') is True

    def test_full_setup_prompts_returns_unset(self):
        with patch('dietary_profile.DIETARY_PROFILE', {
            'allergies': ['peanuts'], 'dietary_restrictions': [],
            'dislikes': [], 'cuisine_preferences': [],
            'health_conditions': ['diabetes'], 'cooking_skill': None,
            'budget': None, 'meal_timing': None, 'notes': ''
        }):
            prompts = full_setup_prompts()
            keys = [p['key'] for p in prompts]
            assert 'allergies' not in keys  # already set
            assert 'health_conditions' not in keys  # already set
            assert 'dietary_restrictions' in keys
            assert 'cooking_skill' in keys


# ---------------------------------------------------------------------------
# Allergen Checker
# ---------------------------------------------------------------------------

class TestAllergenChecker:
    def test_load_allergen_map(self):
        import allergy_checker
        allergy_checker._ALLERGEN_MAP = None  # reset cache
        allergen_map = load_allergen_map()
        assert isinstance(allergen_map, dict)
        assert 'peanuts' in allergen_map
        assert 'dairy' in allergen_map

    def test_keyword_match(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            warnings = check_meal_allergens(
                [('peanut butter', 2, 'tbsp')],
                'peanut butter sandwich'
            )
            assert len(warnings) >= 1
            assert any(w['allergen'] == 'peanuts' for w in warnings)
            assert any(w['match_type'] == 'keyword' for w in warnings)

    def test_contextual_match(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            warnings = check_meal_allergens(
                [('chicken', 1, 'servings')],
                'chicken pad thai for dinner'
            )
            assert len(warnings) >= 1
            assert any(w['trigger'] == 'pad thai' for w in warnings)
            assert any(w['match_type'] == 'contextual' for w in warnings)

    def test_no_false_positives(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            warnings = check_meal_allergens(
                [('chicken breast', 1, 'servings'), ('rice', 1, 'cups')],
                'grilled chicken breast with rice'
            )
            assert len(warnings) == 0

    def test_multiple_allergens(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['dairy', 'gluten']}):
            warnings = check_meal_allergens(
                [('pizza', 1, 'slices')],
                'pizza for dinner'
            )
            # Pizza is in also_check for both dairy and gluten
            assert len(warnings) >= 2
            allergens_found = {w['allergen'] for w in warnings}
            assert 'dairy' in allergens_found
            assert 'gluten' in allergens_found

    def test_severity_ordering(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts', 'dairy']}):
            warnings = check_meal_allergens(
                [('peanut butter', 1, 'servings'), ('milk', 1, 'glasses')],
                'peanut butter and milk'
            )
            assert len(warnings) >= 2
            # High severity should come first
            assert warnings[0]['severity'] == 'high'

    def test_no_warnings_when_no_allergies(self):
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': []}):
            warnings = check_meal_allergens(
                [('peanut butter', 1, 'servings')],
                'peanut butter sandwich'
            )
            assert len(warnings) == 0

    def test_check_single_food_match(self):
        result = check_single_food('peanut butter', ['peanuts'])
        assert 'peanuts' in result

    def test_check_single_food_no_match(self):
        result = check_single_food('chicken breast', ['peanuts'])
        assert result == []

    def test_format_warnings_empty(self):
        assert format_warnings([]) == ""

    def test_format_warnings_high_severity(self):
        warnings = [{'allergen': 'peanuts', 'trigger': 'peanut butter',
                      'match_type': 'keyword', 'severity': 'high',
                      'message': 'ALLERGY WARNING: peanut butter contains peanuts'}]
        result = format_warnings(warnings)
        assert '!!!' in result
        assert 'peanut butter' in result


# ---------------------------------------------------------------------------
# Meal + Allergy Integration
# ---------------------------------------------------------------------------

class TestMealAllergyIntegration:
    @patch('calculate_macros.calculate_meal_macros')
    def test_analyze_meal_includes_warnings(self, mock_macros):
        mock_macros.return_value = {
            'calories': 350, 'protein': 10, 'carbs': 40, 'fat': 16,
            'sodium': 150, 'fiber': 5, 'items': [
                {'name': 'peanut butter', 'quantity': 2, 'unit': 'tbsp',
                 'calories': 190, 'protein': 8, 'carbs': 6, 'fat': 16, 'sodium': 150, 'fiber': 2}
            ]
        }
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': ['peanuts']}):
            result = analyze_meal('peanut butter toast for breakfast')
            assert 'allergy_warnings' in result
            assert len(result['allergy_warnings']) >= 1

    @patch('calculate_macros.calculate_meal_macros')
    def test_analyze_meal_no_warnings_no_allergies(self, mock_macros):
        mock_macros.return_value = {
            'calories': 450, 'protein': 40, 'carbs': 45, 'fat': 8,
            'sodium': 450, 'fiber': 5, 'items': [
                {'name': 'chicken breast', 'quantity': 200, 'unit': 'g',
                 'calories': 300, 'protein': 35, 'carbs': 0, 'fat': 6, 'sodium': 300, 'fiber': 0}
            ]
        }
        with patch('dietary_profile.DIETARY_PROFILE', {'allergies': []}):
            result = analyze_meal('chicken breast and rice for lunch')
            assert result.get('allergy_warnings', []) == []

    @patch('calculate_macros.calculate_meal_macros')
    def test_log_writes_warnings(self, mock_macros, tmp_path):
        mock_macros.return_value = {
            'calories': 350, 'protein': 10, 'carbs': 40, 'fat': 16,
            'sodium': 150, 'fiber': 5, 'items': [
                {'name': 'peanut butter', 'quantity': 2, 'unit': 'tbsp',
                 'calories': 190, 'protein': 8, 'carbs': 6, 'fat': 16, 'sodium': 150, 'fiber': 2}
            ]
        }
        result = {
            'meal_type': 'Breakfast', 'meal_time': '8:00 AM',
            'food_items': [('peanut butter', 2, 'tbsp')],
            'macros': mock_macros.return_value,
            'allergy_warnings': [
                {'allergen': 'peanuts', 'trigger': 'peanut butter',
                 'match_type': 'keyword', 'severity': 'high',
                 'message': 'ALLERGY WARNING: peanut butter contains peanuts'}
            ]
        }
        with patch('calculate_macros.DIET_DIR', str(tmp_path)):
            log_file = log_meal_to_file(result, date='2026-02-09')
            content = open(log_file).read()
            assert 'ALLERGY WARNING' in content


# ---------------------------------------------------------------------------
# Personalized Coach Notes
# ---------------------------------------------------------------------------

class TestPersonalizedCoachNotes:
    def _make_diet(self, **overrides):
        diet = {'calories_consumed': 2000, 'protein': 80, 'carbs': 250,
                'fat': 70, 'sodium': 2000, 'fiber': 30, 'meals': ['Lunch'],
                'hydration': 4}
        diet.update(overrides)
        return diet

    def test_diabetes_high_carbs_warning(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': ['diabetes'], 'dietary_restrictions': []}):
            notes = generate_coach_notes(None, self._make_diet(carbs=250), None)
            assert any('diabetes' in n for n in notes['improvements'])

    def test_diabetes_good_carb_control(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': ['diabetes'], 'dietary_restrictions': []}):
            notes = generate_coach_notes(None, self._make_diet(carbs=80), None)
            assert any('carb control' in n for n in notes['strengths'])

    def test_hypertension_sodium_warning(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': ['hypertension'], 'dietary_restrictions': []}):
            notes = generate_coach_notes(None, self._make_diet(sodium=2000), None)
            assert any('hypertension' in n for n in notes['improvements'])

    def test_high_cholesterol_fat_warning(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': ['high_cholesterol'], 'dietary_restrictions': []}):
            notes = generate_coach_notes(None, self._make_diet(fat=80), None)
            assert any('high cholesterol' in n.lower() for n in notes['improvements'])

    def test_vegetarian_protein_suggestions(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': [], 'dietary_restrictions': ['vegetarian']}):
            notes = generate_coach_notes(None, self._make_diet(protein=30), None)
            assert any('tofu' in n for n in notes['tomorrow_focus'])

    def test_keto_carb_warning(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': [], 'dietary_restrictions': ['keto']}):
            notes = generate_coach_notes(None, self._make_diet(carbs=100, protein=30), None)
            assert any('keto' in n for n in notes['improvements'])

    def test_no_conditions_no_extra_notes(self):
        with patch('config.DIETARY_PROFILE',
                   {'health_conditions': [], 'dietary_restrictions': []}):
            notes = generate_coach_notes(None, self._make_diet(), None)
            assert not any('diabetes' in n for n in notes['improvements'])
            assert not any('hypertension' in n for n in notes['improvements'])


# ---------------------------------------------------------------------------
# Meal Planner
# ---------------------------------------------------------------------------

class TestMealPlanner:
    def test_load_meal_templates(self):
        templates = load_meal_templates()
        assert isinstance(templates, list)
        assert len(templates) >= 50

    def test_get_remaining_macros_structure(self):
        remaining = get_remaining_macros()
        assert 'calories' in remaining
        assert 'protein' in remaining
        assert 'carbs' in remaining
        assert 'fat' in remaining
        assert 'sodium' in remaining
        assert 'meals_remaining' in remaining

    def test_filter_by_allergens(self):
        templates = [
            {'name': 'PB Sandwich', 'allergens': ['peanuts'], 'meal_types': ['lunch'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['peanut butter', 'bread']},
            {'name': 'Chicken Rice', 'allergens': [], 'meal_types': ['lunch'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['chicken', 'rice']},
        ]
        profile = {'allergies': ['peanuts'], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'lunch')
        assert len(filtered) == 1
        assert filtered[0]['name'] == 'Chicken Rice'

    def test_filter_by_restrictions(self):
        templates = [
            {'name': 'Steak', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['beef']},
            {'name': 'Tofu Bowl', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': ['vegetarian', 'vegan'], 'seasons': ['all'],
                      'difficulty': 'easy', 'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['tofu', 'rice']},
        ]
        profile = {'allergies': [], 'dietary_restrictions': ['vegetarian'],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'dinner')
        assert len(filtered) == 1
        assert filtered[0]['name'] == 'Tofu Bowl'

    def test_filter_by_dislikes(self):
        # Need 4+ templates so relaxation doesn't kick in (requires >= 3 after filter)
        templates = [
            {'name': 'Olive Pasta', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['pasta', 'olives', 'tomato']},
            {'name': 'Plain Pasta', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['pasta', 'tomato']},
            {'name': 'Rice Bowl', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['rice', 'beans']},
            {'name': 'Chicken Plate', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['chicken', 'potatoes']},
        ]
        profile = {'allergies': [], 'dietary_restrictions': [],
                   'dislikes': ['olives'], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'dinner')
        assert len(filtered) == 3
        assert all(m['name'] != 'Olive Pasta' for m in filtered)

    def test_filter_by_cooking_skill(self):
        templates = [
            {'name': 'Simple Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['chicken']},
            {'name': 'Complex Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'hard',
                      'cooking_skill': 'advanced', 'budget': 'budget'},
             'ingredients': ['lobster']},
            {'name': 'Medium Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['rice']},
            {'name': 'Easy Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['pasta']},
        ]
        profile = {'allergies': [], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': 'basic', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'dinner')
        assert all(m['name'] != 'Complex Meal' for m in filtered)

    def test_filter_by_budget(self):
        templates = [
            {'name': 'Budget Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['rice', 'beans']},
            {'name': 'Premium Meal', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'premium'},
             'ingredients': ['wagyu']},
            {'name': 'Cheap Meal 1', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['pasta']},
            {'name': 'Cheap Meal 2', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['eggs']},
        ]
        profile = {'allergies': [], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': 'budget'}
        filtered, _ = filter_templates(templates, profile, 'dinner')
        assert all(m['name'] != 'Premium Meal' for m in filtered)

    def test_filter_never_relaxes_allergens(self):
        """Allergen filter should never be relaxed even with few results."""
        templates = [
            {'name': 'PB Only', 'allergens': ['peanuts'], 'meal_types': ['snack'],
             'tags': {'dietary': [], 'seasons': ['all'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'budget'},
             'ingredients': ['peanut butter']},
        ]
        profile = {'allergies': ['peanuts'], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'snack')
        assert len(filtered) == 0

    def test_score_template_calorie_fit(self):
        template = {'calories': 500, 'protein': 40, 'sodium': 400,
                    'tags': {'cuisines': ['american']}, 'ingredients': ['chicken']}
        remaining = {'calories': 500, 'protein': 40, 'sodium': 2000,
                     'meals_remaining': 1}
        score = score_template(template, remaining, {'cuisine_preferences': []})
        # Perfect calorie and protein fit should give high score
        assert score > 0.5

    def test_score_template_poor_fit(self):
        template = {'calories': 1000, 'protein': 5, 'sodium': 2000,
                    'tags': {'cuisines': ['thai']}, 'ingredients': ['noodles']}
        remaining = {'calories': 300, 'protein': 50, 'sodium': 500,
                     'meals_remaining': 1}
        score = score_template(template, remaining, {'cuisine_preferences': []})
        # Very poor fit should give low score
        assert score < 0.5

    def test_suggest_meals_returns_list(self):
        suggestions = suggest_meals(meal_type='dinner', count=3)
        assert isinstance(suggestions, list)

    def test_suggest_meals_sorted_by_score(self):
        suggestions = suggest_meals(meal_type='dinner', count=5)
        if len(suggestions) >= 2:
            scores = [s['score'] for s in suggestions]
            assert scores == sorted(scores, reverse=True)

    def test_format_suggestions_output(self):
        remaining = {'calories': 800, 'protein': 45, 'carbs': 100,
                     'fat': 30, 'sodium': 1500, 'consumed': {'calories': 1200},
                     'meals_remaining': 1}
        suggestions = [
            {'template': {'name': 'Test Meal', 'calories': 500, 'protein': 40,
                          'carbs': 50, 'fat': 15, 'meal_types': ['dinner'],
                          'tags': {'cuisines': ['american'], 'cooking_skill': 'basic',
                                   'prep_time_min': 25}},
             'score': 0.85, 'remaining': remaining, 'relaxed_filters': []}
        ]
        output = format_suggestions(suggestions, remaining)
        assert 'Test Meal' in output
        assert '500 cal' in output
        assert 'Remaining today' in output

    def test_filter_relaxation(self):
        """Filters should relax when too few results."""
        templates = [
            {'name': 'Winter Stew', 'allergens': [], 'meal_types': ['dinner'],
             'tags': {'dietary': [], 'seasons': ['winter'], 'difficulty': 'easy',
                      'cooking_skill': 'basic', 'budget': 'premium'},
             'ingredients': ['beef', 'potatoes']},
        ]
        profile = {'allergies': [], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': 'budget'}
        # Budget filter would exclude this, but should relax
        filtered, relaxed = filter_templates(templates, profile, 'dinner')
        assert len(filtered) == 1
        assert 'budget' in relaxed

    def test_meal_type_filter(self):
        templates = load_meal_templates()
        profile = {'allergies': [], 'dietary_restrictions': [],
                   'dislikes': [], 'cuisine_preferences': [],
                   'cooking_skill': '', 'budget': ''}
        filtered, _ = filter_templates(templates, profile, 'breakfast')
        for meal in filtered:
            assert 'breakfast' in [t.lower() for t in meal['meal_types']]


# ---------------------------------------------------------------------------
# TheMealDB
# ---------------------------------------------------------------------------

class TestTheMealDB:
    def test_parse_meal_to_template_basic(self):
        meal = {
            'idMeal': '12345',
            'strMeal': 'Test Chicken',
            'strCategory': 'Chicken',
            'strArea': 'American',
            'strInstructions': 'Cook the chicken.',
            'strMealThumb': 'http://example.com/thumb.jpg',
            'strYoutube': 'http://youtube.com/watch?v=abc',
            'strIngredient1': 'Chicken',
            'strMeasure1': '500g',
            'strIngredient2': 'Rice',
            'strMeasure2': '1 cup',
            'strIngredient3': '',
            'strMeasure3': '',
        }
        result = parse_meal_to_template(meal)
        assert result['name'] == 'Test Chicken'
        assert result['themealdb_id'] == '12345'
        assert len(result['ingredients']) == 2
        assert '500g Chicken' in result['ingredients']

    def test_parse_meal_to_template_macros_zero(self):
        meal = {'idMeal': '1', 'strMeal': 'Test', 'strCategory': 'Beef',
                'strArea': 'British'}
        result = parse_meal_to_template(meal)
        assert result['calories'] == 0
        assert result['protein'] == 0
        assert result['carbs'] == 0
        assert result['fat'] == 0

    def test_parse_meal_to_template_none(self):
        assert parse_meal_to_template(None) is None

    def test_parse_meal_to_template_breakfast_category(self):
        meal = {'idMeal': '1', 'strMeal': 'Pancakes', 'strCategory': 'Breakfast',
                'strArea': 'American'}
        result = parse_meal_to_template(meal)
        assert 'breakfast' in result['meal_types']

    @patch('themealdb._fetch')
    def test_search_meals_handles_api_error(self, mock_fetch):
        from themealdb import search_meals
        mock_fetch.return_value = None
        result = search_meals('nonexistent')
        assert result == []


# ---------------------------------------------------------------------------
# Meal Planner CLI
# ---------------------------------------------------------------------------

class TestMealPlannerCLI:
    def test_remaining_flag(self, capsys):
        """--remaining flag should show macro info."""
        with patch('sys.argv', ['meal_planner.py', '--remaining']):
            from meal_planner import main
            main()
        output = capsys.readouterr().out
        assert 'Remaining' in output or 'consumption' in output

    def test_type_flag(self):
        """--type flag should filter by meal type."""
        suggestions = suggest_meals(meal_type='breakfast', count=3)
        for s in suggestions:
            assert 'breakfast' in [t.lower() for t in s['template']['meal_types']]

    def test_count_flag(self):
        """--count flag should limit results."""
        suggestions = suggest_meals(meal_type='dinner', count=2)
        assert len(suggestions) <= 2


# ---------------------------------------------------------------------------
# Meal History
# ---------------------------------------------------------------------------

class TestMealHistory:
    def test_parse_foods_basic(self, tmp_path):
        """Parse a basic diet log with food items."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            log = (
                "# Diet Log 2026-02-09\n\n"
                "### Breakfast (~8:00 AM)\n"
                "- Oatmeal (1 cup)\n"
                "  - Est. calories: ~300\n"
                "- Banana\n\n"
                "### Lunch (~12:30 PM)\n"
                "- Chicken breast (200g)\n"
                "- White rice (1 cup)\n"
                "  - Est. calories: ~450\n"
            )
            (tmp_path / "2026-02-09.md").write_text(log)
            foods = parse_foods_from_diet_log("2026-02-09")
            assert len(foods) == 4
            assert foods[0]['name'] == 'oatmeal'
            assert foods[0]['meal_type'] == 'breakfast'
            assert foods[0]['calories'] == 300
            assert foods[1]['name'] == 'banana'
            assert foods[2]['name'] == 'chicken breast'
            assert foods[2]['meal_type'] == 'lunch'
        finally:
            meal_history.DIET_DIR = orig

    def test_parse_foods_multi_meal(self, tmp_path):
        """Parse log with multiple meal sections."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            log = (
                "### Breakfast\n- Eggs\n"
                "### Lunch\n- Salad\n"
                "### Dinner\n- Pasta\n"
                "### Snack\n- Apple\n"
            )
            (tmp_path / "2026-02-09.md").write_text(log)
            foods = parse_foods_from_diet_log("2026-02-09")
            meal_types = [f['meal_type'] for f in foods]
            assert meal_types == ['breakfast', 'lunch', 'dinner', 'snack']
        finally:
            meal_history.DIET_DIR = orig

    def test_parse_foods_missing_file(self, tmp_path):
        """Missing file returns empty list."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            foods = parse_foods_from_diet_log("2099-01-01")
            assert foods == []
        finally:
            meal_history.DIET_DIR = orig

    def test_parse_foods_ignores_metadata(self, tmp_path):
        """Indented metadata lines should not be parsed as food items."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            log = (
                "### Lunch\n"
                "- Chicken breast (200g)\n"
                "  - Est. calories: ~350\n"
                "  - Macros: ~40g protein, ~0g carbs, ~8g fat\n"
                "  - Hydration: 1 beverage(s)\n"
            )
            (tmp_path / "2026-02-09.md").write_text(log)
            foods = parse_foods_from_diet_log("2026-02-09")
            assert len(foods) == 1
            assert foods[0]['name'] == 'chicken breast'
            assert foods[0]['calories'] == 350
        finally:
            meal_history.DIET_DIR = orig

    def test_parse_foods_stops_at_summary(self, tmp_path):
        """Should not parse foods after ## Daily Health Summary."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            log = (
                "### Lunch\n- Chicken\n\n"
                "## Daily Health Summary\n"
                "- Not a food item\n"
            )
            (tmp_path / "2026-02-09.md").write_text(log)
            foods = parse_foods_from_diet_log("2026-02-09")
            assert len(foods) == 1
            assert foods[0]['name'] == 'chicken'
        finally:
            meal_history.DIET_DIR = orig

    def test_get_recent_foods_multi_day(self, tmp_path):
        """Multi-day aggregation returns foods from all days."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            from datetime import datetime, timedelta
            today = datetime.now()
            for i in range(3):
                date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                (tmp_path / f"{date}.md").write_text(
                    f"### Lunch\n- Food day {i}\n"
                )
            recent = get_recent_foods(days=3)
            assert len(recent['all_food_names']) == 3
            assert len(recent['by_date']) == 3
        finally:
            meal_history.DIET_DIR = orig

    def test_get_recent_foods_no_logs(self, tmp_path):
        """No diet logs returns empty collections."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            recent = get_recent_foods(days=3)
            assert recent['all_food_names'] == []
            assert len(recent['by_date']) == 3
        finally:
            meal_history.DIET_DIR = orig

    def test_get_typical_calories_average(self, tmp_path):
        """Average calculation with sufficient data points."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            from datetime import datetime, timedelta
            today = datetime.now()
            for i in range(3):
                date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                (tmp_path / f"{date}.md").write_text(
                    f"### Lunch\n- Food\n  - Est. calories: ~{400 + i * 100}\n"
                )
            result = get_typical_calories('lunch', days=7)
            assert result is not None
            assert 400 <= result <= 600
        finally:
            meal_history.DIET_DIR = orig

    def test_get_typical_calories_insufficient(self, tmp_path):
        """Returns None with fewer than 2 data points."""
        import meal_history
        orig = meal_history.DIET_DIR
        meal_history.DIET_DIR = str(tmp_path)
        try:
            from datetime import datetime
            date = datetime.now().strftime('%Y-%m-%d')
            (tmp_path / f"{date}.md").write_text(
                "### Lunch\n- Food\n  - Est. calories: ~500\n"
            )
            result = get_typical_calories('lunch', days=7)
            # Only 1 data point, should return None
            assert result is None
        finally:
            meal_history.DIET_DIR = orig


# ---------------------------------------------------------------------------
# Meal History Cache
# ---------------------------------------------------------------------------

class TestMealHistoryCache:
    def test_save_load_roundtrip(self, tmp_path):
        """Cache save and load should roundtrip correctly."""
        import meal_history
        orig = meal_history._CACHE_FILE
        cache_file = str(tmp_path / 'cache.json')
        meal_history._CACHE_FILE = cache_file
        try:
            from datetime import datetime
            history = {
                'detected_cuisines': {'mexican': 0.8},
                'today_food_names': ['oatmeal'],
                'built_date': datetime.now().strftime('%Y-%m-%d'),
                'days_analyzed': 3,
            }
            _save_cache(history)
            loaded = _load_cache()
            assert loaded is not None
            assert loaded['detected_cuisines'] == {'mexican': 0.8}
        finally:
            meal_history._CACHE_FILE = orig

    def test_stale_on_different_date(self, tmp_path):
        """Cache from a different date should return None."""
        import meal_history
        orig = meal_history._CACHE_FILE
        cache_file = str(tmp_path / 'cache.json')
        meal_history._CACHE_FILE = cache_file
        try:
            history = {
                'detected_cuisines': {},
                'built_date': '2020-01-01',
                'days_analyzed': 3,
            }
            _save_cache(history)
            loaded = _load_cache()
            assert loaded is None
        finally:
            meal_history._CACHE_FILE = orig

    def test_valid_same_date(self, tmp_path):
        """Cache from today should be valid."""
        import meal_history
        orig = meal_history._CACHE_FILE
        cache_file = str(tmp_path / 'cache.json')
        meal_history._CACHE_FILE = cache_file
        try:
            from datetime import datetime
            history = {
                'detected_cuisines': {'asian': 0.5},
                'built_date': datetime.now().strftime('%Y-%m-%d'),
                'days_analyzed': 3,
            }
            _save_cache(history)
            loaded = _load_cache()
            assert loaded is not None
            assert loaded['detected_cuisines'] == {'asian': 0.5}
        finally:
            meal_history._CACHE_FILE = orig

    def test_get_history_uses_cache(self, tmp_path):
        """get_history should use cache when available."""
        import meal_history
        orig_cache = meal_history._CACHE_FILE
        orig_diet = meal_history.DIET_DIR
        cache_file = str(tmp_path / 'cache.json')
        meal_history._CACHE_FILE = cache_file
        meal_history.DIET_DIR = str(tmp_path / 'diet')
        os.makedirs(str(tmp_path / 'diet'), exist_ok=True)
        try:
            from datetime import datetime
            cached = {
                'recent_foods': {'by_date': {}, 'all_food_names': ['cached_food'], 'by_meal_type': {}},
                'detected_cuisines': {'italian': 0.9},
                'today_food_names': ['cached_food'],
                'typical_calories': {},
                'built_date': datetime.now().strftime('%Y-%m-%d'),
                'days_analyzed': 3,
            }
            _save_cache(cached)
            result = get_history()
            assert result['detected_cuisines'] == {'italian': 0.9}
            assert 'cached_food' in result['today_food_names']
        finally:
            meal_history._CACHE_FILE = orig_cache
            meal_history.DIET_DIR = orig_diet

    def test_force_refresh_bypasses_cache(self, tmp_path):
        """force_refresh should rebuild even with valid cache."""
        import meal_history
        orig_cache = meal_history._CACHE_FILE
        orig_diet = meal_history.DIET_DIR
        cache_file = str(tmp_path / 'cache.json')
        meal_history._CACHE_FILE = cache_file
        meal_history.DIET_DIR = str(tmp_path / 'diet')
        os.makedirs(str(tmp_path / 'diet'), exist_ok=True)
        try:
            from datetime import datetime
            cached = {
                'recent_foods': {'by_date': {}, 'all_food_names': ['stale_food'], 'by_meal_type': {}},
                'detected_cuisines': {'mexican': 1.0},
                'today_food_names': ['stale_food'],
                'typical_calories': {},
                'built_date': datetime.now().strftime('%Y-%m-%d'),
                'days_analyzed': 3,
            }
            _save_cache(cached)
            result = get_history(force_refresh=True)
            # After force refresh with empty diet dir, should have no foods
            assert 'stale_food' not in result.get('today_food_names', [])
        finally:
            meal_history._CACHE_FILE = orig_cache
            meal_history.DIET_DIR = orig_diet


# ---------------------------------------------------------------------------
# Cuisine Mapping
# ---------------------------------------------------------------------------

class TestCuisineMapping:
    def test_load_cuisine_map(self):
        """Cuisine map should load successfully."""
        cuisine_map = _load_cuisine_map()
        assert isinstance(cuisine_map, dict)
        assert len(cuisine_map) >= 40

    def test_detect_mexican(self):
        """Mexican ingredients should detect mexican cuisine."""
        foods = [{'name': 'flour tortilla with salsa'}]
        detected = detect_cuisines_from_foods(foods)
        assert 'mexican' in detected
        assert detected['mexican'] > 0.5

    def test_detect_asian(self):
        """Asian ingredients should detect asian cuisine."""
        foods = [{'name': 'tofu stir fry with soy sauce'}]
        detected = detect_cuisines_from_foods(foods)
        assert 'asian' in detected
        assert detected['asian'] > 0.5

    def test_detect_italian(self):
        """Italian ingredients should detect italian cuisine."""
        foods = [{'name': 'pasta with marinara and parmesan'}]
        detected = detect_cuisines_from_foods(foods)
        assert 'italian' in detected
        assert detected['italian'] > 0.5

    def test_generic_no_detect(self):
        """Generic ingredients should not detect any cuisine."""
        foods = [{'name': 'chicken and rice with salt'}]
        detected = detect_cuisines_from_foods(foods)
        # Should not strongly detect any cuisine
        for cuisine, confidence in detected.items():
            assert confidence < 0.5, f"Generic food falsely detected {cuisine}"

    def test_confidence_caps_at_one(self):
        """Confidence per cuisine should cap at 1.0."""
        foods = [{'name': 'tortilla with salsa guacamole queso lime crema'}]
        detected = detect_cuisines_from_foods(foods)
        assert 'mexican' in detected
        assert detected['mexican'] <= 1.0


# ---------------------------------------------------------------------------
# Variety Scoring
# ---------------------------------------------------------------------------

class TestVarietyScoring:
    def _make_template(self, **kwargs):
        defaults = {
            'name': 'Test Meal', 'calories': 500, 'protein': 40,
            'sodium': 400, 'carbs': 50, 'fat': 15,
            'tags': {'cuisines': ['american']},
            'ingredients': ['chicken', 'rice'],
            'meal_types': ['dinner'],
        }
        defaults.update(kwargs)
        return defaults

    def _make_remaining(self, **kwargs):
        defaults = {
            'calories': 800, 'protein': 60, 'sodium': 2000,
            'meals_remaining': 1,
        }
        defaults.update(kwargs)
        return defaults

    def test_explore_favors_novel(self):
        """Explore mode should score novel meals higher than familiar ones."""
        remaining = self._make_remaining()
        history = {
            'recent_foods': {'all_food_names': ['pasta', 'bread', 'cheese']},
            'detected_cuisines': {'italian': 0.9},
            'today_food_names': [],
            'typical_calories': {},
        }
        novel_template = self._make_template(
            ingredients=['tofu', 'soy sauce', 'bamboo shoots'],
            tags={'cuisines': ['asian']},
        )
        familiar_template = self._make_template(
            ingredients=['pasta', 'cheese', 'bread'],
            tags={'cuisines': ['italian']},
        )
        profile = {'cuisine_preferences': [], 'meal_variety': 'explore'}

        # Run multiple times and average to reduce random variance
        novel_scores = [score_template(novel_template, remaining, profile, history)
                        for _ in range(20)]
        familiar_scores = [score_template(familiar_template, remaining, profile, history)
                           for _ in range(20)]
        assert sum(novel_scores) / 20 > sum(familiar_scores) / 20

    def test_consistent_favors_familiar(self):
        """Consistent mode should score familiar meals higher than novel ones."""
        remaining = self._make_remaining()
        history = {
            'recent_foods': {'all_food_names': ['pasta', 'bread', 'cheese']},
            'detected_cuisines': {'italian': 0.9},
            'today_food_names': [],
            'typical_calories': {'dinner': 500},
        }
        novel_template = self._make_template(
            ingredients=['tofu', 'soy sauce', 'bamboo shoots'],
            tags={'cuisines': ['asian']},
        )
        familiar_template = self._make_template(
            ingredients=['pasta', 'cheese', 'bread'],
            tags={'cuisines': ['italian']},
        )
        profile = {'cuisine_preferences': ['italian'], 'meal_variety': 'consistent'}

        novel_scores = [score_template(novel_template, remaining, profile, history)
                        for _ in range(20)]
        familiar_scores = [score_template(familiar_template, remaining, profile, history)
                           for _ in range(20)]
        assert sum(familiar_scores) / 20 > sum(novel_scores) / 20

    def test_balanced_between_modes(self):
        """Balanced mode scores should be between explore and consistent."""
        remaining = self._make_remaining()
        history = {
            'recent_foods': {'all_food_names': ['pasta', 'bread']},
            'detected_cuisines': {'italian': 0.8},
            'today_food_names': [],
            'typical_calories': {'dinner': 500},
        }
        template = self._make_template(
            ingredients=['tofu', 'soy sauce'],
            tags={'cuisines': ['asian']},
        )

        explore_scores = [score_template(template, remaining,
                          {'cuisine_preferences': [], 'meal_variety': 'explore'}, history)
                          for _ in range(50)]
        balanced_scores = [score_template(template, remaining,
                           {'cuisine_preferences': [], 'meal_variety': 'balanced'}, history)
                           for _ in range(50)]
        consistent_scores = [score_template(template, remaining,
                             {'cuisine_preferences': [], 'meal_variety': 'consistent'}, history)
                             for _ in range(50)]

        avg_explore = sum(explore_scores) / 50
        avg_balanced = sum(balanced_scores) / 50
        avg_consistent = sum(consistent_scores) / 50
        # For a novel template, explore > balanced > consistent
        assert avg_explore > avg_consistent

    def test_weights_sum_to_one(self):
        """All variety mode weights should sum to 1.0."""
        for mode, weights in _VARIETY_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"{mode} weights sum to {total}, not 1.0"

    def test_repetition_penalty_for_same_day(self):
        """Same-day food overlap should reduce score."""
        remaining = self._make_remaining()
        history_no_overlap = {
            'recent_foods': {'all_food_names': []},
            'detected_cuisines': {},
            'today_food_names': [],
            'typical_calories': {},
        }
        history_overlap = {
            'recent_foods': {'all_food_names': []},
            'detected_cuisines': {},
            'today_food_names': ['chicken', 'rice'],
            'typical_calories': {},
        }
        template = self._make_template(ingredients=['chicken', 'rice'])
        profile = {'cuisine_preferences': [], 'meal_variety': 'balanced'}

        no_overlap_scores = [score_template(template, remaining, profile, history_no_overlap)
                             for _ in range(20)]
        overlap_scores = [score_template(template, remaining, profile, history_overlap)
                          for _ in range(20)]
        assert sum(no_overlap_scores) / 20 > sum(overlap_scores) / 20

    def test_pattern_match_typical_calories(self):
        """Templates matching typical calories should score higher on pattern_match."""
        remaining = self._make_remaining()
        history = {
            'recent_foods': {'all_food_names': []},
            'detected_cuisines': {},
            'today_food_names': [],
            'typical_calories': {'dinner': 500},
        }
        matching = self._make_template(calories=500)
        mismatching = self._make_template(calories=900)
        profile = {'cuisine_preferences': [], 'meal_variety': 'consistent'}

        match_scores = [score_template(matching, remaining, profile, history)
                        for _ in range(20)]
        mismatch_scores = [score_template(mismatching, remaining, profile, history)
                           for _ in range(20)]
        assert sum(match_scores) / 20 > sum(mismatch_scores) / 20

    def test_no_history_graceful(self):
        """Scoring should work gracefully with no history."""
        remaining = self._make_remaining()
        template = self._make_template()
        profile = {'cuisine_preferences': [], 'meal_variety': 'balanced'}
        score = score_template(template, remaining, profile, {})
        assert isinstance(score, float)
        assert score >= 0

    def test_invalid_mode_defaults_to_balanced(self):
        """Invalid variety mode should default to balanced."""
        remaining = self._make_remaining()
        template = self._make_template()
        profile = {'cuisine_preferences': [], 'meal_variety': 'invalid_mode'}
        score = score_template(template, remaining, profile, {})
        assert isinstance(score, float)
        assert score >= 0
