import json
import random
from datetime import datetime, timedelta

from config import (
    load_skill_md, FAMILY_DIETARY_RULES_PROMPT, PROCESSED_MEATS, BREAKFAST_PROFILES, get_banned_recipes
)
from mealie_client import MealieClient
from gemini_client import call_gemini
from recipe_crawler import get_recipes_from_db, find_recipe_for_ingredient, find_and_import_recipe
from shopping_sync import sync_shopping_list
from email_notifier import send_saturday_report_email

_MEAL_EXCLUSION_PARSING_SKILL_DEFINITION = load_skill_md('meal-exclusion-parsing')
_WEEKLY_MEAL_SELECTION_SKILL_DEFINITION = load_skill_md('weekly-meal-selection')

def parse_exclusions(text: str) -> dict:
    """Use Gemini to interpret a free-text description of which meals to skip, delegating to the AI skill."""
    if not text or not text.strip():
        return {}

    today = datetime.now()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    week_dates = {
        (next_monday + timedelta(days=i)).strftime("%A"): (next_monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(7)
    }

    prompt = (
        """You are an expert in the 'Mealie Meal Exclusion Parsing Skill'.

""" +
        _MEAL_EXCLUSION_PARSING_SKILL_DEFINITION +
        """

### CONTEXT FOR THIS INVOCATION:
""" +
        f"User input: {text}\n" +
        f"Week dates: {', '.join(f'{d} ({dt})' for d, dt in week_dates.items())}.\n\n" +
        "Return ONLY the JSON object as specified in the skill definition."
    )

    try:
        raw = call_gemini(prompt, expect_json=True)
        result = json.loads(raw)
        valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
        valid_meals = {"breakfast", "lunch", "dinner"}
        exclusions = {}
        for day, meals in result.items():
            if day in valid_days and isinstance(meals, list):
                cleaned_meals = [m for m in meals if m in valid_meals]
                if cleaned_meals:
                    exclusions[day] = cleaned_meals
        print(f"[AI] Parsed exclusions: {exclusions}")
        return exclusions
    except Exception as e:
        print(f"[AI] parse_exclusions failed: {e} — no exclusions applied")
        return {}

def generate_weekly_plan(start_date_str, end_date_str, exclude_text="", freezer_items="", special_requests="", low_staples_ids=[], progress_callback=None):
    """Generate weekly plan using an AI-driven intelligent rule-based scoring engine and schedule in Mealie."""
    client = MealieClient()
    
    if progress_callback:
        progress_callback("Analyzing inputs and processing freezer/pantry/fridge items...", 5)
    
    # Fetch all recipes once to use for lookup and deduplication
    all_recipes = get_recipes_from_db()

    priority_recipe_ids = []
    if freezer_items:
        items = [i.strip() for i in freezer_items.split(",") if i.strip()]
        for item in items:
            if progress_callback:
                progress_callback(f"Finding/importing recipe for item: {item}...", 15)
            
            # Pass all_recipes to avoid redundant fetches and use improved matching
            recipe_id = find_recipe_for_ingredient(item, all_recipes=all_recipes)
            if not recipe_id:
                if find_and_import_recipe(item, existing_recipe_ids=priority_recipe_ids): # Pass existing IDs for AI to avoid re-importing
                    # Re-fetch after import to get the new ID
                    all_recipes = get_recipes_from_db()
                    recipe_id = find_recipe_for_ingredient(item, all_recipes=all_recipes)
            
            if recipe_id and recipe_id not in priority_recipe_ids:
                priority_recipe_ids.append(recipe_id)
                
    if progress_callback:
        progress_callback("Filtering recipes and checking exclusions...", 40)
    
    banned_recipes = [name.lower() for name in get_banned_recipes()]
    print(f"[Plan Generation] Loaded banned recipes: {banned_recipes}")

    # all_recipes already fetched above
    allowed_recipes = []
    
    for r in all_recipes:
        name_lower = r['name'].lower()
        slug_lower = r.get('slug', '').lower()
        desc_lower = r.get('description', '').lower() if r.get('description') else ''
        tags = [t.lower() for t in r.get('tags', [])]
        
        all_text = f"{name_lower} {slug_lower} {desc_lower} " + " ".join(tags)
        
        r['_all_text'] = all_text
        
        if any(kw in all_text for kw in PROCESSED_MEATS):
            continue
            
        is_banned = False
        for banned_name in banned_recipes:
            if banned_name in name_lower or banned_name in slug_lower or name_lower in banned_name:
                is_banned = True
                break
        if is_banned:
            print(f"[Plan Generation] Excluding banned recipe: {r['name']}")
            continue
            
        allowed_recipes.append(r)
        
    if not allowed_recipes:
        print("Warning: No recipes left after filtering! Using unfiltered recipes.")
        allowed_recipes = all_recipes
        
    if progress_callback:
        progress_callback("Filtering recipes and checking exclusions...", 40)

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    num_days = (end_date - start_date).days + 1
    exclusions = parse_exclusions(exclude_text)
    dinner_days = [
        (start_date + timedelta(days=i)).strftime("%A")
        for i in range(num_days)
        if 'dinner' not in exclusions.get((start_date + timedelta(days=i)).strftime("%A"), [])
    ]
    num_dinners = len(dinner_days)

    # Fetch recently planned recipes (preceding 7 days) to avoid repeating them
    recent_recipe_names = []
    try:
        prev_start = start_date - timedelta(days=7)
        prev_end = start_date - timedelta(days=1)
        prev_plans = client.get_meal_plan(prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d"))
        for p in prev_plans:
            if p.get('recipe') and p['recipe'].get('name'):
                recent_recipe_names.append(p['recipe']['name'])
        recent_recipe_names = list(set(recent_recipe_names))
    except Exception as e:
        print(f"Error fetching recently planned recipes: {e}")

    recipe_catalogue = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": (r.get("description") or "")[:120],
            "tags": r.get("tags", []),
            "fiber_g": r.get("fiber_content"),
            "ingredients_preview": ", ".join(r.get("ingredients", [])[:5]),
            "instructions_preview": " ".join(r.get("instructions", []))[:80]
        }
        for r in allowed_recipes
    ]
    # Shuffle the catalogue to break order bias and increase variety
    random.shuffle(recipe_catalogue)

    selection_prompt = (
        """You are an expert in the 'Mealie Weekly Meal Selection Skill'.

""" +
        _WEEKLY_MEAL_SELECTION_SKILL_DEFINITION +
        """

### CONTEXT FOR THIS INVOCATION:
""" +
        f"- **Family Dietary Rules & Preferences**: {FAMILY_DIETARY_RULES_PROMPT}\n" +
        f"- **Banned Recipes (NEVER select these)**: {', '.join(get_banned_recipes())}\n" +
        f"- **Plan Start Date (Saturday)**: {start_date_str}\n" +
        f"- **Meal Exclusions (Skipped/Eating Out)**: {json.dumps(exclusions)}\n" +
        f"- **Freezer/Pantry/Fridge items to prioritize**: {freezer_items or 'none'}\n" +
        f"- **Special requests from the family**: {special_requests or 'none'}\n" +
        f"- **Recently planned recipes (AVOID selecting these)**: {', '.join(recent_recipe_names) if recent_recipe_names else 'none'}\n\n" +
        f"### RECIPE CATALOGUE (JSON):\n" +
        f"{json.dumps(recipe_catalogue, indent=2)}\n\n" +
        "Return ONLY the JSON object as specified in the skill definition."
    )

    if progress_callback:
        progress_callback("Querying Gemini AI for optimized 7-day plan...", 50)
    
    meals = []
    try:
        raw = call_gemini(selection_prompt, expect_json=True, temperature=0.7)
        ai_result = json.loads(raw)
        
        # Build the final meals list from AI output
        for day_entry in ai_result.get("days", []):
            d_str = day_entry['date']
            m = day_entry['meals']
            prep_note = m.get('prep_note') or ""
            
            # Breakfast
            meals.append({"date": d_str, "entryType": "breakfast", "title": m.get('breakfast', 'Staples'), "recipeId": None})
            
            # Lunch
            meals.append({"date": d_str, "entryType": "lunch", "title": m.get('lunch', 'Leftovers'), "recipeId": None})
            
            # Dinner
            din_val = m.get('dinner')
            # Robust UUID check
            is_uuid = False
            if din_val:
                try:
                    import uuid
                    uuid.UUID(str(din_val))
                    is_uuid = True
                except ValueError:
                    is_uuid = False
            
            if is_uuid:
                meals.append({"date": d_str, "entryType": "dinner", "title": "", "recipeId": din_val, "text": prep_note})
            else:
                meals.append({"date": d_str, "entryType": "dinner", "title": din_val or "Eating Out", "recipeId": None, "text": prep_note})
            
        print(f"[AI] Successfully generated structured 7-day plan.")
    except Exception as e:
        print(f"[AI] Full plan generation failed: {e} — falling back to basic logic")
        if progress_callback:
            progress_callback(f"Gemini selection failed ({str(e)}), falling back to basic selection...", 65)
        
        # --- BASIC FALLBACK LOGIC ---
        random.shuffle(allowed_recipes)
        selected_ids = [r["id"] for r in allowed_recipes[:num_dinners]]
        id_to_recipe = {r["id"]: r for r in allowed_recipes}
        clean_recipes = [id_to_recipe[rid] for rid in selected_ids if rid in id_to_recipe]
        
        meals = []
        current_date = start_date
        recipe_index = 0
        breakfasts = list(BREAKFAST_PROFILES.keys())
        while current_date <= end_date:
            d_str = current_date.strftime("%Y-%m-%d")
            day_name = current_date.strftime("%A")
            day_exclusions = exclusions.get(day_name, [])
            
            if 'breakfast' in day_exclusions:
                meals.append({"date": d_str, "entryType": "breakfast", "title": "Skipped", "recipeId": None})
            else:
                meals.append({"date": d_str, "entryType": "breakfast", "title": breakfasts[current_date.weekday() % len(breakfasts)], "recipeId": None})
                
            if 'lunch' in day_exclusions:
                meals.append({"date": d_str, "entryType": "lunch", "title": "Skipped", "recipeId": None})
            else:
                meals.append({"date": d_str, "entryType": "lunch", "title": "Leftovers", "recipeId": None})
            
            if 'dinner' in day_exclusions:
                meals.append({"date": d_str, "entryType": "dinner", "title": "Eating Out", "recipeId": None})
            else:
                if clean_recipes and recipe_index < len(clean_recipes):
                    meals.append({"date": d_str, "entryType": "dinner", "title": "", "recipeId": clean_recipes[recipe_index]['id']})
                    recipe_index += 1
                else:
                    meals.append({"date": d_str, "entryType": "dinner", "title": "TBD", "recipeId": None})
            current_date += timedelta(days=1)
        
    if progress_callback:
        progress_callback("Clearing old scheduled meals in Mealie calendar...", 70)
    existing_plans = client.get_meal_plan(start_date_str, end_date_str)
    for p in existing_plans:
        client.delete_meal_plan_entry(p['id'])
        
    if progress_callback:
        progress_callback("Scheduling new breakfasts, lunches, and dinners...", 80)
    for m in meals:
        client.schedule_meal(
            date_str=m['date'],
            entry_type=m['entryType'],
            title=m.get('title') or "",
            text=m.get('text') or "",
            recipe_id=m.get('recipeId')
        )
        
    sync_shopping_list(start_date_str, end_date_str, low_staples_ids, progress_callback=progress_callback)
    
    if progress_callback:
        progress_callback("Sending weekly plan report email to family...", 99)
    send_saturday_report_email(start_date_str, end_date_str, exclude_text, freezer_items, low_staples_ids, special_requests)
    
    if progress_callback:
        progress_callback("Meal plan generation complete!", 100)
    print(f"Rule-based plan successfully generated and scheduled for {start_date_str} to {end_date_str}.")
