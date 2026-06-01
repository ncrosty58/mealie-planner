import json
import requests
from datetime import datetime, timedelta

from .config import (
    RDA, BREAKFAST_PROFILES, LUNCH_LEFTOVER_PROFILE, LUNCH_SANDWICH_PROFILE,
    _RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION
)
from .exceptions import MealieAPIError, SkillParsingError
from .models import RecipeNutritionImputation

class RecipeNutrition:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client

    def impute_nutrition_with_ai(self, recipe_details):
        """Call Gemini to estimate nutritional values for a recipe missing data."""
        ingredients = []
        for ing in recipe_details.get('recipeIngredient', []):
            ing_text = ing.get('display') or ing.get('originalText')
            if not ing_text:
                note = ing.get('note') or ""
                food_name = ing.get('food', {}).get('name') if ing.get('food') else ""
                quantity = ing.get('quantity') or ""
                unit = ing.get('unit', {}).get('name') if ing.get('unit') else ""
                ing_text = f"{quantity} {unit} {food_name} {note}".strip()
            if ing_text:
                ingredients.append(ing_text)
        
        servings = recipe_details.get('recipeServings') or recipe_details.get('recipeYield') or '4'
        description = recipe_details.get('description') or ''
        
        prompt = (
            """You are an expert in the 'Recipe Nutrition Imputation Skill'.

""" +
            _RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION +
            """

### CONTEXT FOR THIS INVOCATION:
""" +
            f"Recipe Name: {recipe_details.get('name')}\n" +
            f"Description: {description}\n" +
            f"Servings: {servings}\n" +
            f"Ingredients: {', '.join(ingredients)}\n\n" +
            "Return ONLY the JSON object as specified in the skill definition."
        )

        try:
            raw = self.gemini.call(prompt, response_schema=RecipeNutritionImputation)
            result = RecipeNutritionImputation.model_validate_json(raw).model_dump()
            # Basic validation
            for k in RDA.keys():
                if k not in result:
                    result[k] = "0"
            return result
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
                            # Optionally: update Mealie here? For now just use local.
                            nut_data = {k: float(v) for k, v in imputed.items() if v and str(v).replace('.','',1).isdigit()}
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
    from .gemini_client import GeminiClient
    client = UnifiedMealieClient()
    gemini = GeminiClient()
    nutrition = RecipeNutrition(client, gemini)
    return nutrition.calculate_nutrition_for_range(start_date_str, end_date_str)

