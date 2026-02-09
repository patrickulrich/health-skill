#!/usr/bin/env python3
"""
Progressive overload tracking: PR history, stall detection, and trend analysis.
Stores per-exercise PR and session history in pr_history.json.
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import FITNESS_DIR

PR_HISTORY_FILE = os.path.join(SKILL_DIR, 'pr_history.json')


def _load_pr_history():
    """Load pr_history.json. Returns dict with 'exercises' key."""
    if not os.path.exists(PR_HISTORY_FILE):
        return {'exercises': {}}
    try:
        with open(PR_HISTORY_FILE) as f:
            data = json.load(f)
        if 'exercises' not in data:
            data['exercises'] = {}
        return data
    except (json.JSONDecodeError, IOError):
        return {'exercises': {}}


def _save_pr_history(data):
    """Write pr_history.json atomically."""
    tmp = PR_HISTORY_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PR_HISTORY_FILE)
    return PR_HISTORY_FILE


def record_exercise(name, date, sets, reps, weight, unit='lbs'):
    """
    Record an exercise session and check for PRs.
    Returns dict with PR info:
      {'is_weight_pr': bool, 'is_volume_pr': bool,
       'previous_best_weight': float|None, 'previous_best_volume': int|None}
    Suppresses PR announcement on first-ever entry.
    """
    data = _load_pr_history()
    exercises = data['exercises']

    volume = int(sets * reps * weight) if weight else 0
    entry = {
        'date': date,
        'sets': sets,
        'reps': reps,
        'weight': float(weight) if weight else 0,
        'volume': volume,
        'unit': unit,
    }

    result = {
        'is_weight_pr': False,
        'is_volume_pr': False,
        'previous_best_weight': None,
        'previous_best_volume': None,
    }

    if name not in exercises:
        # First entry -- record but don't announce PR
        exercises[name] = {
            'pr_weight': float(weight) if weight else 0,
            'pr_weight_date': date,
            'pr_volume': volume,
            'pr_volume_date': date,
            'history': [entry],
        }
    else:
        ex = exercises[name]
        result['previous_best_weight'] = ex.get('pr_weight', 0)
        result['previous_best_volume'] = ex.get('pr_volume', 0)

        if weight and float(weight) > ex.get('pr_weight', 0):
            result['is_weight_pr'] = True
            ex['pr_weight'] = float(weight)
            ex['pr_weight_date'] = date

        if volume > ex.get('pr_volume', 0):
            result['is_volume_pr'] = True
            ex['pr_volume'] = volume
            ex['pr_volume_date'] = date

        ex['history'].append(entry)

    _save_pr_history(data)
    return result


def get_exercise_history(name):
    """Return sorted session entries for an exercise."""
    data = _load_pr_history()
    ex = data['exercises'].get(name)
    if not ex:
        return []
    return sorted(ex['history'], key=lambda e: e['date'])


def get_pr(name):
    """Return PR info for an exercise, or None if not tracked."""
    data = _load_pr_history()
    ex = data['exercises'].get(name)
    if not ex:
        return None
    return {
        'pr_weight': ex.get('pr_weight', 0),
        'pr_weight_date': ex.get('pr_weight_date'),
        'pr_volume': ex.get('pr_volume', 0),
        'pr_volume_date': ex.get('pr_volume_date'),
    }


def detect_stalled_lifts(weeks=3):
    """
    Find exercises where no weight PR has been set in the last N weeks.
    Returns list of dicts: [{exercise, weeks_since_pr, suggestion}]
    """
    data = _load_pr_history()
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime('%Y-%m-%d')
    stalled = []

    for name, ex in data['exercises'].items():
        if ex.get('pr_weight', 0) == 0:
            continue  # skip bodyweight/cardio
        pr_date = ex.get('pr_weight_date', '')
        if pr_date and pr_date < cutoff:
            days = (datetime.now() - datetime.strptime(pr_date, '%Y-%m-%d')).days
            weeks_since = days // 7
            stalled.append({
                'exercise': name,
                'weeks_since_pr': weeks_since,
                'suggestion': f"Try adding 2.5-5 lbs or an extra rep to {name}",
            })

    return stalled


def get_progression_trends(weeks=4):
    """
    Analyze recent trends per exercise over the last N weeks.
    Returns dict: {name: {trend: 'improving'|'stalled'|'declining', sessions: int}}
    """
    data = _load_pr_history()
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime('%Y-%m-%d')
    trends = {}

    for name, ex in data['exercises'].items():
        recent = [e for e in ex['history'] if e['date'] >= cutoff]
        if len(recent) < 2:
            trends[name] = {'trend': 'insufficient_data', 'sessions': len(recent)}
            continue

        # Compare first half vs second half of recent sessions
        mid = len(recent) // 2
        first_half = recent[:mid]
        second_half = recent[mid:]

        first_avg_weight = sum(e['weight'] for e in first_half) / len(first_half)
        second_avg_weight = sum(e['weight'] for e in second_half) / len(second_half)

        if first_avg_weight == 0:
            trend = 'insufficient_data'
        elif second_avg_weight > first_avg_weight * 1.02:
            trend = 'improving'
        elif second_avg_weight < first_avg_weight * 0.98:
            trend = 'declining'
        else:
            trend = 'stalled'

        trends[name] = {'trend': trend, 'sessions': len(recent)}

    return trends


def backfill_from_logs(fitness_dir=None):
    """
    One-time scan of all historical workout logs to rebuild pr_history.json.
    Returns count of exercises processed.
    """
    fitness_dir = fitness_dir or FITNESS_DIR
    if not os.path.isdir(fitness_dir):
        return 0

    from scripts.exercise_db import normalize_exercise_name

    data = {'exercises': {}}
    count = 0

    # Find all .md files in fitness dir
    for filename in sorted(os.listdir(fitness_dir)):
        if not filename.endswith('.md'):
            continue
        date = filename.replace('.md', '')
        filepath = os.path.join(fitness_dir, filename)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except IOError:
            continue

        # Stop at summary section
        summary_start = content.find('## Daily Health Summary')
        if summary_start != -1:
            content = content[:summary_start]

        # Parse exercises with sets/reps/weight
        # Pattern: "N. ExerciseName" followed by Sets/Reps/Weight lines
        exercise_blocks = re.findall(
            r'^\d+\.\s+(.+?)$\n((?:\s+(?:Sets|Reps|Weight|Count|Distance|Duration):.*\n)*)',
            content, re.MULTILINE
        )

        for raw_name, details in exercise_blocks:
            canonical = normalize_exercise_name(raw_name.strip())
            sets = 1
            reps = 0
            weight = 0

            sets_match = re.search(r'Sets:\s*(\d+)', details)
            if sets_match:
                sets = int(sets_match.group(1))
            reps_match = re.search(r'Reps:\s*(\d+)', details)
            if reps_match:
                reps = int(reps_match.group(1))
            weight_match = re.search(r'Weight:\s*([\d.]+)', details)
            if weight_match:
                weight = float(weight_match.group(1))

            if weight == 0 and reps == 0:
                count_match = re.search(r'Count:\s*(\d+)', details)
                if count_match:
                    reps = int(count_match.group(1))

            volume = int(sets * reps * weight)
            entry = {
                'date': date,
                'sets': sets,
                'reps': reps,
                'weight': weight,
                'volume': volume,
                'unit': 'lbs',
            }

            if canonical not in data['exercises']:
                data['exercises'][canonical] = {
                    'pr_weight': weight,
                    'pr_weight_date': date,
                    'pr_volume': volume,
                    'pr_volume_date': date,
                    'history': [entry],
                }
            else:
                ex = data['exercises'][canonical]
                if weight > ex['pr_weight']:
                    ex['pr_weight'] = weight
                    ex['pr_weight_date'] = date
                if volume > ex['pr_volume']:
                    ex['pr_volume'] = volume
                    ex['pr_volume_date'] = date
                ex['history'].append(entry)

            count += 1

    _save_pr_history(data)
    return count
