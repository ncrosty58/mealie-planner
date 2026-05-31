import time
import json
import re

from .config import (
    ACTIVE_LIST_ID, STAPLES_LIST_ID, FAMILY_DIETARY_RULES_PROMPT,
    _SHOPPING_LIST_SYNC_SKILL_DEFINITION
)
from .recipe_crawler import RecipeCrawler

class ShoppingListSync:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client
        self.crawler = RecipeCrawler(mealie_client, gemini_client)

    def sync_shopping_list(self, start_date_str, end_date_str, low_staples_ids=[], progress_callback=None, freezer_items="") -> bool:
        """Sync active shopping list based on scheduled recipes and low staples using the unified shopping-list-sync AI skill."""
        print(f"Starting AI shopping list sync for {start_date_str} to {end_date_str}...")
        if progress_callback:
            progress_callback("AI shopping list sync started...", 90)
        try:
            # Give Mealie a moment to process previous scheduling calls
            time.sleep(1.5)

            # 1. Fetch data from Mealie
            meal_plans = self.client.get_meal_plan(start_date_str, end_date_str)
            print(f"[Sync] Found {len(meal_plans)} total meal plan entries for period.")
            
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            
            # Build set of low staples IDs (hyphen-insensitive)
            low_ids_clean = {s_id.replace('-', '') for s_id in low_staples_ids}
            
            # Map low staples to their notes (names) and build staples notes list
            staples_notes = [item['note'] for item in staples]

            # Parse freezer items for the AI skill payload
            inventory_items = []
            if freezer_items:
                inventory_items = [i.strip() for i in freezer_items.split(",") if i.strip()]

            low_staples_notes = []
            for item in staples:
                clean_id = item['id'].replace('-', '')
                if clean_id in low_ids_clean:
                    low_staples_notes.append(item['note'])
                    
            # 2. Extract ingredient display strings from meals
            if progress_callback:
                progress_callback("Extracting ingredients from scheduled meals...", 93)
            raw_recipe_ingredients = []
            
            # Pre-fetch all recipes for fast lookup during sync
            all_recipes_overview = self.crawler.get_recipes_from_db()

            for p in meal_plans:
                rid = p.get('recipeId')
                title = p.get('title') or ""
                
                # If it's a text-based entry (like lunch "Sandwich"), try to find a matching recipe
                if not rid and title:
                    rid = self.crawler.find_recipe_for_ingredient(title, all_recipes=all_recipes_overview)
                
                if rid:
                    try:
                        r_details = self.client.get_recipe_details(rid)
                        for ing in r_details.get('recipeIngredient', []):
                            disp = ing.get('display') or ing.get('originalText') or ""
                            disp = disp.strip()
                            if disp:
                                raw_recipe_ingredients.append(disp)
                    except Exception as e:
                        print(f"Error fetching recipe details for ID {rid}: {e}")
                        
            print(f"[Sync] Extracted {len(raw_recipe_ingredients)} raw ingredient strings from meals.")
            
            # 3. Call the unified shopping-list-sync AI skill
            if progress_callback:
                progress_callback("Generating final shopping list using AI...", 96)
            
            payload = {
                "ingredients": raw_recipe_ingredients,
                "staples": staples_notes,
                "inventory_items": inventory_items,
                "low_staples": low_staples_notes
            }
            
            prompt = (
                """You are an expert in the 'Shopping List Sync Skill'.

""" +
                _SHOPPING_LIST_SYNC_SKILL_DEFINITION + """

### CONTEXT FOR THIS INVOCATION:
""" +
                f"Input Data: {json.dumps(payload)}\n" +
                f"Family Dietary Rules: {FAMILY_DIETARY_RULES_PROMPT}\n\n" +
                "Return ONLY the JSON array of objects as specified in the skill definition."
            )
            
            print("--- AI SHOPPING LIST SYNC PROMPT ---")
            ai_response = self.gemini.call(prompt, expect_json=True)
            try:
                ai_output = json.loads(ai_response)
                print(f"[AI] Received {len(ai_output)} items from shopping list sync skill.")
            except Exception as parse_err:
                print(f"Failed to parse AI response: {parse_err}. Response was: {ai_response}")
                raise parse_err
                
            # Fetch labels and cache them
            existing_labels = self.client.get_labels()
            label_cache = {l['name'].strip().lower(): l['id'] for l in existing_labels}

            def resolve_label_id(cat_name):
                cat_name = cat_name.strip()
                if not cat_name:
                    return None
                cat_lower = cat_name.lower()
                if cat_lower in label_cache:
                    return label_cache[cat_lower]
                try:
                    print(f"[Sync] Creating new label in Mealie: '{cat_name}'")
                    new_lbl = self.client.create_label(cat_name)
                    label_cache[cat_lower] = new_lbl['id']
                    return new_lbl['id']
                except Exception as le:
                    print(f"Error creating label '{cat_name}': {le}")
                    return None

            # 4. Process final ingredients: tag Dirty Dozen organic items
            ingredients_list = []
            for idx, item in enumerate(ai_output):
                name = item.get('name') or ''
                name = name.strip()
                if not name:
                    continue
                qty = item.get('quantity', 1.0)
                
                unit = item.get('unit') or ''
                unit = unit.strip()
                
                category = item.get('category') or ''
                label_id = resolve_label_id(category) if category else None
                
                # For ingredients, include the unit in the note (e.g. "1 lb Chicken Breast")
                # For staples (where unit might be null/empty), just use the name
                full_note = f"{unit} {name}".strip() if unit else name
                
                ingredients_list.append({
                    "shoppingListId": ACTIVE_LIST_ID,
                    "note": full_note,
                    "quantity": qty,
                    "checked": False,
                    "position": idx,
                    "labelId": label_id
                })
                
            print(f"[Sync] Final shopping list contains {len(ingredients_list)} items.")
                
            # 5. Clear the active list and add new items
            if progress_callback:
                progress_callback("Clearing active shopping list in Mealie...", 98)
            print(f"Clearing active shopping list {ACTIVE_LIST_ID}...")
            self.client.clear_shopping_list(ACTIVE_LIST_ID)
            
            if progress_callback:
                progress_callback(f"Bulk adding {len(ingredients_list)} items to active shopping list...", 99)
            print(f"Adding {len(ingredients_list)} items in bulk to active shopping list...")
            if ingredients_list:
                self.client.add_shopping_list_items_bulk(ingredients_list)
                
            print(f"AI shopping list sync completed successfully. Added {len(ingredients_list)} items.")
            if progress_callback:
                progress_callback("Shopping list synchronization complete!", 100)
            return True
        except Exception as e:
            print(f"Error during AI shopping list sync: {e}")
            if progress_callback:
                progress_callback(f"Error during shopping list sync: {str(e)}", 100)
            return False
