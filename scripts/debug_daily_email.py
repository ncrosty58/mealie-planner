import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.mealie_client import MealieClient
from mealie_planner.gemini_client import GeminiClient
from mealie_planner.email_notifier import EmailNotifier

def generate_debug_email(date_str):
    client = MealieClient()
    gemini = GeminiClient()
    notifier = EmailNotifier(client, gemini)
    
    # 1. Fetch meal plans for specified date
    plans = client.get_meal_plan(date_str, date_str)
    if not plans:
        print(f"No scheduled meals for {date_str}.")
        return False
        
    bf = next((p['title'] for p in plans if p['entryType'] == 'breakfast'), "Staples")
    ln = next((p['title'] for p in plans if p['entryType'] == 'lunch'), "Leftovers")
    
    dinner_item = next((p for p in plans if p['entryType'] == 'dinner'), None)
    dn_title = "Eating Out"
    dn_recipe = None
    ai_prep_note = ""
    
    if dinner_item:
        ai_prep_note = dinner_item.get('text') or ""
        if dinner_item.get('recipeId'):
            try:
                dn_recipe = client.get_recipe_details(dinner_item['recipeId'])
                dn_title = dn_recipe['name']
            except Exception as e:
                print(f"Error fetching recipe details: {e}")
                dn_title = "Recipe Details Unavailable"
        elif dinner_item.get('title'):
            dn_title = dinner_item['title']

    print(f"Dinner Title: {dn_title}")
    print(f"Prep Note: {ai_prep_note}")

    # 2. Generate AI summary
    parsed_recipe_info = notifier.parse_recipe_details_for_ai(dn_recipe) if dn_recipe else None
    
    print("\n--- Generating AI Summary ---")
    ai_summary = notifier.generate_daily_ai_summary("Sunday", bf, ln, dn_title, parsed_recipe_info, ai_prep_note)
    print(f"Gemini Response:\n{ai_summary}\n")
    
    # 3. Nutrition for today
    daily_nutrition, _ = notifier.nutrition.calculate_nutrition_for_range(date_str, date_str)
    today_nutrients = daily_nutrition.get(date_str, {})
    
    # 4. Build HTML
    html = notifier.build_daily_briefing_html(
        day_name="Sunday",
        date_str=date_str,
        bf=bf,
        ln=ln,
        dn_title=dn_title,
        dn_recipe=dn_recipe,
        ai_prep_note=ai_prep_note,
        today_nutrients=today_nutrients,
        ai_summary=ai_summary
    )
    
    # Write to local file
    output_path = os.path.join(os.path.dirname(__file__), '../debug_email.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Successfully generated daily email briefing preview at {os.path.abspath(output_path)}")

if __name__ == '__main__':
    # Use tomorrow's date which has dinner recipe scheduled
    target_date = "2026-05-31"
    generate_debug_email(target_date)
