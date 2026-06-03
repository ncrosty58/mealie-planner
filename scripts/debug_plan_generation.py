import os
import sys
from datetime import datetime, timedelta

# Add the project root to sys.path to ensure module discovery
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.ai_client import AIClient
from mealie_planner.recipe_crawler import RecipeCrawler
from mealie_planner.shopping_sync import ShoppingListSync
from mealie_planner.email_notifier import EmailNotifier
from mealie_planner.plan_generator import PlanGenerator

if __name__ == "__main__":
    print("--- Debugging generate_weekly_plan ---")
    try:
        # Define placeholder dates and parameters for testing
        today = datetime.now()
        start_date = today + timedelta(days=(5 - today.weekday() + 7) % 7) # Next Saturday
        end_date = start_date + timedelta(days=6)
        
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")
        
        # Instantiate clients and generator directly
        client = UnifiedMealieClient()
        ai = AIClient()
        crawler = RecipeCrawler(client, ai)
        shopping = ShoppingListSync(client, ai, crawler)
        notifier = EmailNotifier(client, ai)
        generator = PlanGenerator(client, ai, crawler, shopping, notifier)
        
        # Call generate_weekly_plan
        generator.generate_weekly_plan(
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            exclude_text="",
            freezer_items="chicken breast",
            special_requests="more vegetarian, less red meat",
            low_staples_ids=[]
        )
        print("--- generate_weekly_plan debugging complete ---")
    except Exception as e:
        print(f"Error during generate_weekly_plan debugging: {e}")
