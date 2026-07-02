import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.ai_client import AIClient
from mealie_planner.email_notifier import EmailNotifier
from mealie_planner.plan_generator import PlanGenerator
from mealie_planner.recipe_crawler import RecipeCrawler
from mealie_planner.shopping_sync import ShoppingListSync
from mealie_planner.unified_client import UnifiedMealieClient


def test_plan_breakfasts():
    client = UnifiedMealieClient()
    ai = AIClient()
    crawler = RecipeCrawler(client, ai)
    shopping = ShoppingListSync(client, ai, crawler)
    notifier = EmailNotifier(client, ai)
    generator = PlanGenerator(client, ai, crawler, shopping, notifier)
    
    # Generate dates for next Saturday
    today = datetime.now()
    start_date = today + timedelta(days=(5 - today.weekday() + 7) % 7)
    end_date = start_date + timedelta(days=6)
    
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Generating plan from {start_date_str} to {end_date_str} to verify breakfast options...")
    
    # We call generate_weekly_plan directly
    generator.generate_weekly_plan(
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        exclude_text="",
        freezer_items="chicken",
        special_requests="make sure we get oats and bagels for breakfast",
        low_staples_ids=[]
    )
    
    # Fetch plans back to verify
    plans = client.get_meal_plan(start_date_str, end_date_str)
    print("\n--- Scheduled Breakfasts ---")
    breakfast_count = 0
    for p in sorted(plans, key=lambda x: (x.get('date', ''), x.get('entryType', ''))):
        if p.get('entryType') == 'breakfast':
            print(f"Date: {p.get('date')} ({datetime.strptime(p.get('date'), '%Y-%m-%d').strftime('%A')}) | Breakfast: {p.get('title')}")
            breakfast_count += 1
            
    if breakfast_count == 0:
        print("No breakfast entries found.")

if __name__ == '__main__':
    test_plan_breakfasts()
