import requests
from datetime import datetime, timedelta

from .config import (
    RDA, BREAKFAST_PROFILES, LUNCH_LEFTOVER_PROFILE, LUNCH_SANDWICH_PROFILE,
    _RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION, RECIPE_API_KEY
)
from .exceptions import MealieAPIError, SkillParsingError
from .models import RecipeNutritionImputation
from .utils import extract_ingredient_texts

class RecipeNutrition:
    def __init__(self, mealie_client, ai_client):
        self.client = mealie_client
        self.ai = ai_client

    def fetch_nutrition_from_recipe_api(self, recipe_name):
        """Fetch recipe details and nutrition from recipe-api.com using search and get endpoints."""
        if not RECIPE_API_KEY:
            print("[RecipeAPI] RECIPE_API_KEY is not set.")
            return None
        
        headers = {
            "X-API-Key": RECIPE_API_KEY,
            "Accept": "application/json"
        }
        
        try:
            print(f"[RecipeAPI] Searching for recipe: '{recipe_name}'")
            search_url = "https://recipe-api.com/api/v1/recipes"
            params = {"q": recipe_name, "per_page": 1}
            r = requests.get(search_url, headers=headers, params=params, timeout=10)
            r.raise_for_status()
            search_data = r.json()
            
            recipes = search_data.get("data", [])
            if not recipes:
                print(f"[RecipeAPI] No matching recipes found for: '{recipe_name}'")
                return None
                
            recipe_id = recipes[0].get("id")
            if not recipe_id:
                return None
                
            print(f"[RecipeAPI] Fetching full details for recipe ID: {recipe_id}")
            detail_url = f"https://recipe-api.com/api/v1/recipes/{recipe_id}"
            r_detail = requests.get(detail_url, headers=headers, timeout=10)
            r_detail.raise_for_status()
            detail_data = r_detail.json()
            
            recipe_obj = detail_data.get("data", {})
            nutrition = recipe_obj.get("nutrition", {})
            per_serving = nutrition.get("per_serving")
            if not per_serving:
                print(f"[RecipeAPI] No per-serving nutrition details found for: '{recipe_name}'")
                return None
                
            print(f"[RecipeAPI] Successfully retrieved nutrition for: '{recipe_name}'")
            return {
                "calories": str(per_serving.get("calories") or 0.0),
                "proteinContent": str(per_serving.get("protein_g") or 0.0),
                "carbohydrateContent": str(per_serving.get("carbohydrates_g") or 0.0),
                "fatContent": str(per_serving.get("fat_g") or 0.0),
                "fiberContent": str(per_serving.get("fiber_g") or 0.0),
                "sodiumContent": str(per_serving.get("sodium_mg") or 0.0),
                "sugarContent": str(per_serving.get("sugar_g") or 0.0),
                "cholesterolContent": str(per_serving.get("cholesterol_mg") or 0.0)
            }
        except Exception as e:
            print(f"[RecipeAPI] Request to recipe-api.com failed: {e}")
            return None

    def impute_nutrition_with_ai(self, recipe_details):
        """Estimate nutritional values for a recipe missing data, trying Recipe API first, then falling back to AI."""
        # 1. Try Recipe API first
        recipe_name = recipe_details.get('name')
        if recipe_name:
            api_data = self.fetch_nutrition_from_recipe_api(recipe_name)
            if api_data:
                return api_data
                
        # 2. Fallback to Gemini/DeepSeek AI Imputation
        ingredients = extract_ingredient_texts(recipe_details)
        servings = recipe_details.get('recipeServings') or recipe_details.get('recipeYield') or '4'
        description = recipe_details.get('description') or ''
        
        prompt = (
            """You are an expert in the 'Recipe Nutrition Imputation Skill'.

""" +
            _RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION +
            """

### CONTEXT FOR THIS INVOCATION:
""" +
            f"Recipe Name: {recipe_name}\n" +
            f"Description: {description}\n" +
            f"Servings: {servings}\n" +
            f"Ingredients: {', '.join(ingredients)}\n\n" +
            "Return ONLY the JSON object as specified in the skill definition."
        )

        try:
            raw = self.ai.call(prompt, response_schema=RecipeNutritionImputation)
            return RecipeNutritionImputation.model_validate_json(raw).model_dump()
        except Exception as e:
            print(f"[AI] Nutrition imputation failed: {e}")
            return None

    def calculate_nutrition_for_range(self, start_date_str, end_date_str):
        """Calculate aggregate and daily nutritional totals for a date range."""
        try:
            meal_plans = self.client.get_meal_plan(start_date_str, end_date_str)
        except MealieAPIError as e:
            print(f"Error fetching meal plans for nutrition: {e}")
            return {}, {}

        # Initialize tracking dicts
        daily_nutrients = {}
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        
        curr = start_date
        while curr <= end_date:
            daily_nutrients[curr.strftime("%Y-%m-%d")] = {k: 0.0 for k in RDA.keys()}
            curr += timedelta(days=1)

        category_totals = {
            "breakfast": {k: 0.0 for k in RDA.keys()},
            "lunch": {k: 0.0 for k in RDA.keys()},
            "dinner": {k: 0.0 for k in RDA.keys()}
        }
        category_counts = {"breakfast": 0, "lunch": 0, "dinner": 0}

        for item in meal_plans:
            # Normalize date to YYYY-MM-DD
            d_str = item['date'][:10]
            if d_str not in daily_nutrients:
                continue
                
            entry_type = item['entryType']
            title = item.get('title') or ""
            recipe_id = item.get('recipeId')
            
            nut_data = None
            
            # 1. Process Breakfasts
            if entry_type == "breakfast":
                nut_data = BREAKFAST_PROFILES.get(title)
                if nut_data:
                    category_counts["breakfast"] += 1
            
            # 2. Process Lunches
            elif entry_type == "lunch":
                if "leftover" in title.lower():
                    nut_data = LUNCH_LEFTOVER_PROFILE
                    category_counts["lunch"] += 1
                elif "sandwich" in title.lower() or "pb&j" in title.lower():
                    nut_data = LUNCH_SANDWICH_PROFILE
                    category_counts["lunch"] += 1

            # 3. Process Dinners
            elif entry_type == "dinner" and recipe_id:
                try:
                    r = self.client.get_recipe_details(recipe_id)
                    # Check if nutrition is missing
                    has_nut = r.get('nutrition') and r['nutrition'].get('calories')
                    
                    if not has_nut:
                        print(f"[Nutrition] Imputing missing data for: {r['name']}")
                        imputed = self.impute_nutrition_with_ai(r)
                        if imputed:
                            nut_data = {
                                "calories": float(imputed.get('calories') or 0),
                                "protein": float(imputed.get('proteinContent') or 0),
                                "carbs": float(imputed.get('carbohydrateContent') or 0),
                                "fat": float(imputed.get('fatContent') or 0),
                                "fiber": float(imputed.get('fiberContent') or 0),
                                "sodium": float(imputed.get('sodiumContent') or 0),
                                "sugar": float(imputed.get('sugarContent') or 0),
                                "cholesterol": float(imputed.get('cholesterolContent') or 0)
                            }
                            
                            # Save back to Mealie database via PATCH to avoid future imputations
                            try:
                                slug = r.get('slug')
                                if slug:
                                    patch_payload = {
                                        "nutrition": {
                                            "calories": imputed.get("calories"),
                                            "proteinContent": imputed.get("proteinContent"),
                                            "carbohydrateContent": imputed.get("carbohydrateContent"),
                                            "fatContent": imputed.get("fatContent"),
                                            "fiberContent": imputed.get("fiberContent"),
                                            "sodiumContent": imputed.get("sodiumContent"),
                                            "sugarContent": imputed.get("sugarContent"),
                                            "cholesterolContent": imputed.get("cholesterolContent")
                                        }
                                    }
                                    self.client.patch_recipe(slug, patch_payload)
                                    print(f"[Nutrition] Saved imputed nutrition back to Mealie for recipe: {r['name']}")
                                    
                                    # Update local client details cache too
                                    r_id = r.get('id')
                                    if r_id and r_id in self.client._recipe_details_cache:
                                        self.client._recipe_details_cache[r_id]['nutrition'] = patch_payload["nutrition"]
                                    if slug and slug in self.client._recipe_details_cache:
                                        self.client._recipe_details_cache[slug]['nutrition'] = patch_payload["nutrition"]
                            except Exception as patch_err:
                                print(f"[Nutrition] Failed to save imputed nutrition back to Mealie: {patch_err}")
                    else:
                        raw_nut = r['nutrition']
                        # Standard Mealie keys: calories, proteinContent, fatContent, carbohydrateContent, fiberContent, sodiumContent, sugarContent, cholesterolContent
                        nut_data = {
                            "calories": float(raw_nut.get('calories') or 0),
                            "protein": float(raw_nut.get('proteinContent') or 0),
                            "carbs": float(raw_nut.get('carbohydrateContent') or 0),
                            "fat": float(raw_nut.get('fatContent') or 0),
                            "fiber": float(raw_nut.get('fiberContent') or 0),
                            "sodium": float(raw_nut.get('sodiumContent') or 0),
                            "sugar": float(raw_nut.get('sugarContent') or 0),
                            "cholesterol": float(raw_nut.get('cholesterolContent') or 0)
                        }
                    
                    if nut_data:
                        category_counts["dinner"] += 1
                        
                except Exception as e:
                    print(f"Error processing dinner nutrition for {recipe_id}: {e}")

            # Add to daily and category totals
            if nut_data:
                for k in RDA.keys():
                    val = float(nut_data.get(k, 0))
                    daily_nutrients[d_str][k] += val
                    category_totals[entry_type][k] += val

        # Calculate averages (weighted by days active)
        averages = {}
        for k in RDA.keys():
            avg_bf = (category_totals["breakfast"][k] / category_counts["breakfast"]) if category_counts["breakfast"] > 0 else 0.0
            avg_ln = (category_totals["lunch"][k] / category_counts["lunch"]) if category_counts["lunch"] > 0 else 0.0
            avg_dn = (category_totals["dinner"][k] / category_counts["dinner"]) if category_counts["dinner"] > 0 else 0.0
            
            averages[k] = round(avg_bf + avg_ln + avg_dn, 1)
            
        return daily_nutrients, averages

def calculate_nutrition_for_range(start_date_str, end_date_str):
    """Standalone helper to run nutrition calculation with fresh clients."""
    from .unified_client import UnifiedMealieClient
    from .ai_client import AIClient
    client = UnifiedMealieClient()
    ai = AIClient()
    nutrition = RecipeNutrition(client, ai)
    return nutrition.calculate_nutrition_for_range(start_date_str, end_date_str)
