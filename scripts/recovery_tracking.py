#!/usr/bin/env python3
"""
Muscle group recovery monitoring.
Tracks which muscle groups were trained on which days to detect
neglected groups and insufficient recovery periods.
"""

import os
import sys
import re
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import FITNESS_DIR
from scripts.exercise_db import normalize_exercise_name, get_muscle_groups


def get_muscle_group_history(days_back=14, fitness_dir=None):
    """
    Scan recent workout logs and map muscle groups to dates trained.
    Returns dict: {muscle_group: [date_str, ...]}
    """
    fitness_dir = fitness_dir or FITNESS_DIR
    if not os.path.isdir(fitness_dir):
        return {}

    today = datetime.now().date()
    history = {}

    for i in range(days_back):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        filepath = os.path.join(fitness_dir, f'{date}.md')
        if not os.path.exists(filepath):
            continue

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except IOError:
            continue

        # Stop at summary section
        summary_start = content.find('## Daily Health Summary')
        if summary_start != -1:
            content = content[:summary_start]

        # Extract exercise names from numbered lists
        exercise_names = re.findall(r'^\d+\.\s+(.+?)$', content, re.MULTILINE)

        for raw_name in exercise_names:
            canonical = normalize_exercise_name(raw_name.strip())
            muscles = get_muscle_groups(canonical)
            for muscle in muscles:
                if muscle == 'cardio':
                    continue  # skip cardio for recovery tracking
                if muscle not in history:
                    history[muscle] = []
                if date not in history[muscle]:
                    history[muscle].append(date)

    return history


def get_recovery_warnings(days_back=14, fitness_dir=None):
    """
    Check for muscle groups that are neglected or overtrained.
    Returns list of warning dicts:
      [{muscle_group, days_since_last, warning_type, message}]
    warning_type: 'neglected' (7+ days) or 'insufficient_recovery' (consecutive days)
    """
    history = get_muscle_group_history(days_back, fitness_dir)
    today = datetime.now().date()
    warnings = []

    # All muscle groups we track (excluding cardio)
    all_muscles = set()
    for muscle, dates in history.items():
        all_muscles.add(muscle)

    for muscle, dates in history.items():
        sorted_dates = sorted(dates, reverse=True)

        # Check for neglected (7+ days since last training)
        if sorted_dates:
            last_date = datetime.strptime(sorted_dates[0], '%Y-%m-%d').date()
            days_since = (today - last_date).days
            if days_since > 7:
                warnings.append({
                    'muscle_group': muscle,
                    'days_since_last': days_since,
                    'warning_type': 'neglected',
                    'message': f"{muscle.title()} hasn't been trained in {days_since} days",
                })

        # Check for insufficient recovery (trained on consecutive days)
        if len(sorted_dates) >= 2:
            for j in range(len(sorted_dates) - 1):
                d1 = datetime.strptime(sorted_dates[j], '%Y-%m-%d').date()
                d2 = datetime.strptime(sorted_dates[j + 1], '%Y-%m-%d').date()
                diff = (d1 - d2).days
                if diff == 0:
                    warnings.append({
                        'muscle_group': muscle,
                        'days_since_last': 0,
                        'warning_type': 'insufficient_recovery',
                        'message': f"{muscle.title()} trained twice on {sorted_dates[j]} -- allow 48h recovery between sessions",
                    })
                elif diff == 1:
                    warnings.append({
                        'muscle_group': muscle,
                        'days_since_last': 0,
                        'warning_type': 'insufficient_recovery',
                        'message': f"{muscle.title()} trained on consecutive days ({sorted_dates[j+1]} and {sorted_dates[j]}) -- allow 48h recovery",
                    })

    return warnings


def format_recovery_section(warnings):
    """Format recovery warnings as markdown for weekly summary."""
    if not warnings:
        return ''

    lines = ["\n### Recovery Notes"]

    neglected = [w for w in warnings if w['warning_type'] == 'neglected']
    insufficient = [w for w in warnings if w['warning_type'] == 'insufficient_recovery']

    if neglected:
        lines.append("\n**Neglected muscle groups:**")
        for w in neglected:
            lines.append(f"- {w['message']}")

    if insufficient:
        lines.append("\n**Insufficient recovery:**")
        for w in insufficient:
            lines.append(f"- {w['message']}")

    return '\n'.join(lines)
