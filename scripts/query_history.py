#!/usr/bin/env python3
"""
Natural language workout query engine.
Answers questions about workout history, PRs, trends, and counts.
"""

import sys
import os
import re
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from scripts.exercise_db import normalize_exercise_name
from scripts.progressive_overload import (
    get_pr, get_exercise_history, get_progression_trends, _load_pr_history,
)
from scripts.generate_daily_summary import load_fitbit_data


def classify_query(text):
    """
    Classify a natural language query into a structured intent.
    Returns dict: {type, exercise, metric, timeframe}
    """
    text_lower = text.lower().strip()
    result = {
        'type': 'summary',
        'exercise': None,
        'metric': None,
        'timeframe': None,
    }

    # Extract exercise name (look for known patterns)
    # "my bench PR" -> bench, "last deadlift" -> deadlift
    # Try to find exercise name after key phrases
    exercise_patterns = [
        r'(?:my|the)\s+(.+?)\s+(?:pr|record|best|max)',
        r'(?:last|when|did i)\s+(?:do|did|last)\s+(.+?)(?:\s*\?|$)',
        r'(?:how many times)\s+(?:did i|have i)\s+(?:do|done|did)\s+(.+?)(?:\s+this|\s*\?|$)',
        r'(?:trend|progress|progression)\s+(?:for|on|of)\s+(.+?)(?:\s*\?|$)',
        r'(?:how has|how is)\s+(?:my\s+)?(.+?)\s+(?:trended|trending|going|progressing)',
    ]

    for pattern in exercise_patterns:
        match = re.search(pattern, text_lower)
        if match:
            raw = match.group(1).strip()
            result['exercise'] = normalize_exercise_name(raw)
            break

    # Classify query type
    if re.search(r'\b(?:pr|record|best|max|personal)\b', text_lower):
        result['type'] = 'pr'
    elif re.search(r'\b(?:last|when|most recent)\b', text_lower):
        result['type'] = 'last_workout'
    elif re.search(r'\b(?:how many|count|times)\b', text_lower):
        result['type'] = 'count'
    elif re.search(r'\b(?:trend|progress|trending|progressing)\b', text_lower):
        result['type'] = 'trend'
    elif re.search(r'\b(?:sleep|steps|heart rate|weight|calories burned)\b', text_lower):
        result['type'] = 'trend'
        # Extract Fitbit metric
        if 'sleep' in text_lower:
            result['metric'] = 'sleep'
        elif 'step' in text_lower:
            result['metric'] = 'steps'
        elif 'heart' in text_lower:
            result['metric'] = 'resting_hr'
        elif 'weight' in text_lower:
            result['metric'] = 'weight'

    # Extract timeframe
    if 'this week' in text_lower:
        result['timeframe'] = 'week'
    elif 'this month' in text_lower:
        result['timeframe'] = 'month'
    elif 'last week' in text_lower:
        result['timeframe'] = 'last_week'
    elif match := re.search(r'last\s+(\d+)\s+(?:days?|weeks?)', text_lower):
        result['timeframe'] = f"last_{match.group(1)}_days"

    return result


def answer_query(text):
    """Process a natural language query and return a human-readable answer."""
    query = classify_query(text)

    if query['type'] == 'pr':
        return _answer_pr(query)
    elif query['type'] == 'last_workout':
        return _answer_last_workout(query)
    elif query['type'] == 'count':
        return _answer_count(query)
    elif query['type'] == 'trend':
        if query['metric']:
            return _answer_fitbit_trend(query)
        if query['exercise']:
            return _answer_exercise_trend(query)
        return _answer_summary(query)
    else:
        return _answer_summary(query)


def _answer_pr(query):
    """Answer a PR question."""
    if not query['exercise']:
        return "Which exercise are you asking about? Try: 'What is my bench press PR?'"

    pr = get_pr(query['exercise'])
    if not pr:
        return f"No data found for {query['exercise']}. Log some workouts first!"

    parts = [f"**{query['exercise']} PRs:**"]
    if pr['pr_weight'] > 0:
        parts.append(f"- Weight PR: {pr['pr_weight']} lbs (set on {pr['pr_weight_date']})")
    if pr['pr_volume'] > 0:
        parts.append(f"- Volume PR: {pr['pr_volume']:,} lbs total (set on {pr['pr_volume_date']})")
    return '\n'.join(parts)


def _answer_last_workout(query):
    """Answer when an exercise was last done."""
    if not query['exercise']:
        return "Which exercise? Try: 'When did I last do squats?'"

    history = get_exercise_history(query['exercise'])
    if not history:
        return f"No records found for {query['exercise']}."

    last = history[-1]
    parts = [f"**Last {query['exercise']} session:** {last['date']}"]
    if last['weight'] > 0:
        parts.append(f"- {last['sets']} sets x {last['reps']} reps @ {last['weight']} lbs")
    elif last['reps'] > 0:
        parts.append(f"- {last['reps']} reps")
    parts.append(f"- Total sessions recorded: {len(history)}")
    return '\n'.join(parts)


def _answer_count(query):
    """Answer how many times an exercise was done."""
    if not query['exercise']:
        return "Which exercise? Try: 'How many times did I squat this week?'"

    history = get_exercise_history(query['exercise'])
    if not history:
        return f"No records found for {query['exercise']}."

    # Filter by timeframe
    filtered = _filter_by_timeframe(history, query['timeframe'])
    timeframe_str = _timeframe_label(query['timeframe'])

    return f"You did {query['exercise']} **{len(filtered)} time(s)** {timeframe_str}."


def _answer_exercise_trend(query):
    """Answer trend question for a specific exercise."""
    trends = get_progression_trends(weeks=4)
    if query['exercise'] in trends:
        t = trends[query['exercise']]
        return (
            f"**{query['exercise']} trend (last 4 weeks):** {t['trend']}\n"
            f"- Sessions: {t['sessions']}"
        )
    return f"Not enough data for {query['exercise']} trend. Need at least 2 sessions in the last 4 weeks."


def _answer_fitbit_trend(query):
    """Answer trend questions about Fitbit metrics."""
    metric = query['metric']
    days = _timeframe_to_days(query.get('timeframe'))
    today = datetime.now().date()

    values = []
    for i in range(days):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        fitbit = load_fitbit_data(date)
        if fitbit and metric in fitbit and fitbit[metric] is not None:
            values.append((date, fitbit[metric]))

    if not values:
        return f"No Fitbit {metric} data found for the last {days} days."

    values.reverse()  # chronological order
    metric_values = [v for _, v in values]
    avg = sum(metric_values) / len(metric_values)

    # Simple trend: compare first half vs second half
    mid = len(metric_values) // 2
    if mid > 0:
        first_avg = sum(metric_values[:mid]) / mid
        second_avg = sum(metric_values[mid:]) / len(metric_values[mid:])
        if second_avg > first_avg * 1.03:
            direction = "trending up"
        elif second_avg < first_avg * 0.97:
            direction = "trending down"
        else:
            direction = "stable"
    else:
        direction = "not enough data for trend"

    label = metric.replace('_', ' ').title()
    unit = _metric_unit(metric)

    return (
        f"**{label} (last {days} days):**\n"
        f"- Average: {avg:.1f}{unit}\n"
        f"- Trend: {direction}\n"
        f"- Data points: {len(values)}"
    )


def _answer_summary(query):
    """General summary of workout trends."""
    trends = get_progression_trends(weeks=4)
    if not trends:
        return "No workout data found. Start logging workouts to see trends!"

    parts = ["**Workout Trends (last 4 weeks):**"]
    for name, t in sorted(trends.items()):
        if t['trend'] != 'insufficient_data':
            parts.append(f"- {name}: {t['trend']} ({t['sessions']} sessions)")

    if len(parts) == 1:
        return "Not enough data for trends yet. Keep logging workouts!"

    return '\n'.join(parts)


def _filter_by_timeframe(history, timeframe):
    """Filter history entries by timeframe."""
    if not timeframe:
        return history

    today = datetime.now().date()

    if timeframe == 'week':
        monday = today - timedelta(days=today.weekday())
        cutoff = monday.strftime('%Y-%m-%d')
    elif timeframe == 'last_week':
        monday = today - timedelta(days=today.weekday()) - timedelta(weeks=1)
        sunday = monday + timedelta(days=6)
        return [e for e in history if monday.strftime('%Y-%m-%d') <= e['date'] <= sunday.strftime('%Y-%m-%d')]
    elif timeframe == 'month':
        cutoff = today.replace(day=1).strftime('%Y-%m-%d')
    elif match := re.match(r'last_(\d+)_days', timeframe):
        days = int(match.group(1))
        cutoff = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    else:
        return history

    return [e for e in history if e['date'] >= cutoff]


def _timeframe_label(timeframe):
    """Human-readable label for timeframe."""
    if timeframe == 'week':
        return 'this week'
    elif timeframe == 'last_week':
        return 'last week'
    elif timeframe == 'month':
        return 'this month'
    elif timeframe and 'days' in timeframe:
        match = re.match(r'last_(\d+)_days', timeframe)
        if match:
            return f"in the last {match.group(1)} days"
    return 'total'


def _timeframe_to_days(timeframe):
    """Convert timeframe to number of days."""
    if timeframe == 'week':
        return 7
    elif timeframe == 'last_week':
        return 14
    elif timeframe == 'month':
        return 30
    elif timeframe and 'days' in timeframe:
        match = re.match(r'last_(\d+)_days', timeframe)
        if match:
            return int(match.group(1))
    return 30  # default


def _metric_unit(metric):
    """Return unit string for a Fitbit metric."""
    units = {
        'sleep_hours': 'h',
        'steps': ' steps',
        'resting_hr': ' bpm',
        'weight': ' kg',
        'calories_burned': ' kcal',
    }
    return units.get(metric, '')


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: query_history.py 'your question'")
        print("Examples:")
        print("  query_history.py 'What is my bench PR?'")
        print("  query_history.py 'When did I last do deadlifts?'")
        print("  query_history.py 'How many times did I squat this week?'")
        print("  query_history.py 'How has my sleep trended this month?'")
        sys.exit(1)

    text = ' '.join(sys.argv[1:])
    print(answer_query(text))


if __name__ == '__main__':
    main()
