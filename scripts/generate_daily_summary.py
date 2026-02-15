#!/usr/bin/env python3
"""
Generate daily health summary combining Fitbit, diet, and workout data.
Creates comprehensive report with diet overview, fitness stats, workout overview, and coach's notes.
"""

import sys
import os
import json
import re
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import FITNESS_DIR, DIET_DIR, GOALS, calculate_calorie_target
from scripts.exercise_db import normalize_exercise_name

# Approximate calories burned per minute of moderate cardio
# Based on average for 70kg adult at moderate intensity
CARDIO_KCAL_PER_MIN = 7

def get_date():
    """Get today's date in YYYY-MM-DD format."""
    return datetime.now().strftime('%Y-%m-%d')

def load_fitbit_data(date):
    """
    Load Fitbit data from JSON file.
    Returns dict with fitness metrics.
    """
    fitbit_file = os.path.join(FITNESS_DIR, 'fitbit', f'{date}.json')

    if not os.path.exists(fitbit_file):
        return None

    try:
        with open(fitbit_file, 'r') as f:
            data = json.load(f)

        # Extract relevant metrics
        result = {
            'steps': 0,
            'calories_burned': 0,
            'resting_hr': None,
            'sleep_hours': 0,
            'weight': None,
            'distance': 0,
            'floors': 0,
            'elevation': 0,
            'minutes_sedentary': 0,
            'minutes_lightly_active': 0,
            'minutes_fairly_active': 0,
            'minutes_very_active': 0,
            'hrv_rmssd': None,
            'body_fat': None,
            'bmi': None,
            'sleep_efficiency': None,
            'hr_zones': None,
            'sleep_stages': None,
            'fitbit_activities': [],
        }

        # Steps - may be stringified JSON
        if 'steps' in data:
            steps_data = data['steps']
            if isinstance(steps_data, str):
                steps_data = json.loads(steps_data)
            if 'activities-steps' in steps_data:
                steps_list = steps_data['activities-steps']
                if steps_list and 'value' in steps_list[0]:
                    result['steps'] = int(float(steps_list[0]['value']))

        # Calories burned - may be stringified JSON
        if 'calories' in data:
            calories_data = data['calories']
            if isinstance(calories_data, str):
                calories_data = json.loads(calories_data)
            if 'activities-calories' in calories_data:
                calories_list = calories_data['activities-calories']
                if calories_list and 'value' in calories_list[0]:
                    result['calories_burned'] = int(float(calories_list[0]['value']))

        # Heart rate - may be stringified JSON
        if 'heart' in data:
            heart_data = data['heart']
            if isinstance(heart_data, str):
                heart_data = json.loads(heart_data)
            if 'activities-heart' in heart_data:
                hr_list = heart_data['activities-heart']
                if hr_list and 'value' in hr_list[0]:
                    if 'restingHeartRate' in hr_list[0]['value']:
                        result['resting_hr'] = hr_list[0]['value']['restingHeartRate']
                    # Heart rate zones (Fat Burn, Cardio, Peak minutes)
                    zones = hr_list[0]['value'].get('heartRateZones', [])
                    if zones:
                        result['hr_zones'] = {}
                        for zone in zones:
                            name = zone.get('name', '')
                            if name:
                                result['hr_zones'][name] = zone.get('minutes', 0)

        # Sleep - may be stringified JSON
        if 'sleep' in data:
            sleep_data = data['sleep']
            if isinstance(sleep_data, str):
                sleep_data = json.loads(sleep_data)
            # Use summary.totalMinutesAsleep for accurate total across all sessions
            summary = sleep_data.get('summary', {})
            total_minutes = summary.get('totalMinutesAsleep', 0)
            if total_minutes:
                result['sleep_hours'] = round(total_minutes / 60, 1)
            # Sleep stages breakdown from first (main) sleep session
            sleep_list = sleep_data.get('sleep', [])
            if sleep_list:
                stages_summary = sleep_list[0].get('levels', {}).get('summary', {})
                if stages_summary:
                    result['sleep_stages'] = {
                        'deep': stages_summary.get('deep', {}).get('minutes', 0),
                        'light': stages_summary.get('light', {}).get('minutes', 0),
                        'rem': stages_summary.get('rem', {}).get('minutes', 0),
                        'wake': stages_summary.get('wake', {}).get('minutes', 0),
                    }

        # Weight - may be stringified JSON
        if 'weight' in data:
            weight_data = data['weight']
            if isinstance(weight_data, str):
                weight_data = json.loads(weight_data)
            if 'weight' in weight_data:
                weight_list = weight_data['weight']
                if weight_list and 'weight' in weight_list[0]:
                    result['weight'] = float(weight_list[0]['weight'])

        # Distance - may be stringified JSON
        if 'distance' in data:
            distance_data = data['distance']
            if isinstance(distance_data, str):
                distance_data = json.loads(distance_data)
            if 'activities-distance' in distance_data:
                distance_list = distance_data['activities-distance']
                if distance_list and 'value' in distance_list[0]:
                    result['distance'] = float(distance_list[0]['value'])

        # Floors - may be stringified JSON
        if 'floors' in data:
            floors_data = data['floors']
            if isinstance(floors_data, str):
                floors_data = json.loads(floors_data)
            if 'activities-floors' in floors_data:
                floors_list = floors_data['activities-floors']
                if floors_list and 'value' in floors_list[0]:
                    result['floors'] = int(float(floors_list[0]['value']))

        # Elevation - may be stringified JSON
        if 'elevation' in data:
            elevation_data = data['elevation']
            if isinstance(elevation_data, str):
                elevation_data = json.loads(elevation_data)
            if 'activities-elevation' in elevation_data:
                elevation_list = elevation_data['activities-elevation']
                if elevation_list and 'value' in elevation_list[0]:
                    result['elevation'] = float(elevation_list[0]['value'])

        # Active minutes - may be stringified JSON
        for data_key, json_key in [
            ('minutes_sedentary', 'activities-minutesSedentary'),
            ('minutes_lightly_active', 'activities-minutesLightlyActive'),
            ('minutes_fairly_active', 'activities-minutesFairlyActive'),
            ('minutes_very_active', 'activities-minutesVeryActive'),
        ]:
            if data_key in data:
                am_data = data[data_key]
                if isinstance(am_data, str):
                    am_data = json.loads(am_data)
                if json_key in am_data:
                    am_list = am_data[json_key]
                    if am_list and 'value' in am_list[0]:
                        result[data_key] = int(float(am_list[0]['value']))

        # HRV - from /all endpoint, average minute-level RMSSD readings
        if 'hrv' in data:
            hrv_data = data['hrv']
            if isinstance(hrv_data, str):
                hrv_data = json.loads(hrv_data)
            if 'hrv' in hrv_data and hrv_data['hrv']:
                minutes = hrv_data['hrv'][0].get('minutes', [])
                if minutes:
                    rmssd_values = [m['value']['rmssd'] for m in minutes
                                    if 'value' in m and 'rmssd' in m.get('value', {})
                                    and isinstance(m['value']['rmssd'], (int, float))]
                    if rmssd_values:
                        result['hrv_rmssd'] = round(sum(rmssd_values) / len(rmssd_values), 1)

        # Body fat - may be stringified JSON
        if 'body_fat' in data:
            bf_data = data['body_fat']
            if isinstance(bf_data, str):
                bf_data = json.loads(bf_data)
            if 'fat' in bf_data and bf_data['fat']:
                result['body_fat'] = float(bf_data['fat'][0]['fat'])

        # BMI - from weight response
        if 'weight' in data:
            weight_data_bmi = data['weight']
            if isinstance(weight_data_bmi, str):
                weight_data_bmi = json.loads(weight_data_bmi)
            if 'weight' in weight_data_bmi and weight_data_bmi['weight']:
                bmi = weight_data_bmi['weight'][0].get('bmi')
                if bmi:
                    result['bmi'] = float(bmi)

        # Fitbit-logged activities (runs, bike rides, etc.)
        if 'activities' in data:
            activities_data = data['activities']
            if isinstance(activities_data, str):
                activities_data = json.loads(activities_data)
            activity_list = activities_data.get('activities', [])
            if activity_list:
                for act in activity_list:
                    activity_info = {
                        'name': act.get('activityName', 'Unknown'),
                        'calories': act.get('calories', 0),
                        'duration_min': round(act.get('duration', 0) / 60000, 1),
                        'distance': act.get('distance', 0),
                        'distance_unit': act.get('distanceUnit', ''),
                    }
                    result['fitbit_activities'].append(activity_info)

        # Sleep efficiency
        if 'sleep' in data:
            sleep_data_eff = data['sleep']
            if isinstance(sleep_data_eff, str):
                sleep_data_eff = json.loads(sleep_data_eff)
            if 'sleep' in sleep_data_eff and sleep_data_eff['sleep']:
                efficiency = sleep_data_eff['sleep'][0].get('efficiency')
                if efficiency:
                    result['sleep_efficiency'] = int(efficiency)

        return result

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Error loading Fitbit data: {e}")
        return None

def parse_diet_log(date):
    """
    Parse diet log file and extract macro totals.
    Returns dict with diet metrics.
    """
    diet_file = os.path.join(DIET_DIR, f'{date}.md')

    if not os.path.exists(diet_file):
        return None

    try:
        with open(diet_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Only parse content before any "## Daily Health Summary" to avoid reading previous summaries
        summary_start = content.find('## Daily Health Summary')
        if summary_start != -1:
            content = content[:summary_start]

        result = {
            'calories_consumed': 0,
            'protein': 0,
            'carbs': 0,
            'fat': 0,
            'sodium': 0,
            'fiber': 0,
            'meals': [],
            'hydration': 0,
        }

        # Extract macro totals from "## Totals" section
        # Use character class to match any dash (hyphen, en-dash, em dash, etc.)
        totals_idx = content.find('## Daily Totals')
        if totals_idx != -1:
            # Extract totals section (up to 500 chars should be enough)
            totals_section = content[totals_idx:totals_idx+500]

            # Find each macro line - match ANY dash character before keyword
            # Calories: ~2,060
            calories_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Calories:\s*~?\s*([0-9.,]+)', totals_section, re.IGNORECASE)
            if calories_match:
                calories_str = calories_match.group(1).replace(',', '')
                result['calories_consumed'] = int(float(calories_str))

            # Protein: ~92g
            protein_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Protein:\s*~?\s*([0-9.,]+)g', totals_section, re.IGNORECASE)
            if protein_match:
                result['protein'] = int(float(protein_match.group(1)))

            # Carbs: ~214g
            carbs_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Carbs:\s*~?\s*([0-9.,]+)g', totals_section, re.IGNORECASE)
            if carbs_match:
                result['carbs'] = int(float(carbs_match.group(1)))

            # Fat: ~93g
            fat_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Fat:\s*~?\s*([0-9.,]+)g', totals_section, re.IGNORECASE)
            if fat_match:
                result['fat'] = int(float(fat_match.group(1)))

            # Sodium: ~4,200mg or ~1,800mg
            sodium_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Sodium:\s*~?\s*([0-9.,]+)\s*mg', totals_section, re.IGNORECASE)
            if sodium_match:
                sodium_str = sodium_match.group(1).replace(',', '').replace('~', '')
                result['sodium'] = int(float(sodium_str))

            # Fiber: ~2g or ~4g
            fiber_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Fiber:\s*~?\s*([0-9.,]+)g', totals_section, re.IGNORECASE)
            if fiber_match:
                result['fiber'] = int(float(fiber_match.group(1)))

            # Hydration: X beverages
            hydration_match = re.search(r'[-\u2000\u2010\u2011\u2012\u2013\u2014-]\s*Hydration:\s*(\d+)\s*beverage', totals_section, re.IGNORECASE)
            if hydration_match:
                result['hydration'] = int(hydration_match.group(1))

        # Extract allergen warnings (written by log_meal_to_file as "- ALLERGY WARNING: ...")
        allergen_warnings = re.findall(r'-\s*ALLERGY WARNING:\s*(.+)', content)
        if allergen_warnings:
            result['allergen_warnings'] = allergen_warnings

        # Count meals
        meal_types = re.findall(r'###\s*(Breakfast|Lunch|Dinner|Snack)', content)
        result['meals'] = meal_types

        return result

    except Exception as e:
        print(f"Error parsing diet log: {e}")
        return None

def parse_workout_log(date):
    """
    Parse workout log file and extract workout metrics.
    Returns dict with workout data.
    """
    workout_file = os.path.join(FITNESS_DIR, f'{date}.md')

    if not os.path.exists(workout_file):
        return {'workout_sessions': 0, 'resistance_volume': 0, 'cardio_minutes': 0, 'intensity': None}

    try:
        with open(workout_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Only parse content before any "## Daily Health Summary"
        summary_start = content.find('## Daily Health Summary')
        if summary_start != -1:
            content = content[:summary_start]

        result = {
            'workout_sessions': 0,
            'resistance_volume': 0,
            'cardio_minutes': 0,
            'intensity': None,
            'total_reps': 0,
            'exercises': [],
        }

        # Bug 5 fix: Find workout sections with full body content (not just header)
        workout_sections = re.findall(r'(## Workout - [^\n]+(?:\n(?!## ).*)*)', content)
        result['workout_sessions'] = len(workout_sections)

        for section in workout_sections:
            # Parse individual exercises from numbered list format:
            # 1. Exercise Name
            #    Count: 60
            #    Sets: 3
            #    Reps: 10
            #    Weight: 225 lbs
            exercise_blocks = re.split(r'\n(?=\d+\.\s)', section)
            for block in exercise_blocks:
                ex_match = re.match(r'\d+\.\s+(.+)', block)
                if not ex_match:
                    continue

                exercise_name = normalize_exercise_name(ex_match.group(1).strip())
                ex_info = {'name': exercise_name}

                # Extract Count (bodyweight exercises)
                count_match = re.search(r'Count:\s*(\d+)', block)
                if count_match:
                    ex_info['count'] = int(count_match.group(1))
                    result['total_reps'] += ex_info['count']

                # Extract Sets
                sets = 1
                sets_match = re.search(r'Sets:\s*(\d+)', block)
                if sets_match:
                    sets = int(sets_match.group(1))
                    ex_info['sets'] = sets

                # Extract Reps
                reps = 0
                reps_match = re.search(r'Reps:\s*(\d+)', block)
                if reps_match:
                    reps = int(reps_match.group(1))
                    ex_info['reps'] = reps
                    result['total_reps'] += sets * reps

                # Extract Weight
                weight_match = re.search(r'Weight:\s*(\d+\.?\d*)\s*(lbs?|kg)', block)
                if weight_match:
                    weight_val = float(weight_match.group(1))
                    unit = weight_match.group(2)
                    ex_info['weight'] = weight_val
                    ex_info['weight_unit'] = unit
                    weight_lbs = weight_val * 2.205 if 'kg' in unit else weight_val
                    result['resistance_volume'] += sets * reps * weight_lbs

                result['exercises'].append(ex_info)

        # Extract cardio (look for distance, duration)
        cardio_keywords = ['run', 'ran', 'running', 'jog', 'jogged', 'jogging',
                           'bike', 'biked', 'biking', 'cycle', 'cycled', 'cycling',
                           'swim', 'swam', 'swimming', 'walk', 'walked', 'walking',
                           'cardio', 'elliptical']
        if any(re.search(r'\b' + re.escape(keyword) + r'\b', content.lower()) for keyword in cardio_keywords):
            # Only take the first duration match, skipping pace-style patterns (e.g. "5 min/km")
            duration_pattern = r'(\d+)\s*(min|minutes?|hour|hours?|h)\b'
            for match in re.finditer(duration_pattern, content):
                # Skip pace patterns like "5 min/km" or "6 min/mi"
                after = content[match.end():match.end()+10]
                if re.match(r'\s*/\s*(?:km|mi|mile)', after):
                    continue
                unit = match.group(2).lower()
                duration_val = int(match.group(1))
                if unit in ('hour', 'hours', 'h'):
                    result['cardio_minutes'] += duration_val * 60
                else:
                    result['cardio_minutes'] += duration_val
                break  # Only take the first (primary) duration

        # Detect intensity (highest-to-lowest priority so "light warmup max effort" → Max Effort)
        intensity_keywords = [
            ('Max Effort', ['max', 'failure', 'failed', 'all-out', '100%']),
            ('Hard', ['hard', 'intense', 'heavy']),
            ('Moderate', ['moderate', 'normal', 'maintain']),
            ('Light', ['light', 'easy', 'warmup', 'recovery']),
        ]

        for intensity, keywords in intensity_keywords:
            if any(keyword in content.lower() for keyword in keywords):
                result['intensity'] = intensity
                break

        return result

    except Exception as e:
        print(f"Error parsing workout log: {e}")
        return {'workout_sessions': 0, 'resistance_volume': 0, 'cardio_minutes': 0, 'intensity': None}

def assess_movement(steps):
    """Assess activity level based on steps."""
    if steps < 5000:
        return "Sedentary"
    elif steps < 8000:
        return "Light"
    elif steps < 12000:
        return "Moderate"
    elif steps < 16000:
        return "Active"
    else:
        return "Very active"

def assess_protein(protein, weight):
    """Assess protein intake based on weight and configured protein_per_kg."""
    if weight:
        target = int(weight * GOALS['protein_per_kg'])
        if target <= 0:
            return "N/A"
        percentage = int((protein / target) * 100)

        if percentage >= 125:
            return f"Excellent ({percentage}% of {target}g target)"
        elif percentage >= 100:
            return f"Good ({percentage}% of {target}g target)"
        elif percentage >= 75:
            return f"Fair ({percentage}% of {target}g target)"
        else:
            return f"Needs improvement ({percentage}% of {target}g target)"
    else:
        return "N/A"

def assess_sleep(hours):
    """Assess sleep quality based on configured sleep target."""
    target = GOALS['sleep_target_h']
    if hours >= target:
        return "Good"
    elif hours >= target - 2:
        return "Fair"
    else:
        return "Poor"

def assess_workout_intensity(intensity, workout_data):
    """Assess workout quality/intensity."""
    if not intensity:
        if workout_data['workout_sessions'] > 0:
            return "Logged"
        return None

    intensity_lower = intensity.lower()

    if intensity_lower in ['light', 'easy', 'warmup', 'recovery']:
        return "Light"
    elif intensity_lower in ['moderate', 'normal', 'maintain']:
        return "Moderate"
    elif intensity_lower in ['hard', 'intense', 'heavy']:
        return "Hard"
    elif intensity_lower in ['max', 'failure', 'failed']:
        return "Max Effort"
    else:
        return intensity

def generate_coach_notes(fitbit, diet, workout, date=None):
    """Generate coach's notes and tomorrow's focus using configured goals."""
    notes = {
        'strengths': [],
        'improvements': [],
        'tomorrow_focus': []
    }

    # Compute protein target from goals
    weight = (fitbit or {}).get('weight') or GOALS.get('weight_kg')
    protein_target = int(weight * GOALS['protein_per_kg']) if weight else 75
    sodium_limit = GOALS['sodium_limit_mg']
    step_target = GOALS['step_target']
    sleep_target = GOALS['sleep_target_h']
    step_good = int(step_target * 0.8)  # 80% of target counts as "good"

    # Diet strengths
    if diet and diet['protein'] > protein_target:
        notes['strengths'].append(f"Great job on protein! {diet['protein']}g exceeds your {protein_target}g target")
    if diet and diet['fiber'] >= 30:
        notes['strengths'].append(f"Excellent fiber intake ({diet['fiber']}g) - keep it up!")
    if diet and diet.get('sodium', 0) > 0 and diet['sodium'] <= sodium_limit * 0.7:
        notes['strengths'].append(f"Great sodium control ({diet['sodium']}mg - well under {sodium_limit:,}mg limit)")
    if diet and diet.get('hydration', 0) >= 6:
        notes['strengths'].append(f"Good hydration ({diet['hydration']} beverages)")

    # Workout strengths
    if workout and workout['workout_sessions'] > 0:
        notes['strengths'].append(f"Completed {workout['workout_sessions']} workout session(s)")
        if workout['intensity'] in ['Hard', 'Max Effort']:
            notes['strengths'].append(f"High intensity training ({workout['intensity']})")
        if workout['intensity'] in ['Light', 'Moderate']:
            notes['strengths'].append(f"{workout['intensity']} intensity training")
        if workout['resistance_volume'] > 5000:
            notes['strengths'].append(f"High training volume ({workout['resistance_volume']:,} lbs)")

    # Fitness strengths (from Fitbit)
    if fitbit and fitbit['steps'] >= step_target:
        notes['strengths'].append(f"Crushed your step goal! {fitbit['steps']:,} steps (target: {step_target:,})")
    elif fitbit and fitbit['steps'] >= step_good:
        notes['strengths'].append(f"Good movement ({fitbit['steps']:,} steps)")
    if fitbit and fitbit['sleep_hours'] >= sleep_target:
        notes['strengths'].append(f"Solid sleep ({fitbit['sleep_hours']}h)")
    if fitbit:
        active_total = fitbit.get('minutes_fairly_active', 0) + fitbit.get('minutes_very_active', 0)
        if active_total >= 30:
            notes['strengths'].append(f"Good active minutes ({active_total} min fairly/very active)")
        if fitbit.get('hrv_rmssd') and fitbit['hrv_rmssd'] >= 50:
            notes['strengths'].append(f"Strong HRV ({fitbit['hrv_rmssd']} ms RMSSD)")

    # Allergen warnings (highest priority)
    if diet and diet.get('allergen_warnings'):
        for warning in diet['allergen_warnings']:
            notes['improvements'].insert(0, f"ALLERGEN ALERT: {warning}")

    # Diet improvements
    if diet and diet['sodium'] > sodium_limit:
        notes['improvements'].append(f"High sodium ({diet['sodium']}mg - limit is {sodium_limit:,}mg)")
    if diet and 0 < diet.get('fiber', 0) < GOALS.get('fiber_target_g', 38):
        notes['improvements'].append(f"Low fiber ({diet['fiber']}g - aim for {GOALS.get('fiber_target_g', 38)}g+)")
    if diet and diet['carbs'] > 250:
        notes['improvements'].append(f"High carbs ({diet['carbs']}g - consider reducing)")
    if fitbit and fitbit['steps'] < int(step_target * 0.5):
        notes['improvements'].append(f"Low movement ({fitbit['steps']} steps - aim for {step_good:,}+)")
    if fitbit and fitbit['sleep_hours'] < sleep_target - 1:
        notes['improvements'].append(f"Low sleep ({fitbit['sleep_hours']}h - aim for {sleep_target}+ hours)")
    if diet and 0 < diet.get('hydration', 0) < 4:
        notes['improvements'].append(f"Low hydration ({diet['hydration']} beverages - aim for 6+)")
    if fitbit:
        active_total = fitbit.get('minutes_fairly_active', 0) + fitbit.get('minutes_very_active', 0)
        if active_total < 15 and fitbit['steps'] >= int(step_target * 0.5):
            notes['improvements'].append(f"Low active minutes ({active_total} min - aim for 30+ fairly/very active)")
        if fitbit.get('hrv_rmssd') and fitbit['hrv_rmssd'] < 25:
            notes['improvements'].append(f"Low HRV ({fitbit['hrv_rmssd']} ms) - prioritize recovery and sleep")
    if not diet:
        notes['improvements'].append("No meals logged today - please track your food")
    # Bug 7 fix: Single check for no exercise (removed duplicate block)
    if not workout or workout['workout_sessions'] == 0:
        notes['improvements'].append("No exercise logged today")

    # Tomorrow's focus
    if not notes['strengths']:
        notes['tomorrow_focus'].append("Log your meals to get better insights")

    if not workout or workout['workout_sessions'] == 0:
        notes['tomorrow_focus'].append("Get some exercise - track your workouts")

    if diet and diet['protein'] < protein_target:
        notes['tomorrow_focus'].append(f"Increase protein intake (aim for {protein_target}g+)")

    if fitbit and fitbit['steps'] < step_good:
        notes['tomorrow_focus'].append(f"Get more movement (aim for {step_good:,}+ steps)")

    if diet and diet['sodium'] > sodium_limit:
        notes['tomorrow_focus'].append(f"Watch sodium intake (limit to {sodium_limit:,}mg)")

    # PR notes — check if any PRs were set today
    if date:
        try:
            from scripts.progressive_overload import _load_pr_history
            pr_data = _load_pr_history()
            for name, ex in pr_data.get('exercises', {}).items():
                if ex.get('pr_weight_date') == date:
                    notes['strengths'].append(f"New weight PR on {name}: {ex['pr_weight']} lbs!")
                if ex.get('pr_volume_date') == date:
                    notes['strengths'].append(f"New volume PR on {name}!")
                if ex.get('pr_reps_date') == date:
                    notes['strengths'].append(f"New reps PR on {name}: {ex['pr_reps']} reps!")
        except Exception:
            pass

    # Recovery warnings — check for neglected muscle groups
    try:
        from scripts.recovery_tracking import get_recovery_warnings
        warnings = get_recovery_warnings(days_back=7)
        for w in warnings:
            if w['warning_type'] == 'neglected' and w['days_since_last'] >= 5:
                notes['improvements'].append(w['message'])
    except Exception:
        pass

    # Health-condition-aware coaching
    try:
        from config import DIETARY_PROFILE
        conditions = DIETARY_PROFILE.get('health_conditions', [])
        restrictions = DIETARY_PROFILE.get('dietary_restrictions', [])

        if diet:
            if 'diabetes' in conditions and diet['carbs'] > 200:
                notes['improvements'].append(
                    f"High carb intake ({diet['carbs']}g) -- monitor blood sugar (diabetes)")
            if 'diabetes' in conditions and diet['carbs'] < 100:
                notes['strengths'].append("Good carb control for blood sugar management")
            if 'hypertension' in conditions and diet['sodium'] > 1500:
                notes['improvements'].append(
                    f"Sodium at {diet['sodium']}mg -- hypertension guideline is <1,500mg")
            if 'high_cholesterol' in conditions and diet['fat'] > 65:
                notes['improvements'].append(
                    f"Fat intake ({diet['fat']}g) -- consider heart-healthy fats (high cholesterol)")

            # Restriction-aware protein suggestions
            if diet['protein'] < protein_target:
                if any(r in restrictions for r in ['vegetarian', 'vegan']):
                    notes['tomorrow_focus'].append(
                        f"Plant protein sources: tofu, lentils, beans, tempeh (aim for {protein_target}g)")

            # Keto compliance feedback
            if 'keto' in restrictions and diet['carbs'] <= 50:
                notes['strengths'].append(f"Excellent keto compliance ({diet['carbs']}g carbs -- under 50g target)")
            if 'keto' in restrictions and diet['carbs'] > 50:
                notes['improvements'].append(
                    f"Carbs at {diet['carbs']}g -- keto target is <50g")
    except ImportError:
        pass

    if not notes['tomorrow_focus']:
        notes['tomorrow_focus'].append("Keep up the good work!")

    return notes

def generate_summary(date):
    """Generate comprehensive daily health summary."""
    fitbit = load_fitbit_data(date)
    diet = parse_diet_log(date)
    workout = parse_workout_log(date)

    # Build summary
    lines = [f"\n## Daily Health Summary - {date}"]

    # Diet overview
    lines.append("\n### Diet Overview")
    if diet:
        lines.append(f"- **Calories consumed**: {diet['calories_consumed']:,} kcal")

        # Calculate percentages if we have protein target
        weight = (fitbit or {}).get('weight') or GOALS.get('weight_kg')
        if weight:
            protein_target = int(weight * GOALS['protein_per_kg'])
            protein_pct = int((diet['protein'] / protein_target) * 100) if protein_target > 0 else 0
            lines.append(f"- **Protein**: {diet['protein']}g ({protein_pct}% of {protein_target}g target)")
        else:
            lines.append(f"- **Protein**: {diet['protein']}g")

        lines.append(f"- **Carbs**: {diet['carbs']}g")
        lines.append(f"- **Fat**: {diet['fat']}g")
        if diet['sodium'] > 0:
            sodium_limit = GOALS['sodium_limit_mg']
            lines.append(f"- **Sodium**: {diet['sodium']:,}mg ({'⚠️' if diet['sodium'] > sodium_limit else 'OK'} - limit {sodium_limit:,}mg)")
        if diet['fiber'] > 0:
            fiber_target = GOALS['fiber_target_g']
            lines.append(f"- **Fiber**: {diet['fiber']}g (target: {fiber_target}g)")
        if diet.get('hydration', 0) > 0:
            lines.append(f"- **Hydration**: {diet['hydration']} beverages")
        lines.append(f"- **Meals**: {', '.join(dict.fromkeys(diet['meals']))}")
        if diet.get('allergen_warnings'):
            lines.append("")
            lines.append("**Allergen Warnings:**")
            for warning in diet['allergen_warnings']:
                lines.append(f"- {warning}")
    else:
        lines.append("- No meals logged today")

    # Workout overview
    lines.append("\n### Workout Overview")
    if workout and workout['workout_sessions'] > 0:
        lines.append(f"- **Workout sessions**: {workout['workout_sessions']}")
        lines.append(f"- **Intensity**: {workout['intensity']}")
        if workout['resistance_volume'] > 0:
            lines.append(f"- **Resistance volume**: {workout['resistance_volume']:,} lbs")
        if workout.get('total_reps', 0) > 0:
            lines.append(f"- **Total reps**: {workout['total_reps']:,}")
        if workout.get('exercises'):
            exercise_names = [ex['name'] for ex in workout['exercises']]
            lines.append(f"- **Exercises**: {', '.join(exercise_names)}")
        if workout['cardio_minutes'] > 0:
            lines.append(f"- **Cardio time**: {workout['cardio_minutes']} minutes")
    else:
        lines.append("- No exercise logged today")

    # Fitbit-tracked activities
    if fitbit and fitbit.get('fitbit_activities'):
        lines.append("\n**Fitbit-tracked activities:**")
        for act in fitbit['fitbit_activities']:
            parts = [act['name']]
            if act.get('duration_min'):
                parts.append(f"{act['duration_min']} min")
            if act.get('distance'):
                parts.append(f"{act['distance']} {act.get('distance_unit', '')}")
            if act.get('calories'):
                parts.append(f"{act['calories']} kcal")
            lines.append(f"- {' | '.join(parts)}")

    # Fitness overview
    lines.append("\n### Fitness Overview")
    if fitbit:
        lines.append(f"- **Steps**: {fitbit['steps']:,} ({assess_movement(fitbit['steps'])})")
        lines.append(f"- **Distance**: {fitbit['distance']} km")
        if fitbit['floors']:
            lines.append(f"- **Floors**: {fitbit['floors']}")
        lines.append(f"- **Calories burned**: {fitbit['calories_burned']:,} kcal")
        if fitbit['resting_hr']:
            lines.append(f"- **Resting heart rate**: {fitbit['resting_hr']} bpm")
        if fitbit.get('hr_zones'):
            zone_parts = []
            for zone_name in ['Fat Burn', 'Cardio', 'Peak']:
                mins = fitbit['hr_zones'].get(zone_name, 0)
                if mins > 0:
                    zone_parts.append(f"{zone_name}: {mins} min")
            if zone_parts:
                lines.append(f"- **HR zones**: {', '.join(zone_parts)}")
        if fitbit.get('hrv_rmssd'):
            lines.append(f"- **HRV (RMSSD)**: {fitbit['hrv_rmssd']} ms")
        active_total = fitbit['minutes_fairly_active'] + fitbit['minutes_very_active']
        lines.append(f"- **Active minutes**: {active_total} min ({fitbit['minutes_fairly_active']} fairly + {fitbit['minutes_very_active']} very)")
        lines.append(f"- **Sedentary**: {fitbit['minutes_sedentary']} min")
        sleep_str = f"{fitbit['sleep_hours']}h ({assess_sleep(fitbit['sleep_hours'])})"
        if fitbit.get('sleep_efficiency'):
            sleep_str += f", {fitbit['sleep_efficiency']}% efficiency"
        lines.append(f"- **Sleep**: {sleep_str}")
        if fitbit.get('sleep_stages'):
            stages = fitbit['sleep_stages']
            lines.append(f"  - Deep: {stages['deep']} min, Light: {stages['light']} min, REM: {stages['rem']} min, Wake: {stages['wake']} min")
        if fitbit['weight']:
            weight_str = f"{fitbit['weight']} kg"
            if fitbit.get('bmi'):
                weight_str += f" (BMI {fitbit['bmi']:.1f})"
            lines.append(f"- **Weight**: {weight_str}")
        if fitbit.get('body_fat'):
            lines.append(f"- **Body fat**: {fitbit['body_fat']:.1f}%")
    else:
        lines.append("- No Fitbit data available")

    # Net balance
    lines.append("\n### Net Balance")
    if fitbit and diet and workout:
        total_burned = fitbit['calories_burned']
        net_calories = diet['calories_consumed'] - total_burned
        lines.append(f"- **Calorie balance**: {net_calories:+,} kcal (consumed - burned)")
        calorie_target = calculate_calorie_target()
        if calorie_target:
            lines.append(f"- **Calorie target**: {calorie_target:,} kcal/day")
        lines.append(f"- **Protein status**: {assess_protein(diet['protein'], fitbit.get('weight') or GOALS.get('weight_kg'))}")
        lines.append(f"- **Movement**: {assess_movement(fitbit['steps'])}")
        lines.append(f"- **Workout**: {assess_workout_intensity(workout['intensity'], workout)}")
    elif diet:
        lines.append(f"- **Calories consumed**: {diet['calories_consumed']:,} kcal")

    # Coach's notes
    coach_notes = generate_coach_notes(fitbit, diet, workout, date=date)

    lines.append("\n### Coach's Notes")

    if coach_notes['strengths']:
        lines.append("\n**Strengths:**")
        for strength in coach_notes['strengths']:
            lines.append(f"- {strength}")

    if coach_notes['improvements']:
        lines.append("\n**Areas for improvement:**")
        for improvement in coach_notes['improvements']:
            lines.append(f"- {improvement}")

    lines.append("\n**Tomorrow's focus:**")
    for focus in coach_notes['tomorrow_focus']:
        lines.append(f"- {focus}")

    return '\n'.join(lines)

def append_to_log(date, summary):
    """Append summary to dedicated summaries folder."""
    summaries_dir = os.path.join(os.path.dirname(FITNESS_DIR), 'summaries')
    summary_file = os.path.join(summaries_dir, f'{date}.md')

    try:
        os.makedirs(summaries_dir, exist_ok=True)

        # Write summary (overwrites any existing summary for this date)
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary)
            f.write('\n')

        print(f"Summary saved to {summary_file}")
    except Exception as e:
        print(f"Error saving summary: {e}")

def main():
    """Generate daily health summary."""
    date = get_date()

    print(f"Generating daily health summary for {date}...")

    summary = generate_summary(date)
    print(summary)
    print()

    append_to_log(date, summary)

if __name__ == '__main__':
    main()
