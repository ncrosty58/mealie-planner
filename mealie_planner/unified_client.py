import os
import sys
import json
import logging
from typing import List, Dict, Any, Optional

# Add mealie-mcp-server/src to the python path to import MealieFetcher
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
if mcp_src_dir not in sys.path:
    sys.path.insert(0, mcp_src_dir)

from mealie import MealieFetcher

logger = logging.getLogger("mealie-planner-unified")
from .models import StandardizedIngredients
from .config import _INGREDIENT_STANDARDIZATION_SKILL_DEFINITION

_recipe_details_cache = {}

class UnifiedMealieClient(MealieFetcher):
    """
    A unified Mealie client that inherits from the vendored MealieFetcher
    and adds missing or legacy compatibility methods.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(UnifiedMealieClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        if self._initialized:
            return
            
        base_url = base_url or os.getenv('MEALIE_API_URL') or os.getenv('MEALIE_BASE_URL', 'http://mealie:9000')
        api_key = api_key or os.getenv('MEALIE_TOKEN') or os.getenv('MEALIE_API_KEY')
        
        if not api_key:
            raise ValueError("Mealie API Key (MEALIE_TOKEN or MEALIE_API_KEY) is missing.")
            
        super().__init__(base_url=base_url, api_key=api_key)
        self._recipe_details_cache = _recipe_details_cache
        self._initialized = True

    # --- Legacy Compatibility Aliases ---
    
    @property
    def api_url(self):
        """Backwards compatibility for scripts using client.api_url"""
        return self._client.base_url

    @property
    def headers(self):
        """Backwards compatibility for scripts using client.headers"""
        return self._client.headers

    def get_all_recipes(self) -> List[Dict[str, Any]]:
        """Legacy alias for get_recipes(per_page=500)"""
        res = self.get_recipes(per_page=500)
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def get_recipe_details(self, recipe_id_or_slug: str) -> Dict[str, Any]:
        """Fetch full details of a specific recipe, using a local cache."""
        if recipe_id_or_slug in self._recipe_details_cache:
            return self._recipe_details_cache[recipe_id_or_slug]

        details = self.get_recipe(recipe_id_or_slug)
        self._recipe_details_cache[recipe_id_or_slug] = details
        return details

    def get_recipes_details_bulk(self, recipe_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch full details for a list of recipes sequentially to protect server stability."""
        import time
        for rid in recipe_ids:
            if rid not in self._recipe_details_cache:
                try:
                    # Sequential fetch with a small breath to prevent SQLite/Worker locking
                    self.get_recipe_details(rid)
                    time.sleep(0.1) 
                except Exception as e:
                    logger.error(f"Error fetching recipe {rid}: {e}")

        return {rid: self._recipe_details_cache.get(rid) for rid in recipe_ids}

    def get_meal_plan(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Legacy alias for get_mealplans with simplified return."""
        res = self.get_mealplans(start_date=start_date, end_date=end_date, per_page=100)
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def delete_meal_plan_entry(self, entry_id: str):
        """Missing method in MealieFetcher to delete a meal plan entry."""
        return self._handle_request("DELETE", f"/api/households/mealplans/{entry_id}")

    def schedule_meal(self, date_str: str, entry_type: str, recipe_id: Optional[str] = None, title: Optional[str] = None, text: Optional[str] = None):
        """Legacy alias for create_mealplan, adding support for prep notes (text)."""
        payload = {
            "date": date_str,
            "entryType": entry_type,
        }
        if recipe_id:
            payload["recipeId"] = recipe_id
        if title:
            payload["title"] = title
        if text:
            payload["text"] = text
            
        return self._handle_request("POST", "/api/households/mealplans", json=payload)

    def clear_shopping_list(self, list_id: str):
        """Clear all items from a shopping list using targeted fetch."""
        items = self.get_shopping_list_items_legacy(list_id)
        item_ids_to_delete = [item['id'] for item in items if 'id' in item]
        if item_ids_to_delete:
            return self.delete_shopping_list_items_bulk(item_ids_to_delete)
        return {"message": "List already empty"}

    def add_shopping_list_items_bulk(self, items: List[Dict[str, Any]]):
        """Alias for create_shopping_list_items_bulk."""
        return self.create_shopping_list_items_bulk(items)
    
    def get_shopping_list_items(self, *args, **kwargs) -> Any:
        """
        Supports both legacy (list_id as first arg) and new (pagination params) signatures.
        """
        if args and isinstance(args[0], str) and len(args[0]) > 20:
            return self.get_shopping_list_items_legacy(args[0])
        return super().get_shopping_list_items(*args, **kwargs)

    def get_shopping_list_items_for_list(self, list_id: str) -> List[Dict[str, Any]]:
        """Helper to get items specifically for one list."""
        return self.get_shopping_list_items_legacy(list_id)

    def get_shopping_list_items_legacy(self, list_id: str) -> List[Dict[str, Any]]:
        """Fetch all items currently on a shopping list (legacy compatibility)."""
        res = self.get_shopping_list(list_id)
        if isinstance(res, dict):
            return res.get('listItems', [])
        return []

    def get_users(self) -> List[Dict[str, Any]]:
        """Fetch all users (legacy compatibility)."""
        res = self._handle_request("GET", "/api/admin/users")
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def get_labels(self) -> List[Dict[str, Any]]:
        """Fetch all shopping list labels (legacy compatibility)."""
        res = self._handle_request("GET", "/api/groups/labels")
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def create_recipe_from_url(self, url: str) -> Dict[str, Any]:
        """
        Missing method to create a recipe from a URL.
        This uses the Mealie API endpoint directly.
        """
        return self._handle_request("POST", "/api/recipes/create/url", json={"url": url})

    def get_detailed_meal_plan(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Fetches meal plan entries and enriches them with full recipe details 
        (ingredients, instructions, etc.) in a single call.
        """
        plans = self.get_meal_plan(start_date, end_date)
        recipe_ids = list(set(p['recipeId'] for p in plans if p.get('recipeId')))
        
        if not recipe_ids:
            return plans
            
        details_map = self.get_recipes_details_bulk(recipe_ids)
        
        for p in plans:
            rid = p.get('recipeId')
            if rid and rid in details_map:
                p['recipe'] = details_map[rid]
                
        return plans

    def parse_raw_ingredients(self, ingredients: List[str]) -> List[Dict[str, Any]]:
        """Helper to parse a list of ingredients using Mealie's NLP ingredient parser endpoint."""
        try:
            logger.info({"message": "Parsing raw ingredients via Mealie API", "count": len(ingredients)})
            res = self._handle_request("POST", "/api/parser/ingredients", json={
                "ingredients": ingredients
            })
            parsed_ingredients = []
            for item in res:
                if isinstance(item, dict) and "ingredient" in item:
                    parsed_ingredients.append(item["ingredient"])
                else:
                    parsed_ingredients.append({"note": item.get("input") if isinstance(item, dict) else str(item)})
            return parsed_ingredients
        except Exception as e:
            logger.warning({"message": "Failed to parse ingredients via Mealie API, falling back to note field mapping", "error": str(e)})
            return [{"note": i} for i in ingredients]

    def parse_ingredients_with_ai(self, raw_text: str) -> List[Dict[str, Any]]:
        """Parse free-text ingredients using the unified GeminiClient and config definitions."""
        from .gemini_client import GeminiClient
        from .parsers import parse_freezer_items
        
        gemini = GeminiClient()
        return parse_freezer_items(gemini, raw_text)

    def standardize_ingredients_with_ai(self, ingredients: List[str]) -> List[str]:
        """
        Use GeminiClient to clean and standardize a list of ingredient strings.
        Removes brand names, extraneous instructions, and formatting noise.
        """
        from .gemini_client import GeminiClient
        gemini = GeminiClient()
        
        try:
            raw_text = "\n".join(ingredients)
            logger.info({"message": "Standardizing ingredients via Gemini AI", "count": len(ingredients)})
            
            prompt = (
                "You are an expert in the 'Ingredient Standardization Skill'.\n\n" +
                _INGREDIENT_STANDARDIZATION_SKILL_DEFINITION +
                "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
                f"Input List:\n{raw_text}\n\n" +
                "Return ONLY a JSON array of strings."
            )

            ai_response = gemini.call(prompt, response_schema=StandardizedIngredients)
            return StandardizedIngredients.model_validate_json(ai_response).root
        except Exception as e:
            logger.error(f"Error standardizing ingredients with AI: {e}")
            return ingredients
