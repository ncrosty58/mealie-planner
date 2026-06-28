import os
import sys
# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import concurrent.futures

from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner import config

def delete_recipe_task(client, r):
    print(f"Deleting recipe: {r['name']} ({r['id']})")
    try:
        client.delete_recipe(r['id'])
    except Exception as e:
        print(f"Error deleting recipe {r['id']}: {e}")

def delete_meal_plan_entry_task(client, p):
    print(f"Deleting meal plan entry: {p.get('title', p.get('entryType'))} on {p['date']}")
    try:
        client.delete_meal_plan_entry(p['id'])
    except Exception as e:
        print(f"Error deleting meal plan entry {p['id']}: {e}")

def full_wipe():
    print("🚀 Starting FULL Mealie wipe...")
    client = UnifiedMealieClient()

    # 1. Delete all recipes
    print("\n--- Deleting all recipes ---")
    recipes = client.get_all_recipes()
    print(f"Found {len(recipes)} recipes.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(delete_recipe_task, client, r) for r in recipes]
        concurrent.futures.wait(futures)

    print(f"Deleted {len(recipes)} recipes.")

    # 2. Clear active shopping list
    print("\n--- Clearing active shopping list ---")
    print(f"Clearing active shopping list (ID: {config.ACTIVE_LIST_ID})")
    try:
        client.clear_shopping_list(config.ACTIVE_LIST_ID)
        print("Active shopping list cleared.")
    except Exception as e:
        print(f"Error clearing shopping list: {e}")

    # 3. Clear meal plan
    print("\n--- Clearing all meal plan entries ---")
    # Using a very wide range to catch all entries
    start_date = "1970-01-01"
    end_date = "2100-01-01"
    try:
        existing_plans = client.get_meal_plan(start_date, end_date)
        print(f"Found {len(existing_plans)} meal plan entries.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(delete_meal_plan_entry_task, client, p) for p in existing_plans]
            concurrent.futures.wait(futures)

        print(f"Cleared {len(existing_plans)} meal plan entries.")
    except Exception as e:
        print(f"Error clearing meal plan: {e}")

    print("\n✅ Mealie full wipe completed.")

if __name__ == "__main__":
    full_wipe()
