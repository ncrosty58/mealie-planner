import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.mealie_client import MealieClient

def list_upcoming_meals():
    client = MealieClient()
    today = datetime.now()
    # Let's check 7 days in the past and 7 days in the future to see what plans exist
    start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (today + timedelta(days=14)).strftime("%Y-%m-%d")
    
    print(f"Fetching plans from {start_date} to {end_date}...")
    plans = client.get_meal_plan(start_date, end_date)
    
    if not plans:
        print("No plans found.")
        return
        
    print(f"Found {len(plans)} scheduled meal items:")
    for plan in sorted(plans, key=lambda x: (x.get('date', ''), x.get('entryType', ''))):
        print(f"Date: {plan.get('date')} | Type: {plan.get('entryType')} | Title: {plan.get('title')} | Recipe ID: {plan.get('recipeId')}")

if __name__ == '__main__':
    list_upcoming_meals()
