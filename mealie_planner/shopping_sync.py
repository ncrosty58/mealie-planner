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
            
            # Fetch actual labels from Mealie
            all_labels = self.client.get_labels()
            
            # Label Preference Filter: If we have specific names, don't even let the AI see the generic ones.
            # This ensures Mealie saves the data using the "clean" labels.
            PREFERENCE_MAP = {
                "Vegetables & Greens": ["1. Produce", "Produce"],
                "Fruits": ["1. Produce", "Produce"],
                "Mushrooms": ["1. Produce", "Produce"],
                "Herbs & Spices": ["1. Produce", "Produce", "6. Baking, Spices & Condiments", "6. Baking, Spices, Oils & Condiments"],
                "Bakery": ["2. Bakery"],
                "Bread & Salty Snacks": ["2. Bakery"],
                "Meats": ["3. Meat, Seafood & Vegetarian Alternatives", "Meat", "3. Meat & Seafood"],
                "Poultry": ["3. Meat, Seafood & Vegetarian Alternatives", "Meat", "3. Meat & Seafood"],
                "Fish": ["3. Meat, Seafood & Vegetarian Alternatives", "Meat", "3. Meat & Seafood"],
                "Seafood & Seaweed": ["3. Meat, Seafood & Vegetarian Alternatives", "Meat", "3. Meat & Seafood"],
                "Dairy & Eggs": ["4. Dairy, Cheese & Eggs", "Dairy"],
                "Cheese": ["4. Dairy, Cheese & Eggs", "Dairy"],
                "Pantry": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Grains & Cereals": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Pasta": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Canned Food": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Soups, Stews & stock": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Legumes": ["5. Pantry / Center Aisle Grains & Canned Goods"],
                "Baking": ["6. Baking, Spices, Oils & Condiments", "6. Baking, Spices & Condiments"],
                "Oils & Fats": ["6. Baking, Spices, Oils & Condiments", "6. Baking, Spices & Condiments"],
                "Seasonings & Spice Blends": ["6. Baking, Spices, Oils & Condiments", "6. Baking, Spices & Condiments"],
                "Sugar & Sweeteners": ["6. Baking, Spices, Oils & Condiments", "6. Baking, Spices & Condiments"],
                "Condiments": ["6. Baking, Spices, Oils & Condiments", "6. Baking, Spices & Condiments"],
                "Frozen Foods": ["7. Frozen Foods"],
                "Beverages": ["8. Beverages"],
                "Wine, Beer & Spirits": ["8. Beverages"]
            }

            label_names = {l['name'] for l in all_labels}
            labels_to_suppress = set()
            for preferred, generics in PREFERENCE_MAP.items():
                if preferred in label_names:
                    labels_to_suppress.update(generics)
            
            filtered_labels = [l for l in all_labels if l['name'] not in labels_to_suppress]
            available_label_names = [l['name'] for l in filtered_labels]
            label_name_to_id = {l['name']: l['id'] for l in filtered_labels}

            payload = {
                "ingredients": raw_recipe_ingredients,
                "staples": staples_notes,
                "inventory_items": inventory_items,
                "low_staples": low_staples_notes,
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
            
            print(f"--- AI SHOPPING LIST SYNC PROMPT ({len(available_label_names)} labels) ---")
            ai_response = self.gemini.call(prompt, expect_json=True)
            
            try:
                final_items = json.loads(ai_response)
                if not isinstance(final_items, list):
                    raise SkillParsingError("AI did not return a list for shopping list sync")
            except Exception as e:
                raise SkillParsingError(f"Failed to parse AI response: {e}")

            # 4. Write to Mealie
            if progress_callback:
                progress_callback("Writing items to Mealie shopping list...", 98)
            
            print(f"[Sync] Final list has {len(final_items)} items. Clearing active list and writing bulk.")
            
            self.client.clear_shopping_list(ACTIVE_LIST_ID)
            
            ingredients_list = []
            for idx, item in enumerate(final_items):
                name = item.get('name', 'Unknown Item')
                qty = item.get('quantity', 1.0)
                unit = item.get('unit') or ''
                unit = unit.strip()
                
                # AI returns the label name from our filtered list
                category_name = item.get('category')
                label_id = label_name_to_id.get(category_name) if category_name else None
                
                # For ingredients, include the unit in the note (e.g. "1 lb Chicken Breast")
                full_note = f"{unit} {name}".strip() if unit else name
                
                ingredients_list.append({
                    "shoppingListId": ACTIVE_LIST_ID,
                    "note": full_note,
                    "quantity": qty,
                    "checked": False,
                    "position": idx,
                    "labelId": label_id
                })
                
            self.client.add_shopping_list_items_bulk(ingredients_list)
            
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

