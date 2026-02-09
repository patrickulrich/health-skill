#!/usr/bin/env python3
"""
Exercise database: name normalization and muscle group lookup.
Loads exercise_aliases.json and builds a flat alias->canonical mapping.
"""

import os
import json

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EXERCISES = None  # list of exercise entries
_LOOKUP = None     # alias (lowercase) -> exercise entry


def _load_exercise_db():
    """Load exercise_aliases.json and return list of exercise entries."""
    path = os.path.join(SKILL_DIR, 'exercise_aliases.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _build_lookup_table(exercises):
    """Build flat alias->exercise entry mapping from exercise list."""
    lookup = {}
    for entry in exercises:
        canonical_lower = entry['canonical'].lower()
        lookup[canonical_lower] = entry
        for alias in entry.get('aliases', []):
            lookup[alias.lower()] = entry
    return lookup


def _ensure_loaded():
    """Ensure the database is loaded (lazy init on first use)."""
    global _EXERCISES, _LOOKUP
    if _EXERCISES is None:
        _EXERCISES = _load_exercise_db()
        _LOOKUP = _build_lookup_table(_EXERCISES)


def normalize_exercise_name(raw):
    """
    Resolve a raw exercise name to its canonical form.
    Returns canonical name if found, otherwise .title() of input.
    """
    _ensure_loaded()
    key = raw.strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]['canonical']
    return raw.strip().title()


def get_muscle_groups(canonical):
    """Return list of muscle groups for a canonical exercise name."""
    _ensure_loaded()
    key = canonical.strip().lower()
    if key in _LOOKUP:
        return list(_LOOKUP[key].get('muscle_groups', []))
    return []


def get_exercise_type(canonical):
    """Return exercise type: 'compound', 'isolation', 'bodyweight', or 'cardio'."""
    _ensure_loaded()
    key = canonical.strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key].get('type', 'unknown')
    return 'unknown'


def reload_db():
    """Re-read exercise_aliases.json (useful for tests)."""
    global _EXERCISES, _LOOKUP
    _EXERCISES = _load_exercise_db()
    _LOOKUP = _build_lookup_table(_EXERCISES)
