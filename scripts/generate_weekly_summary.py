#!/usr/bin/env python3
"""
Generate weekly health summary with averages, consistency, totals, and trends.
Aggregates daily diet, fitness, and workout data for a Mon-Sun week.
Includes exercise progression, recovery notes, and adaptive plan suggestions.
"""

import sys
import os
import re
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from config import FITNESS_DIR, DIET_DIR, GOALS, calculate_calorie_target
from scripts.generate_daily_summary import (
    load_fitbit_data, parse_diet_log, parse_workout_log
)


def get_week_dates(reference_date=None):
    """
    Get Monday-Sunday date range for the week containing reference_date.
    Returns list of date strings in YYYY-MM-DD format.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
    elif isinstance(reference_date, str):
        reference_date = datetime.strptime(reference_date, '%Y-%m-%d').date()

    # Find Monday of this week
    monday = reference_date - timedelta(days=reference_date.weekday())
    return [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]


def collect_week_data(dates):
    """
    Collect daily data for each date in the week.
    Returns dict with lists of daily data.
    """
    days = []
    for date in dates:
        day = {
            'date': date,
            'diet': parse_diet_log(date),
            'fitbit': load_fitbit_data(date),
            'workout': parse_workout_log(date),
        }
        days.append(day)
    return days


def calculate_averages(days):
    """Calculate daily averages across the week."""
    diet_days = [d for d in days if d['diet']]
    fitbit_days = [d for d in days if d['fitbit']]
    workout_days = [d for d in days if d['workout'] and d['workout']['workout_sessions'] > 0]

    avg = {}
    if diet_days:
        avg['calories'] = sum(d['diet']['calories_consumed'] for d in diet_days) / len(diet_days)
        avg['protein'] = sum(d['diet']['protein'] for d in diet_days) / len(diet_days)
        avg['carbs'] = sum(d['diet']['carbs'] for d in diet_days) / len(diet_days)
        avg['fat'] = sum(d['diet']['fat'] for d in diet_days) / len(diet_days)
        avg['hydration'] = sum(d['diet'].get('hydration', 0) for d in diet_days) / len(diet_days)

    if fitbit_days:
        avg['steps'] = sum(d['fitbit']['steps'] for d in fitbit_days) / len(fitbit_days)
        avg['sleep'] = sum(d['fitbit']['sleep_hours'] for d in fitbit_days) / len(fitbit_days)

    return avg


def calculate_consistency(days):
    """Count how many days had data logged."""
    return {
        'meals_logged': sum(1 for d in days if d['diet']),
        'workouts_logged': sum(1 for d in days if d['workout'] and d['workout']['workout_sessions'] > 0),
        'fitbit_synced': sum(1 for d in days if d['fitbit']),
        'total_days': len(days),
    }


def calculate_totals(days):
    """Sum weekly totals for volume, cardio, steps."""
    totals = {
        'resistance_volume': 0,
        'cardio_minutes': 0,
        'total_steps': 0,
        'workout_sessions': 0,
    }
    for d in days:
        if d['workout']:
            totals['resistance_volume'] += d['workout']['resistance_volume']
            totals['cardio_minutes'] += d['workout']['cardio_minutes']
            totals['workout_sessions'] += d['workout']['workout_sessions']
        if d['fitbit']:
            totals['total_steps'] += d['fitbit']['steps']
    return totals


def calculate_trends(current_avg, prev_dates):
    """Compare current week averages to previous week."""
    prev_days = collect_week_data(prev_dates)
    prev_avg = calculate_averages(prev_days)

    trends = {}
    for key in current_avg:
        if key in prev_avg and prev_avg[key] > 0:
            diff = current_avg[key] - prev_avg[key]
            pct = (diff / prev_avg[key]) * 100
            if abs(pct) < 3:
                trends[key] = 'stable'
            elif diff > 0:
                trends[key] = 'up'
            else:
                trends[key] = 'down'
        else:
            trends[key] = None
    return trends, prev_avg


def trend_arrow(direction):
    """Return text indicator for trend direction."""
    if direction == 'up':
        return '[up]'
    elif direction == 'down':
        return '[down]'
    elif direction == 'stable':
        return '[stable]'
    return ''


def generate_exercise_breakdown(dates):
    """
    Generate exercise progression section with PRs, trends, and stall warnings.
    Returns markdown string.
    """
    try:
        from scripts.progressive_overload import (
            _load_pr_history, get_progression_trends, detect_stalled_lifts,
        )
    except ImportError:
        return ''

    pr_data = _load_pr_history()
    if not pr_data.get('exercises'):
        return ''

    lines = ["\n### Exercise Progression"]

    # PRs set this week
    prs_this_week = []
    for name, ex in pr_data['exercises'].items():
        if ex.get('pr_weight_date') in dates:
            prs_this_week.append(f"- {name}: {ex['pr_weight']} lbs (weight PR)")
        if ex.get('pr_volume_date') in dates:
            prs_this_week.append(f"- {name}: {ex['pr_volume']:,} lbs total (volume PR)")
        if ex.get('pr_reps_date') in dates:
            prs_this_week.append(f"- {name}: {ex['pr_reps']} reps (reps PR)")

    if prs_this_week:
        lines.append("\n**PRs this week:**")
        lines.extend(prs_this_week)

    # 4-week trends
    trends = get_progression_trends(weeks=4)
    trend_lines = []
    for name, t in sorted(trends.items()):
        if t['trend'] in ('improving', 'stalled', 'declining'):
            trend_lines.append(f"- {name}: {t['trend']} ({t['sessions']} sessions)")

    if trend_lines:
        lines.append("\n**Exercise trends (4 weeks):**")
        lines.extend(trend_lines)

    # Stalled lift warnings
    stalled = detect_stalled_lifts(weeks=3)
    if stalled:
        lines.append("\n**Stalled lifts:**")
        for s in stalled:
            lines.append(f"- {s['exercise']}: no PR in {s['weeks_since_pr']} weeks -- {s['suggestion']}")

    if len(lines) == 1:
        return ''  # nothing to report

    return '\n'.join(lines)


def generate_weekly_coach_notes(avg, consistency, totals, trends, dates=None):
    """Generate weekly coaching analysis with adaptive suggestions."""
    notes = {
        'trends': [],
        'consistency': [],
        'next_week': [],
        'plan_adjustments': [],
    }

    calorie_target = calculate_calorie_target()
    protein_target = int(GOALS['weight_kg'] * GOALS['protein_per_kg']) if GOALS.get('weight_kg') else 75
    step_target = GOALS['step_target']

    # Trend observations
    if 'protein' in trends and trends['protein'] == 'up':
        notes['trends'].append("Protein trending up -- great improvement")
    if 'protein' in trends and trends['protein'] == 'down':
        notes['trends'].append("Protein trending down -- prioritize protein sources")
    if 'steps' in trends and trends['steps'] == 'up':
        notes['trends'].append("Steps trending up -- good movement habits forming")
    if 'sleep' in trends and trends['sleep'] == 'up':
        notes['trends'].append("Sleep improving -- keep it up")
    if 'sleep' in trends and trends['sleep'] == 'down':
        notes['trends'].append("Sleep declining -- review sleep habits")

    # Consistency
    total = consistency['total_days']
    if consistency['meals_logged'] >= 6:
        notes['consistency'].append(f"Excellent meal logging ({consistency['meals_logged']}/{total} days)")
    elif consistency['meals_logged'] <= 3:
        notes['consistency'].append(f"Missed logging meals on {total - consistency['meals_logged']} days -- consistency is key")
    if consistency['workouts_logged'] >= 3:
        notes['consistency'].append(f"Good workout frequency ({consistency['workouts_logged']}/{total} days)")
    elif consistency['workouts_logged'] <= 1:
        notes['consistency'].append("Very few workouts logged -- aim for at least 3 sessions/week")

    # Next week focus
    if 'calories' in avg and calorie_target and abs(avg['calories'] - calorie_target) > 300:
        if avg['calories'] > calorie_target:
            notes['next_week'].append(f"Bring daily calories closer to {calorie_target:,} target")
        else:
            notes['next_week'].append(f"Calorie intake below target -- ensure adequate fueling")
    if 'protein' in avg and avg['protein'] < protein_target:
        notes['next_week'].append(f"Increase protein intake (averaging {int(avg['protein'])}g, target {protein_target}g)")
    if 'steps' in avg and avg['steps'] < step_target * 0.8:
        notes['next_week'].append(f"Increase daily steps (averaging {int(avg['steps']):,}, target {step_target:,})")

    if not notes['next_week']:
        notes['next_week'].append("Keep up the good work!")

    # Adaptive plan suggestions
    if dates:
        notes['plan_adjustments'] = _generate_adaptive_suggestions(
            consistency, totals, trends, dates
        )

    return notes


def _generate_adaptive_suggestions(consistency, totals, trends, dates):
    """
    Generate adaptive training suggestions based on data patterns.
    Returns list of suggestion strings, capped at 4.
    """
    suggestions = []

    try:
        from scripts.progressive_overload import detect_stalled_lifts, get_progression_trends
        from scripts.recovery_tracking import get_recovery_warnings
    except ImportError:
        return suggestions

    # 1. Deload week: 3+ stalled lifts
    stalled = detect_stalled_lifts(weeks=3)
    if len(stalled) >= 3:
        suggestions.append(
            "Consider a deload week -- multiple lifts have stalled "
            "(see references/workout-programming.md)"
        )

    # 2. Missed workouts: ≤2 workouts on ≥5 logged days
    if consistency['workouts_logged'] <= 2 and consistency['meals_logged'] >= 5:
        suggestions.append("Schedule specific workout times -- logging meals but missing workouts")

    # 3 & 4. Recovery warnings
    warnings = get_recovery_warnings(days_back=14)
    neglected = [w for w in warnings if w['warning_type'] == 'neglected']
    insufficient = [w for w in warnings if w['warning_type'] == 'insufficient_recovery']

    if neglected:
        muscles = ', '.join(w['muscle_group'] for w in neglected[:3])
        suggestions.append(f"Add exercises targeting: {muscles}")

    if insufficient:
        suggestions.append("Allow 48h between same-muscle sessions")

    # 5. Declining trend: 2+ exercises declining
    exercise_trends = get_progression_trends(weeks=4)
    declining = [name for name, t in exercise_trends.items() if t['trend'] == 'declining']
    if len(declining) >= 2:
        suggestions.append(
            "Signs of accumulated fatigue -- check sleep/nutrition or reduce volume"
        )

    # 6. Sleep trending down
    if 'sleep' in trends and trends['sleep'] == 'down':
        suggestions.append("Sleep declining -- reduce intensity, avoid max-effort sessions")

    # Cap at 4 suggestions, prioritized by order (severity)
    return suggestions[:4]


def generate_weekly_summary(reference_date=None):
    """Generate the full weekly summary report."""
    dates = get_week_dates(reference_date)
    days = collect_week_data(dates)
    avg = calculate_averages(days)
    consistency = calculate_consistency(days)
    totals = calculate_totals(days)

    # Previous week for trends
    if isinstance(reference_date, str):
        ref = datetime.strptime(reference_date, '%Y-%m-%d').date()
    elif reference_date:
        ref = reference_date
    else:
        ref = datetime.now().date()
    prev_monday = ref - timedelta(days=ref.weekday()) - timedelta(weeks=1)
    prev_dates = [(prev_monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    trends, prev_avg = calculate_trends(avg, prev_dates)

    coach = generate_weekly_coach_notes(avg, consistency, totals, trends, dates=dates)

    # Format dates for header
    week_start = dates[0]
    week_end = dates[6]

    lines = [f"## Weekly Health Summary -- {week_start} to {week_end}"]

    # Averages
    lines.append("\n### Averages (7 days)")
    calorie_target = calculate_calorie_target()
    if 'calories' in avg:
        target_str = f" (target: {calorie_target:,})" if calorie_target else ""
        lines.append(f"- Calories: ~{int(avg['calories']):,}/day{target_str} {trend_arrow(trends.get('calories'))}")
    if 'protein' in avg:
        weight = GOALS.get('weight_kg')
        pt = int(weight * GOALS['protein_per_kg']) if weight else None
        target_str = f" (target: {pt}g)" if pt else ""
        lines.append(f"- Protein: ~{int(avg['protein'])}g/day{target_str} {trend_arrow(trends.get('protein'))}")
    if 'steps' in avg:
        lines.append(f"- Steps: ~{int(avg['steps']):,}/day (target: {GOALS['step_target']:,}) {trend_arrow(trends.get('steps'))}")
    if 'sleep' in avg:
        lines.append(f"- Sleep: ~{avg['sleep']:.1f}h/day (target: {GOALS['sleep_target_h']}h) {trend_arrow(trends.get('sleep'))}")
    if 'hydration' in avg and avg['hydration'] > 0:
        lines.append(f"- Hydration: ~{avg['hydration']:.1f} beverages/day")

    # Consistency
    total = consistency['total_days']
    lines.append("\n### Consistency")
    lines.append(f"- Meals logged: {consistency['meals_logged']}/{total} days")
    lines.append(f"- Workouts logged: {consistency['workouts_logged']}/{total} days")
    lines.append(f"- Fitbit synced: {consistency['fitbit_synced']}/{total} days")

    # Weekly totals
    lines.append("\n### Weekly Totals")
    if totals['resistance_volume'] > 0:
        lines.append(f"- Resistance volume: {totals['resistance_volume']:,} lbs")
    if totals['cardio_minutes'] > 0:
        lines.append(f"- Cardio time: {totals['cardio_minutes']} min")
    lines.append(f"- Total steps: {totals['total_steps']:,}")
    lines.append(f"- Workout sessions: {totals['workout_sessions']}")

    # Exercise progression section
    exercise_section = generate_exercise_breakdown(dates)
    if exercise_section:
        lines.append(exercise_section)

    # Recovery notes
    try:
        from scripts.recovery_tracking import get_recovery_warnings, format_recovery_section
        warnings = get_recovery_warnings(days_back=14)
        recovery_section = format_recovery_section(warnings)
        if recovery_section:
            lines.append(recovery_section)
    except ImportError:
        pass

    # Coach notes
    lines.append("\n### Weekly Coach Notes")
    if coach['trends']:
        lines.append("\n**Trends:**")
        for t in coach['trends']:
            lines.append(f"- {t}")
    if coach['consistency']:
        lines.append("\n**Consistency:**")
        for c in coach['consistency']:
            lines.append(f"- {c}")
    lines.append("\n**Next week focus:**")
    for f in coach['next_week']:
        lines.append(f"- {f}")

    # Adaptive plan adjustments
    if coach.get('plan_adjustments'):
        lines.append("\n**Plan adjustments:**")
        for adj in coach['plan_adjustments']:
            lines.append(f"- {adj}")

    return '\n'.join(lines)


def main():
    """CLI entry point."""
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    summary = generate_weekly_summary(date_arg)
    print(summary)


if __name__ == '__main__':
    main()
