import time
import json
import re

from .config import (
    ACTIVE_LIST_ID, STAPLES_LIST_ID, FAMILY_DIETARY_RULES_PROMPT,
    _SHOPPING_LIST_SYNC_SKILL_DEFINITION
)
from .recipe_crawler import RecipeCrawler
from .exceptions import MealieAPIError, SkillParsingError
from .models import CompiledShoppingList, CompiledShoppingListWrapper

def normalize_ingredient_name(name: str) -> str:
    """Normalize ingredient name for matching by stripping quantity, unit, descriptors, and organic tag."""
    name = name.lower().strip()
    name = re.sub(r'\(buy organic\)', '', name).strip()
    name = re.sub(r'\b(fresh|frozen|canned|organic|raw|cooked)\b', '', name).strip()
    # Remove leading quantity/unit e.g. "2 lbs ", "1/2 cup ", "3 cloves "
    name = re.sub(r'^[\d\/\s\.\-]+(lbs?|oz|cups?|cans?|cloves?|tsps?|tbsps?|g|kg|ml|l|packages?|bags?|pieces?|slices?)\b', '', name).strip()
    # Remove leading digits and remaining spaces
    name = re.sub(r'^[\d\/\s\.\-]+', '', name).strip()
    # Normalize multiple consecutive spaces to a single space
    name = re.sub(r'\s+', ' ', name).strip()
    return name

class ShoppingListSync:
    def __init__(self, mealie_client, ai_client, crawler):
        self.client = mealie_client
        self.ai = ai_client
        self.crawler = crawler

    def sync_staples_only(self, low_staples_ids) -> bool:
        """Fast, deterministic sync of staples only. No AI, no clearing of recipes."""
        print("[Sync] Performing fast staples-only update...")
        try:
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            active_items = self.client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
            low_ids_clean = {s_id.replace('-', '').lower() for s_id in low_staples_ids}
            staple_names = {normalize_ingredient_name(s['note']): s for s in staples}
            
            active_staple_notes = []
            active_notes_set = set()
            for item in active_items:
                note_norm = normalize_ingredient_name(item['note'])
                active_notes_set.add(note_norm)
                if note_norm in staple_names:
                    active_staple_notes.append(item)

            to_add = []
            for s in staples:
                s_norm = normalize_ingredient_name(s['note'])
                if s['id'].replace('-', '').lower() in low_ids_clean:
                    if s_norm not in active_notes_set:
                        to_add.append({
                            "shoppingListId": ACTIVE_LIST_ID,
                            "note": s['note'],
                            "quantity": s.get('quantity', 1.0),
                            "checked": False,
                            "labelId": s.get('labelId'),
                            "extras": {"is_synced": True}
                        })

            to_delete_ids = []
            for item in active_staple_notes:
                item_norm = normalize_ingredient_name(item['note'])
                master_staple = staple_names.get(item_norm)
                if master_staple:
                    m_id = master_staple['id'].replace('-', '').lower()
                    if m_id not in low_ids_clean:
                        to_delete_ids.append(item['id'])

            if to_delete_ids: self.client.delete_shopping_list_items_bulk(to_delete_ids)
            if to_add: self.client.add_shopping_list_items_bulk(to_add)
            return True
        except Exception as e:
            print(f"Error during fast staples sync: {e}")
            return False

    def sync_shopping_list(self, start_date_str, end_date_str, low_staples_ids=[], progress_callback=None, freezer_items="") -> bool:
        """Non-destructive sync using AI to perform semantic matching and checkmark/ID retention."""
        print(f"Starting non-destructive sync for {start_date_str} to {end_date_str}...")
        if progress_callback: progress_callback("Sync started...", 90)
        
        try:
            time.sleep(1.0)
            
            # Invalidate cached recipes to ensure we fetch fresh ingredients from Mealie
            if hasattr(self.client, 'invalidate_recipe_cache'):
                self.client.invalidate_recipe_cache()
            
            # 1. Fetch current data
            meal_plans = self.client.get_meal_plan(start_date_str, end_date_str)
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            active_items = self.client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
            
            low_ids_clean = {sid.replace('-', '').lower() for sid in low_staples_ids}
            low_staples_notes = [s['note'] for s in staples if s['id'].replace('-', '').lower() in low_ids_clean]

            # 2. Extract ingredients from scheduled recipes
            if progress_callback: progress_callback("Analyzing current progress...", 93)
            recipe_ids_to_fetch = set()
            meal_plan_mapping = []
            all_recipes_overview = self.crawler.get_recipes_from_db()
            
            for p in meal_plans:
                rid = p.get('recipeId')
                title = p.get('title') or ""
                if not rid and title:
                    if title.lower().strip() not in {"leftovers", "pb&j sandwich", "eating out", "skipped", "cereal & milk", "oats", "planned meal", "planned dinner"}:
                        rid = self.crawler.find_recipe_for_ingredient(title, all_recipes=all_recipes_overview)
                if rid: recipe_ids_to_fetch.add(rid)
                meal_plan_mapping.append((p, rid))

            print(f"[Sync] Bulk fetching details for {len(recipe_ids_to_fetch)} unique recipes.")
            details_map = self.client.get_recipes_details_bulk(list(recipe_ids_to_fetch))

            raw_recipe_ingredients = []
            for _, rid in meal_plan_mapping:
                if rid and rid in details_map:
                    r_details = details_map[rid]
                    if r_details:
                        for ing in r_details.get('recipeIngredient', []):
                            txt = ing.get('display') or ing.get('originalText') or ""
                            if txt.strip(): raw_recipe_ingredients.append(txt.strip())

            # 3. Call AI Skill
            if progress_callback: progress_callback("Generating optimized list...", 96)
            
            all_labels = self.client.get_labels()
            label_name_to_id = {l['name']: l['id'] for l in all_labels}

            manual_items = []
            for item in active_items:
                if not item.get('extras', {}).get('is_synced', False):
                    manual_items.append(item['note'])

            payload = {
                "ingredients": raw_recipe_ingredients,
                "staples": [s['note'] for s in staples],
                "inventory_items": [i.strip() for i in re.split(r'[,\n]+', freezer_items) if i.strip()] if freezer_items else [],
                "low_staples": low_staples_notes,
                "manual_items": manual_items,
                "available_labels": [l['name'] for l in all_labels],
                "active_shopping_list": [
                    {
                        "index": idx,
                        "note": item["note"],
                        "checked": item.get("checked", False)
                    }
                    for idx, item in enumerate(active_items)
                ]
            }
            
            prompt = (
                "You are an expert in the 'Shopping List Sync Skill'.\n\n" +
                _SHOPPING_LIST_SYNC_SKILL_DEFINITION +
                "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
                f"Payload: {json.dumps(payload)}\n" +
                f"Family Dietary Rules: {FAMILY_DIETARY_RULES_PROMPT}\n\n" +
                "Return ONLY a JSON object with a single key 'items' whose value is the JSON array of objects as specified in the skill definition. Example: {\"items\": [...]}"
            )
            ai_response = self.ai.call(prompt, response_schema=CompiledShoppingListWrapper)
            wrapper = CompiledShoppingListWrapper.model_validate_json(ai_response)
            final_items = [item.model_dump() for item in wrapper.items]

            # 4. Merge changes in Mealie
            if progress_callback: progress_callback("Merging changes...", 98)
            
            to_add, to_update, matched_ids = [], [], set()

            for idx, ai_item in enumerate(final_items):
                active_idx = ai_item.get('active_item_index')
                name = ai_item.get('name', 'Unknown')
                qty = ai_item.get('quantity', 1.0)
                unit = ai_item.get('unit') or ''
                checked = ai_item.get('checked', False)
                cat_name = ai_item.get('category')
                
                if unit.lower().strip() in {'default', 'unit', 'none', 'null'}:
                    unit = ''
                
                full_note = f"{unit.strip()} {name}".strip() if unit else name
                label_id = label_name_to_id.get(cat_name)

                original = None
                if active_idx is not None:
                    try:
                        active_idx = int(active_idx)
                        if 0 <= active_idx < len(active_items):
                            candidate = active_items[active_idx]
                            if candidate['id'] not in matched_ids:
                                original = candidate
                    except (ValueError, TypeError):
                        pass

                if not original:
                    # Fallback semantic name matching
                    name_norm = normalize_ingredient_name(name)
                    for item in active_items:
                        if item['id'] not in matched_ids:
                            if normalize_ingredient_name(item['note']) == name_norm:
                                original = item
                                break

                if original:
                    matched_ids.add(original['id'])
                    is_manual = not original.get('extras', {}).get('is_synced', False)
                    updated = original.copy()
                    updated.update({
                        "note": full_note,
                        "quantity": qty,
                        "checked": checked,
                        "labelId": label_id if not is_manual else (original.get('labelId') or label_id),
                        "extras": {} if is_manual else {"is_synced": True}
                    })
                    to_update.append(updated)
                else:
                    to_add.append({
                        "shoppingListId": ACTIVE_LIST_ID,
                        "note": full_note,
                        "quantity": qty,
                        "checked": checked,
                        "labelId": label_id,
                        "position": idx,
                        "extras": {"is_synced": True}
                    })

            to_delete = []
            low_staples_norm = {normalize_ingredient_name(note) for note in low_staples_notes}
            for i in active_items:
                if i['id'] not in matched_ids:
                    is_manual = not i.get('extras', {}).get('is_synced', False)
                    i_norm = normalize_ingredient_name(i['note'])
                    is_low_staple = i_norm in low_staples_norm
                    if is_manual:
                        print(f"[Sync] Preserving unmatched manual item: {i['note']}")
                    elif is_low_staple:
                        print(f"[Sync] Preserving unmatched low staple: {i['note']}")
                        # Also add to matched_ids so it isn't processed twice or deleted
                        matched_ids.add(i['id'])
                    else:
                        to_delete.append(i['id'])

            # Ensure all low staples are either matched/updated, added, or kept in the active list
            kept_active_notes_norm = {
                normalize_ingredient_name(item['note'])
                for item in active_items
                if item['id'] not in to_delete
            }
            processed_notes_norm = {normalize_ingredient_name(item['note']) for item in to_update}
            processed_notes_norm.update({normalize_ingredient_name(item['note']) for item in to_add})
            processed_notes_norm.update(kept_active_notes_norm)
            
            for s in staples:
                if s['id'].replace('-', '').lower() in low_ids_clean:
                    s_norm = normalize_ingredient_name(s['note'])
                    if s_norm not in processed_notes_norm:
                        print(f"[Sync] Adding missing low staple in Python: {s['note']}")
                        to_add.append({
                            "shoppingListId": ACTIVE_LIST_ID,
                            "note": s['note'],
                            "quantity": s.get('quantity', 1.0),
                            "checked": False,
                            "labelId": s.get('labelId'),
                            "extras": {"is_synced": True}
                        })

            # 5. Apply changes to Mealie
            if to_delete: self.client.delete_shopping_list_items_bulk(to_delete)
            if to_update: self.client.update_shopping_list_items_bulk(to_update)
            if to_add: self.client.add_shopping_list_items_bulk(to_add)

            if progress_callback: progress_callback("Sync complete!", 100)
            return True
        except Exception as e:
            print(f"Error during AI shopping list sync: {e}")
            if progress_callback: progress_callback(f"Error: {str(e)}", 100)
            return False

def sync_shopping_list(start_date_str, end_date_str, low_staples_ids=[], progress_callback=None, freezer_items=""):
    from .unified_client import UnifiedMealieClient
    from .ai_client import AIClient
    client, ai = UnifiedMealieClient(), AIClient()
    crawler = RecipeCrawler(client, ai)
    return ShoppingListSync(client, ai, crawler).sync_shopping_list(start_date_str, end_date_str, low_staples_ids, progress_callback, freezer_items)
