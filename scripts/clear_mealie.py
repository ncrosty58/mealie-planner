import os
import sys
# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
import pytz
from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.utils import get_active_week_range
from mealie_planner import config

def wipe_mealie_data(week='both', what='both'):
    """Wipe data for current week, next week, or both.

    `what` controls which data is wiped: 'plan' (meal plan entries only),
    'shopping' (shopping list items only), or 'both'.
    """
    client = UnifiedMealieClient()

    tz = pytz.timezone(config.TIMEZONE)
    today = datetime.now(tz)
    today_str = today.strftime("%Y-%m-%d")

    # 1. Calculate planning ranges
    current_start, current_end = get_active_week_range()

    if what in ('plan', 'both'):
        if week in ('current', 'both'):
            current_end_str = current_end.strftime("%Y-%m-%d")
            # Clear current week starting from today (or start of week if today is earlier, which shouldn't happen)
            clear_start_str = max(today_str, current_start.strftime("%Y-%m-%d"))

            print(f"Clearing meal plan for current week from: {clear_start_str} to {current_end_str}")
            existing_plans_current_week = client.get_meal_plan(clear_start_str, current_end_str)
            if existing_plans_current_week:
                for p in existing_plans_current_week:
                    print(f"Deleting meal plan entry: {p.get('title', p.get('entryType'))} on {p['date']}")
                    client.delete_meal_plan_entry(p['id'])
            print(f"Cleared {len(existing_plans_current_week) if existing_plans_current_week else 0} entries for current week.")

        if week in ('next', 'both'):
            # Clear next week's meal plan
            next_start = current_start + timedelta(days=7)
            next_end = current_end + timedelta(days=7)
            next_start_str = next_start.strftime("%Y-%m-%d")
            next_end_str = next_end.strftime("%Y-%m-%d")

            print(f"Clearing meal plan for next week: {next_start_str} to {next_end_str}")
            existing_plans_next_week = client.get_meal_plan(next_start_str, next_end_str)
            if existing_plans_next_week:
                for p in existing_plans_next_week:
                    print(f"Deleting meal plan entry: {p.get('title', p.get('entryType'))} on {p['date']}")
                    client.delete_meal_plan_entry(p['id'])
            print(f"Cleared {len(existing_plans_next_week) if existing_plans_next_week else 0} entries for next week.")

    # Clear the shopping list(s) for the cleared week(s)
    if what in ('shopping', 'both'):
        if week in ('current', 'both'):
            print(f"Clearing active shopping list (ID: {config.ACTIVE_LIST_ID})")
            client.clear_shopping_list(config.ACTIVE_LIST_ID)
            print("Active shopping list cleared.")

        if week in ('next', 'both') and config.NEXT_LIST_ID != config.ACTIVE_LIST_ID:
            print(f"Clearing next week shopping list (ID: {config.NEXT_LIST_ID})")
            client.clear_shopping_list(config.NEXT_LIST_ID)
            print("Next week shopping list cleared.")

    print("Mealie data wiped successfully.")

if __name__ == "__main__":
    week_arg = 'both'
    if len(sys.argv) > 1:
        if sys.argv[1] in ('current', 'next', 'both'):
            week_arg = sys.argv[1]
    wipe_mealie_data(week_arg)
