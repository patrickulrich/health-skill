#!/usr/bin/env python3
"""
Regenerate daily health summary for a specific date.
Usage: regenerate_summary.py YYYY-MM-DD
"""

import sys
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, SCRIPT_DIR)

from generate_daily_summary import generate_summary, write_summary

def main():
    if len(sys.argv) < 2:
        print("Usage: regenerate_summary.py YYYY-MM-DD")
        sys.exit(1)
    
    date_str = sys.argv[1]
    
    # Validate date format
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        print(f"Invalid date format: {date_str}")
        print("Use format: YYYY-MM-DD")
        sys.exit(1)
    
    print(f"Regenerating health summary for {date_str}...")
    summary = generate_summary(date_str)
    print(summary)
    print()
    write_summary(date_str, summary)
    print(f"Summary saved for {date_str}")

if __name__ == '__main__':
    main()
