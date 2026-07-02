"""CLI wrapper around mealie_planner.maintenance.wipe_mealie_data.

Usage: python -m scripts.clear_mealie [current|next|both]
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.maintenance import wipe_mealie_data  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    week_arg = 'both'
    if len(sys.argv) > 1 and sys.argv[1] in ('current', 'next', 'both'):
        week_arg = sys.argv[1]
    wipe_mealie_data(week_arg)
