import json
import random
from datetime import datetime, timedelta

from .config import (
    FAMILY_DIETARY_RULES_PROMPT, BREAKFAST_PROFILES, get_banned_recipes,
    _WEEKLY_MEAL_SELECTION_SKILL_DEFINITION,
    _BANNED_RECIPES_SKILL_DEFINITION
)
from .recipe_crawler import RecipeCrawler
from .shopping_sync import ShoppingListSync
from .email_notifier import EmailNotifier
from .parsers import parse_freezer_items, parse_exclusions
from .exceptions import MealieAPIError, SkillParsingError
from .models import WeeklyMealPlanResponse

class PlanGenerator:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client
        self.crawler = RecipeCrawler(mealie_client, gemini_client)
        self.shopping = ShoppingListSync(mealie_client, gemini_client)
        self.notifier = EmailNotifier(mealie_client, gemini_client)

    def generate_weekly_plan(self, start_date_str, end_date_str, exclude_text="", freezer_items="", special_requests="", low_staples_ids=[], progress_callback=None):
        """Generate weekly plan using an AI-driven intelligent rule-based scoring engine and schedule in Mealie."""
        if progress_callback:
            progress_callback("Analyzing inputs and processing freezer/pantry/fridge items...", 5)
        
        # Fetch all recipes once to use for lookup and deduplication
        all_recipes = self.crawler.get_recipes_from_db()

        priority_recipe_ids = []
        # Map each freezer/pantry item to its resolved recipe ID for the AI prompt
        item_to_recipe_map = {}
        if freezer_items:
            # Use AI to parse free-text items into structured ingredients
            parsed_items = parse_freezer_items(self.gemini, freezer_items)
            
            for item in parsed_items:
                core = item.get("core_ingredient", item.get("raw", ""))
                raw = item.get("raw", core)
                
                if progress_callback:
                    progress_callback(f"Finding/importing recipe for: {core}...", 15)
                
                recipe_id = self.crawler.find_recipe_for_ingredient(core, all_recipes=all_recipes)
                if not recipe_id:
                    if self.crawler.find_and_import_recipe(core, existing_recipe_ids=priority_recipe_ids):
                        all_recipes = self.crawler.get_recipes_from_db()
                        recipe_id = self.crawler.find_recipe_for_ingredient(core, all_recipes=all_recipes)
                
                if recipe_id and recipe_id not in priority_recipe_ids:
                    priority_recipe_ids.append(recipe_id)
                    item_to_recipe_map[raw] = recipe_id
                elif recipe_id:
                    item_to_recipe_map[raw] = recipe_id
                else:
                    print(f"[Plan Generation] WARNING: Could not find or import a recipe for '{raw}' (core: '{core}')")
                    
                    
        if progress_callback:
            progress_callback("Filtering recipes and checking exclusions...", 40)
        
        banned_recipes = [name.lower() for name in get_banned_recipes()]
        print(f"[Plan Generation] Loaded banned recipes: {banned_recipes}")

        allowed_recipes = []
        
        for r in all_recipes:
            name_lower = r['name'].lower()
            slug_lower = r.get('slug', '').lower()
            desc_lower = r.get('description', '').lower() if r.get('description') else ''
            
            # Tags are often dictionaries in newer Mealie versions
            tags = []
            for t in r.get('tags', []):
                if isinstance(t, dict):
                    tags.append(t.get('name', '').lower())
                elif isinstance(t, str):
                    tags.append(t.lower())
            
            # Check against specific banned recipe names
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
            
        # Build a lookup map for validation after AI selection
        catalogue_ids = {r['id'] for r in allowed_recipes}

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        num_days = (end_date - start_date).days + 1
        exclusions = parse_exclusions(self.gemini, exclude_text, start_date, end_date)
        dinner_days = [
            (start_date + timedelta(days=i)).strftime("%A")
            for i in range(num_days)
            if 'dinner' not in exclusions.get((start_date + timedelta(days=i)).strftime("%A"), [])
        ]
        num_dinners = len(dinner_days)
        target_date_strings = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]

        # Fetch recently planned recipes (preceding 7 days) to avoid repeating them
        recent_recipe_names = []
        try:
            prev_start = start_date - timedelta(days=7)
            prev_end = start_date - timedelta(days=1)
            prev_plans = self.client.get_meal_plan(prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d"))
            for p in prev_plans:
                if p.get('recipe') and p['recipe'].get('name'):
                    recent_recipe_names.append(p['recipe']['name'])
            recent_recipe_names = list(set(recent_recipe_names))
        except MealieAPIError as e:
            print(f"Error fetching recently planned recipes: {e}")

        recipe_catalogue = [
            {
                "id": r["id"],
                "name": r["name"],
                "description": (r.get("description") or "")[:120],
                "tags": [t.get('name', t) if isinstance(t, dict) else t for t in r.get('tags', [])],
                "fiber_g": r.get("fiber_content"),
                "ingredients": r.get("ingredients", []),
                "instructions_preview": " ".join(r.get("instructions", []))[:120]
            }
            for r in allowed_recipes
        ]
        random.shuffle(recipe_catalogue)

        # Classify early vs late days relative to the planning range
        if num_days <= 1:
            early_target_dates = target_date_strings
            late_target_dates = target_date_strings
        elif num_days == 2:
            early_target_dates = target_date_strings[:1]
            late_target_dates = target_date_strings[1:]
        elif num_days == 3:
            early_target_dates = target_date_strings[:2]  # Wed, Thu
            late_target_dates = target_date_strings[2:]   # Fri
        else:
            # 4 to 7 days
            split_idx = num_days - 3 if num_days >= 6 else num_days // 2
            early_target_dates = target_date_strings[:split_idx]
            late_target_dates = target_date_strings[split_idx:]
            
        early_days_display = ", ".join([datetime.strptime(d, "%Y-%m-%d").strftime("%A (%Y-%m-%d)") for d in early_target_dates])
        late_days_display = ", ".join([datetime.strptime(d, "%Y-%m-%d").strftime("%A (%Y-%m-%d)") for d in late_target_dates])

        selection_prompt = (
            """You are an expert in the 'Mealie Weekly Meal Selection Skill'.

""" +
            _WEEKLY_MEAL_SELECTION_SKILL_DEFINITION +
            """

### BANNED RECIPES SKILL RULES:
""" +
            _BANNED_RECIPES_SKILL_DEFINITION +
            """

### CONTEXT FOR THIS INVOCATION:
""" +
            f"- **Family Dietary Rules & Preferences**: {FAMILY_DIETARY_RULES_PROMPT}\n" +
            f"- **Banned Recipes (NEVER select these)**: {', '.join(get_banned_recipes())}\n" +
            f"- **Target Planning Dates (You MUST generate exactly these {num_days} dates in this exact order, even if some or all meals on a day are excluded)**: {json.dumps(target_date_strings)}\n" +
            f"- **REDEFINED PERISHABILITY RULES FOR THIS PLANNED RANGE (STRICT RULE OVERRIDE)**:\n" +
            f"  * **EARLY DAYS (Reserve for fresh/highly-perishable ingredients)**: {early_days_display}\n" +
            f"  * **LATE DAYS (Reserve for frozen, canned, or shelf-stable ingredients)**: {late_days_display}\n" +
            f"  * **Strict Sequencing constraint**: You MUST schedule recipes using frozen/shelf-stable items strictly on the LATE DAYS listed above. If there are multiple late days, prioritize the latest ones (e.g. towards the end of the late days list) to ensure they are eaten last. You MUST NOT schedule frozen/shelf-stable ingredients on the EARLY DAYS.\n" +
            (f"- **Note on Weekdays**: Since the target planning range ({start_date_str} to {end_date_str}) is shorter than a full 7-day week, if any prioritized items are described as fresh, schedule them on the earliest available target dates (e.g. Wednesday or Thursday) rather than requiring Sat-Tue.\n" if num_days < 7 else "") +
            f"- **Meal Exclusions (Skipped/Eating Out)**: {json.dumps(exclusions)}\n" +
            f"- **Freezer/Pantry/Fridge items to prioritize**: {freezer_items or 'none'}\n" +
            (f"- **MANDATORY Priority Recipes (MUST include ALL of these in the plan)**: {json.dumps(item_to_recipe_map)}\n" if item_to_recipe_map else "") +
            f"- **Special requests from the family**: {special_requests or 'none'}\n" +
            f"- **Recently planned recipes (AVOID selecting these)**: {', '.join(recent_recipe_names) if recent_recipe_names else 'none'}\n\n" +
            f"### RECIPE CATALOGUE (JSON):\n" +
            f"{json.dumps(recipe_catalogue, indent=2)}\n\n" +
            "Return ONLY the JSON object as specified in the skill definition."
        )

        if progress_callback:
            progress_callback(f"Querying Gemini AI for optimized {num_days}-day plan...", 50)
        
        meals = []
        try:
            raw = self.gemini.call(selection_prompt, response_schema=WeeklyMealPlanResponse, temperature=0.7)
            ai_result = WeeklyMealPlanResponse.model_validate_json(raw).model_dump()
            
            for day_entry in ai_result.get("days", []):
                d_str = day_entry['date']
                if d_str not in target_date_strings:
                    print(f"[Plan Generation] WARNING: AI generated out-of-range date {d_str}. Skipping.")
                    continue
                m = day_entry['meals']
                prep_note = m.get('prep_note') or ""
                
                # Deterministic Exclusion Enforcement
                day_name = datetime.strptime(d_str, "%Y-%m-%d").strftime("%A")
                day_exclusions = exclusions.get(day_name, [])
                print(f"[Plan Generation] Processing {day_name} ({d_str}) with exclusions: {day_exclusions}")

                # Breakfast
                if 'breakfast' in day_exclusions:
                    meals.append({"date": d_str, "entryType": "breakfast", "title": "Skipped", "recipeId": None})
                else:
                    breakfast_title = m.get('breakfast', 'Staples')
                    # Double-check if AI returned something else for skipped meal
                    if breakfast_title.lower() == 'skipped':
                        breakfast_title = "Skipped"
                    meals.append({"date": d_str, "entryType": "breakfast", "title": breakfast_title, "recipeId": None})
                
                # Lunch
                if 'lunch' in day_exclusions:
                    meals.append({"date": d_str, "entryType": "lunch", "title": "Skipped", "recipeId": None})
                else:
                    lunch_title = m.get('lunch', 'Leftovers')
                    if lunch_title.lower() == 'skipped':
                        lunch_title = "Skipped"
                    meals.append({"date": d_str, "entryType": "lunch", "title": lunch_title, "recipeId": None})
                
                # Dinner
                if 'dinner' in day_exclusions:
                    meals.append({"date": d_str, "entryType": "dinner", "title": "Eating Out", "recipeId": None, "text": prep_note})
                else:
                    din_val = m.get('dinner')
                    is_uuid = False
                    if din_val:
                        try:
                            import uuid
                            uuid.UUID(str(din_val))
                            is_uuid = True
                        except ValueError:
                            is_uuid = False
                    
                    if is_uuid:
                        # Deterministic Safety Check: Verify ID exists in catalogue
                        if din_val in catalogue_ids:
                            meals.append({"date": d_str, "entryType": "dinner", "title": "", "recipeId": din_val, "text": prep_note})
                        else:
                            print(f"[Plan Generation] WARNING: AI hallucinated recipe ID {din_val}. Falling back to text entry.")
                            meals.append({"date": d_str, "entryType": "dinner", "title": "Planned Dinner", "recipeId": None, "text": prep_note})
                    else:
                        meals.append({"date": d_str, "entryType": "dinner", "title": din_val or "Eating Out", "recipeId": None, "text": prep_note})
                
            print(f"[AI] Successfully generated structured 7-day plan.")
        except Exception as e:
            print(f"[AI] Full plan generation failed: {e} — falling back to basic logic")
            if progress_callback:
                progress_callback(f"Selection failed ({str(e)}), falling back to basic selection...", 65)
            
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
        
        try:
            existing_plans = self.client.get_meal_plan(start_date_str, end_date_str)
            for p in existing_plans:
                self.client.delete_meal_plan_entry(p['id'])
        except MealieAPIError as e:
            print(f"Error clearing existing plans: {e}")
            
        if progress_callback:
            progress_callback("Scheduling new breakfasts, lunches, and dinners...", 80)
        for m in meals:
            try:
                self.client.schedule_meal(
                    date_str=m['date'],
                    entry_type=m['entryType'],
                    title=m.get('title') or "",
                    text=m.get('text') or "",
                    recipe_id=m.get('recipeId')
                )
            except MealieAPIError as e:
                print(f"Error scheduling meal {m}: {e}")
            
        self.shopping.sync_shopping_list(start_date_str, end_date_str, low_staples_ids, progress_callback=progress_callback, freezer_items=freezer_items)
        
        if progress_callback:
            progress_callback("Sending weekly plan report email to family...", 99)
        self.notifier.send_saturday_report_email(start_date_str, end_date_str, exclude_text, freezer_items, low_staples_ids, special_requests)
        
        if progress_callback:
            progress_callback("Meal plan generation complete!", 100)
        print(f"Rule-based plan successfully generated and scheduled for {start_date_str} to {end_date_str}.")

