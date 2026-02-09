#!/usr/bin/env python3
"""
Log natural language workouts to fitness file.
Simplified pattern matching that actually works.
Supports exercise normalization, saved workout templates, and PR tracking.
"""

import sys
import os
import re
import json
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import FITNESS_DIR
from scripts.exercise_db import normalize_exercise_name


def get_date():
    return datetime.now().strftime('%Y-%m-%d')


def _load_saved_workouts():
    """Load saved workout shortcuts from saved_workouts.json."""
    path = os.path.join(SKILL_DIR, 'saved_workouts.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_workout_template(name, description):
    """Save a workout template to saved_workouts.json."""
    path = os.path.join(SKILL_DIR, 'saved_workouts.json')
    workouts = _load_saved_workouts()
    workouts[name.lower()] = description
    with open(path, 'w') as f:
        json.dump(workouts, f, indent=2)
    return path


def _expand_template(text):
    """Expand saved workout template if text matches a template name."""
    saved = _load_saved_workouts()
    text_lower = text.strip().lower()
    for name, expansion in saved.items():
        if name in text_lower:
            return expansion
    return text


def _parse_single_segment(segment):
    """
    Parse a single exercise segment (e.g., '3 sets of bench press @ 225 lbs').
    Returns a list of exercise dicts found in this segment.
    """
    segment = segment.strip()
    if not segment:
        return []
    segment_lower = segment.lower()
    exercises = []

    # Pattern A: "X sets of [N] exercise [@ W lbs]"
    match = re.search(
        r'(\d+)\s+sets?\s*(?:of|x)\s+(?:(\d+)\s+)?(.+?)(?:\s*(?:@|at|with)\s*(\d+\.?\d*)\s*(?:lbs?|pounds?|kg))?$',
        segment, re.IGNORECASE
    )
    if match:
        sets = int(match.group(1))
        reps = int(match.group(2)) if match.group(2) else 0
        raw_name = match.group(3).strip()
        weight = float(match.group(4)) if match.group(4) else 0
        exercise_name = normalize_exercise_name(raw_name)
        ex = {'name': exercise_name, 'sets': sets, 'reps': reps}
        if weight:
            ex['weight'] = f"{weight} lbs"
            ex['weight_val'] = weight
            ex['volume'] = int(sets * reps * weight)
        exercises.append(ex)
        return exercises

    # Pattern B: "I did X exercise"
    match = re.search(r'(?:did|do)\s+(\d+)\s+(.+?)$', segment, re.IGNORECASE)
    if match:
        count = int(match.group(1))
        raw_name = match.group(2).strip()
        exercise_name = normalize_exercise_name(raw_name)
        exercises.append({'name': exercise_name, 'count': count})
        return exercises

    # Pattern C: "completed/finished exercise at/with/@ W lbs"
    match = re.search(
        r'(?:completed|finished)\s+(.+?)\s*(?:at|with|@)\s*(\d+\.?\d*)\s*(?:lbs?|pounds?)',
        segment, re.IGNORECASE
    )
    if match:
        raw_name = match.group(1).strip()
        weight_val = float(match.group(2))
        exercise_name = normalize_exercise_name(raw_name)
        exercises.append({
            'name': exercise_name,
            'weight': f"{weight_val} lbs",
            'weight_val': weight_val,
            'volume': 0,
        })
        return exercises

    # Pattern D: bare exercise name (from template expansion)
    raw_name = segment.strip()
    if raw_name and len(raw_name) > 1:
        exercise_name = normalize_exercise_name(raw_name)
        # Only add if normalization found a known exercise (not just title-cased)
        exercises.append({
            'name': exercise_name,
            'sets': None,
            'reps': None,
            'weight': None,
        })

    return exercises


def parse_workout_text(text):
    """
    Parse natural language workout description.
    Supports comma/and-separated multi-exercise input and saved templates.
    """
    # Expand templates first
    text = _expand_template(text)
    text_lower = text.lower()

    result = {
        'workout_type': None,
        'exercises': [],
        'intensity': None,
        'duration': None,
        'notes': []
    }

    # Detect workout type
    if 'gym' in text_lower:
        result['workout_type'] = 'Gym'
    elif 'run' in text_lower or 'jog' in text_lower or 'bike' in text_lower or 'cycle' in text_lower or 'swim' in text_lower or 'pool' in text_lower or 'walk' in text_lower:
        result['workout_type'] = 'Cardio'
        if 'cycle' in text_lower or 'bike' in text_lower:
            result['workout_type'] = 'Cardio - Cycling'
        elif 'swim' in text_lower or 'pool' in text_lower:
            result['workout_type'] = 'Cardio - Swimming'
        elif 'walk' in text_lower:
            result['workout_type'] = 'Cardio - Walking'
        else:
            result['workout_type'] = 'Cardio - Running'
    elif 'stretch' in text_lower or 'yoga' in text_lower:
        result['workout_type'] = 'Flexibility/Mobility'
    elif 'mobility' in text_lower:
        result['workout_type'] = 'Flexibility/Mobility'
    elif 'hiit' in text_lower:
        result['workout_type'] = 'HIIT'
    elif 'cardio' in text_lower:
        result['workout_type'] = 'Cardio'
    else:
        result['workout_type'] = 'Resistance Training'

    # Handle cardio with distance/duration first (special case)
    if any(kw in text_lower for kw in ['run', 'jog', 'bike', 'cycle', 'swim', 'pool', 'walk']):
        distance_match = re.search(r'(\d+\.?\d*)\s*(km|kilo|miles?|mi)\b', text, re.IGNORECASE)
        distance = f"{distance_match.group(1)} {distance_match.group(2)}" if distance_match else None

        duration_match = re.search(r'(\d+)\s*(min|minutes?|hour|hours?|h|m)\b', text, re.IGNORECASE)
        duration = None
        if duration_match:
            duration_val = int(duration_match.group(1))
            unit_str = duration_match.group(2).lower()
            if unit_str in ('hour', 'hours', 'h'):
                duration = f"{duration_val * 60} min"
            else:
                duration = f"{duration_val} min"

        if distance or duration:
            if 'run' in text_lower or 'jog' in text_lower:
                cardiotype = 'Running'
            elif 'cycle' in text_lower or 'bike' in text_lower:
                cardiotype = 'Cycling'
            elif 'swim' in text_lower or 'pool' in text_lower:
                cardiotype = 'Swimming'
            elif 'walk' in text_lower:
                cardiotype = 'Walking'
            else:
                cardiotype = 'Cardio'
            result['exercises'].append({
                'name': cardiotype,
                'type': 'Cardio',
                'distance': distance,
                'duration': duration
            })
            result['notes'].append(result['workout_type'])

    # Split on comma and "and" for multi-exercise parsing
    if not result['exercises']:
        segments = re.split(r'\s*,\s*|\s+and\s+', text)
        for segment in segments:
            parsed = _parse_single_segment(segment)
            result['exercises'].extend(parsed)

    # Fallback: bodyweight exercise detection
    if not result['exercises']:
        bodyweight_exercises = ['situps', 'pushups', 'pullups', 'burpees', 'squats', 'lunges', 'dips', 'planks', 'crunches']
        found = [ex for ex in bodyweight_exercises if ex in text_lower]
        if found:
            for ex in found:
                result['exercises'].append({
                    'name': normalize_exercise_name(ex),
                    'sets': None,
                    'reps': None,
                    'weight': None
                })
            result['workout_type'] = 'Resistance Training'

    # Build notes from exercises
    for ex in result['exercises']:
        if ex.get('sets') and ex.get('weight'):
            result['notes'].append(f"{ex['sets']} sets of {ex['name']} @ {ex['weight']}")
        elif ex.get('sets'):
            result['notes'].append(f"{ex['sets']} sets of {ex['name']}")
        elif ex.get('count'):
            result['notes'].append(f"{ex['count']} {ex['name']}")

    # Detect intensity
    intensity_keywords = {
        'light': ['easy', 'light', 'warmup', 'recovery'],
        'moderate': ['medium', 'moderate', 'normal', 'maintain'],
        'hard': ['hard', 'intense', 'heavy'],
        'max': ['max', 'failure', 'all-out', '100%']
    }

    for intensity, keywords in intensity_keywords.items():
        if any(kw in text_lower for kw in keywords):
            result['intensity'] = intensity.title()
            result['notes'].append(f"Intensity: {intensity}")
            break

    return result


def log_workout_to_file(workout, date):
    """Append workout to fitness log file and record PRs."""
    log_file = os.path.join(FITNESS_DIR, f'{date}.md')

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    try:
        timestamp = datetime.now().strftime('%I:%M %p')

        lines = [f"\n## Workout - {timestamp}"]

        if workout['workout_type']:
            lines.append(f"Type: {workout['workout_type']}")

        if workout['intensity']:
            lines.append(f"Intensity: {workout['intensity']}")

        total_volume = 0

        if workout['exercises']:
            lines.append("\n### Exercises")
            for i, exercise in enumerate(workout['exercises'], 1):
                lines.append(f"{i}. {exercise['name']}")
                if exercise.get('count'):
                    lines.append(f"   Count: {exercise['count']}")
                if exercise.get('sets'):
                    lines.append(f"   Sets: {exercise['sets']}")
                if exercise.get('reps'):
                    lines.append(f"   Reps: {exercise['reps']}")
                if exercise.get('weight'):
                    lines.append(f"   Weight: {exercise['weight']}")
                if exercise.get('distance'):
                    lines.append(f"   Distance: {exercise['distance']}")
                if exercise.get('duration'):
                    lines.append(f"   Duration: {exercise['duration']}")

                if exercise.get('volume'):
                    total_volume += exercise['volume']

        if total_volume > 0:
            lines.append(f"\n**Total Volume**: {total_volume:,.0f} lbs")

        if workout['notes']:
            lines.append("\n**Notes**")
            for note in workout['notes']:
                lines.append(f"- {note}")

        new_content = '\n'.join(lines)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(new_content)

        print(f"Workout logged to {log_file}")

        # Record PRs for exercises with weight data
        try:
            from scripts.progressive_overload import record_exercise
            for exercise in workout['exercises']:
                weight = exercise.get('weight_val', 0)
                sets = exercise.get('sets') or 1
                reps = exercise.get('reps') or exercise.get('count') or 0
                if weight > 0 or reps > 0:
                    pr_result = record_exercise(
                        exercise['name'], date, sets, reps, weight
                    )
                    if pr_result['is_weight_pr']:
                        print(f"  NEW WEIGHT PR: {exercise['name']} @ {weight} lbs!")
                    if pr_result['is_volume_pr'] and not pr_result['is_weight_pr']:
                        print(f"  NEW VOLUME PR: {exercise['name']}!")
        except Exception as e:
            pass  # PR tracking is non-critical

    except Exception as e:
        print(f"Error logging workout: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: log_workout.py [--save 'name'] 'workout description'")
        print("Examples:")
        print("  log_workout.py 'I did 34 situps'")
        print("  log_workout.py '3 sets of 10 bench press @ 225 lbs'")
        print("  log_workout.py '5k run, 25 min'")
        print("  log_workout.py 'push day'")
        print("  log_workout.py --save 'upper body' '3 sets bench press, 3 sets shoulder press'")
        sys.exit(1)

    args = sys.argv[1:]

    # Handle --save flag
    save_name = None
    if '--save' in args:
        save_idx = args.index('--save')
        if save_idx + 1 < len(args):
            save_name = args[save_idx + 1]
            args = args[:save_idx] + args[save_idx + 2:]
        else:
            args.remove('--save')

    text = ' '.join(args)

    if save_name:
        path = _save_workout_template(save_name, text)
        print(f"Saved workout template '{save_name}' -> '{text}'")
        print(f"Written to {path}")
        return

    print(f"Logging workout: {text}")
    workout = parse_workout_text(text)

    date = get_date()
    log_workout_to_file(workout, date)

    print(f"\nWorkout Type: {workout['workout_type']}")
    print(f"Intensity: {workout['intensity']}")
    print(f"Exercises logged: {len(workout['exercises'])}")

if __name__ == '__main__':
    main()
