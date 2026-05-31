import time
import json
import re

from .config import (
    ACTIVE_LIST_ID, STAPLES_LIST_ID, FAMILY_DIETARY_RULES_PROMPT,
    _SHOPPING_LIST_SYNC_SKILL_DEFINITION
)
from .recipe_crawler import RecipeCrawler
from .exceptions import MealieAPIError, SkillParsingError

class ShoppingListSync:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client
        self.crawler = RecipeCrawler(mealie_client, gemini_client)

    def sync_staples_only(self, low_staples_ids) -> bool:
        """Fast, deterministic sync of staples only. No AI, no clearing of recipes."""
        print("[Sync] Performing fast staples-only update...")
        try:
            # 1. Fetch current state
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            active_items = self.client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
            
            low_ids_clean = {s_id.replace('-', '').lower() for s_id in low_staples_ids}
            
            # Identify which items on the active list are "staples"
            # We match by name against the master staples list
            staple_names = {s['note'].strip().lower(): s for s in staples}
            
            active_staple_notes = []
            active_non_staple_notes = []
            for item in active_items:
                note = item['note'].strip().lower()
                if note in staple_names:
                    active_staple_notes.append(item)
                else:
                    active_non_staple_notes.append(item)

            # 2. Determine Additions
            # Items in low_ids_clean that aren't on the active list yet
            to_add = []
            active_notes_set = {i['note'].strip().lower() for i in active_items}
            
            for s in staples:
                if s['id'].replace('-', '').lower() in low_ids_clean:
                    if s['note'].strip().lower() not in active_notes_set:
                        to_add.append({
                            "shoppingListId": ACTIVE_LIST_ID,
                            "note": s['note'],
                            "quantity": s.get('quantity', 1.0),
                            "checked": False,
                            "labelId": s.get('labelId')
                        })

            # 3. Determine Deletions
            # Items on the active list that ARE staples but are NOT in low_ids_clean anymore
            to_delete_ids = []
            for item in active_staple_notes:
                # Find the master staple this item belongs to
                master_staple = staple_names.get(item['note'].strip().lower())
                if master_staple:
                    m_id = master_staple['id'].replace('-', '').lower()
                    if m_id not in low_ids_clean:
                        to_delete_ids.append(item['id'])

            # 4. Execute updates
            if to_delete_ids:
                print(f"[Sync] Removing {len(to_delete_ids)} staples no longer marked as low.")
                self.client.delete_shopping_list_items_bulk(to_delete_ids)
            
            if to_add:
                print(f"[Sync] Adding {len(to_add)} new low staples.")
                self.client.add_shopping_list_items_bulk(to_add)

            return True
        except Exception as e:
            print(f"Error during fast staples sync: {e}")
            return False

    def sync_shopping_list(self, start_date_str, end_date_str, low_staples_ids=[], progress_callback=None, freezer_items="") -> bool:
        """Sync active shopping list based on scheduled recipes and low staples using the unified shopping-list-sync AI skill."""
        print(f"Starting AI shopping list sync for {start_date_str} to {end_date_str}...")
        if progress_callback:
            progress_callback("AI shopping list sync started...", 90)
        try:
            # Give Mealie a moment to process previous scheduling calls
            time.sleep(1.0)

            # 1. Fetch data from Mealie
            meal_plans = self.client.get_meal_plan(start_date_str, end_date_str)
            print(f"[Sync] Found {len(meal_plans)} total meal plan entries for period.")
            
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            
            # Build set of low staples IDs (hyphen-insensitive)
            low_ids_clean = {s_id.replace('-', '').lower() for s_id in low_staples_ids}
            
            # Map low staples to their notes (names) and build staples notes list
            staples_notes = [item['note'] for item in staples]
            staple_names_lower = {s['note'].strip().lower() for s in staples}

            # State Preservation: If a staple is CURRENTLY on the active list, 
            # treat it as "low" so the AI doesn't filter it out during this sync.
            active_items = self.client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
            active_staple_names = []
            for item in active_items:
                note = item.get('note', '').strip().lower()
                if note in staple_names_lower:
                    active_staple_names.append(item['note'])

            # Parse freezer items
            inventory_items = []
            if freezer_items:
                inventory_items = [i.strip() for i in freezer_items.split(",") if i.strip()]

            low_staples_notes = []
            for item in staples:
                clean_id = item['id'].replace('-', '').lower()
                if clean_id in low_ids_clean:
                    low_staples_notes.append(item['note'])
            
            # Combine modal-marked low staples with currently active ones
            combined_low_staples = list(set(low_staples_notes + active_staple_names))
            
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
                    STANDARD_NON_RECIPE_MEALS = {
                        "leftovers", "pb&j sandwich", "eating out", "skipped", "planned meal", "planned dinner",
                        "cereal & milk", "yogurt with granola", "bagels & cream cheese", "english muffins with jam", "oats", "toast with jam"
                    }
                    if title.lower().strip() not in STANDARD_NON_RECIPE_MEALS:
                        rid = self.crawler.find_recipe_for_ingredient(title, all_recipes=all_recipes_overview)
                
                if rid:
                    try:
                        r_details = self.client.get_recipe_details(rid)
                        for ing in r_details.get('recipeIngredient', []):
                            disp = ing.get('display') or ing.get('originalText') or ""
                            disp = disp.strip()
                            if disp:
                                raw_recipe_ingredients.append(disp)
                    except MealieAPIError as e:
                        print(f"Error fetching recipe details for ID {rid}: {e}")
                        
            print(f"[Sync] Extracted {len(raw_recipe_ingredients)} raw ingredient strings from meals.")
            
            # 3. Call the unified shopping-list-sync AI skill
            if progress_callback:
                progress_callback("Generating final shopping list using AI...", 96)
            
            # Fetch standardized labels from Mealie
            all_labels = self.client.get_labels()
            available_label_names = [label['name'] for label in all_labels]
            label_name_to_id = {label['name']: label['id'] for label in all_labels}

            payload = {
                "ingredients": raw_recipe_ingredients,
                "staples": staples_notes,
                "inventory_items": inventory_items,
                "low_staples": combined_low_staples,
                "available_labels": available_label_names
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
            
            ai_response = self.gemini.call(prompt, expect_json=True)
            
            try:
                final_items = json.loads(ai_response)
                if not isinstance(final_items, list):
                    raise SkillParsingError("AI did not return a list for shopping list sync")
            except Exception as e:
                raise SkillParsingError(f"Failed to parse AI response: {e}")

            # 4. State-Aware Merge (Preserve checkmarks and prevent disappearing staples)
            if progress_callback:
                progress_callback("Merging updates and preserving checkmarks...", 97)
            
            # Step A: Map current items for easy lookup
            # Keys: foodId or cleaned note
            current_map = {}
            for item in active_items:
                f_id = item.get('foodId') or (item.get('food', {}) or {}).get('id')
                if f_id:
                    current_map[f_id] = item
                else:
                    note = item.get('note', '').strip().lower()
                    if note:
                        current_map[note] = item

            to_add = []
            to_update = []
            matched_current_ids = set()

            # Step B: Match new items against current ones
            # First, we need to get Mealie IDs for our new items
            new_item_names = [item.get('name', 'Unknown') for item in final_items]
            new_item_structures = self.client.parse_raw_ingredients(new_item_names)

            for idx, ai_item in enumerate(final_items):
                name = ai_item.get('name', 'Unknown Item')
                qty = ai_item.get('quantity', 1.0)
                unit = ai_item.get('unit') or ''
                
                # Get structured info from Mealie parser
                m_ing = new_item_structures[idx] if idx < len(new_item_structures) else {}
                m_food_id = (m_ing.get('food', {}) or {}).get('id')
                m_label_id = (m_ing.get('food', {}) or {}).get('labelId')
                m_unit_id = (m_ing.get('unit', {}) or {}).get('id')
                
                full_note = f"{unit.strip()} {name}".strip() if unit else name
                
                # Try to find match
                match = current_map.get(m_food_id) if m_food_id else None
                if not match:
                    match = current_map.get(full_note.strip().lower())
                
                if match:
                    # UPDATE existing item
                    matched_current_ids.add(match['id'])
                    # Preserve checked status!
                    updated_item = match.copy()
                    updated_item['note'] = full_note
                    updated_item['quantity'] = qty
                    updated_item['unitId'] = m_unit_id
                    updated_item['foodId'] = m_food_id
                    updated_item['labelId'] = m_label_id or match.get('labelId')
                    to_update.append(updated_item)
                else:
                    # ADD new item
                    to_add.append({
                        "shoppingListId": ACTIVE_LIST_ID,
                        "note": full_note,
                        "quantity": qty,
                        "checked": False,
                        "unitId": m_unit_id,
                        "foodId": m_food_id,
                        "labelId": m_label_id,
                        "position": idx
                    })

            # Step C: Identify items to DELETE
            # Current items that were NOT matched by the new plan
            to_delete_ids = [item['id'] for item in active_items if item['id'] not in matched_current_ids]

            # 5. Execute in Mealie
            if progress_callback:
                progress_callback("Writing changes to Mealie...", 99)

            if to_delete_ids:
                print(f"[Sync] Deleting {len(to_delete_ids)} old items.")
                self.client.delete_shopping_list_items_bulk(to_delete_ids)
            
            if to_update:
                print(f"[Sync] Updating {len(to_update)} existing items (preserving checkmarks).")
                self.client.update_shopping_list_items_bulk(to_update)
                
            if to_add:
                print(f"[Sync] Adding {len(to_add)} new items.")
                self.client.add_shopping_list_items_bulk(to_add)

            if progress_callback:
                progress_callback("Shopping list sync complete!", 100)
            return True
            
        except Exception as e:
            print(f"Error during AI shopping list sync: {e}")
            if progress_callback:
                progress_callback(f"Error during shopping list sync: {str(e)}", 100)
            return False

def sync_shopping_list(start_date_str, end_date_str, low_staples_ids=[], progress_callback=None, freezer_items=""):
    """Standalone helper to run sync with fresh clients."""
    from .unified_client import UnifiedMealieClient
    from .gemini_client import GeminiClient
    client = UnifiedMealieClient()
    gemini = GeminiClient()
    syncer = ShoppingListSync(client, gemini)
    return syncer.sync_shopping_list(start_date_str, end_date_str, low_staples_ids, progress_callback, freezer_items)
