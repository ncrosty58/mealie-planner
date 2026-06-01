import unittest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from mealie_planner.gemini_client import GeminiClient
from mealie_planner.models import (
    ParsedIngredientList,
    MealExclusions,
    WeeklyMealPlanResponse,
    RecipeNutritionImputation,
    CompiledShoppingItem,
    CompiledShoppingList,
    StandardizedIngredients,
)
from mealie_planner.parsers import parse_freezer_items, parse_exclusions

class TestPydanticIntegration(unittest.TestCase):

    def test_parsed_ingredient_list(self):
        valid_json = '[{"raw": "1lb beef", "core_ingredient": "beef", "has_meat": true}]'
        parsed = ParsedIngredientList.model_validate_json(valid_json).root
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].raw, "1lb beef")
        self.assertEqual(parsed[0].has_meat, True)
        
        # Invalid payload should raise ValidationError
        invalid_json = '[{"raw": "1lb beef", "has_meat": "not_a_boolean"}]'
        with self.assertRaises(ValidationError):
            ParsedIngredientList.model_validate_json(invalid_json)

    def test_meal_exclusions(self):
        valid_json = '{"Monday": ["dinner"], "Tuesday": ["breakfast", "lunch"]}'
        exclusions = MealExclusions.model_validate_json(valid_json).root
        self.assertEqual(exclusions["Monday"], ["dinner"])
        self.assertEqual(exclusions["Tuesday"], ["breakfast", "lunch"])
        
        # Invalid day should raise ValidationError
        invalid_json = '{"NotADay": ["dinner"]}'
        with self.assertRaises(ValidationError):
            MealExclusions.model_validate_json(invalid_json)

    def test_weekly_meal_plan_response(self):
        valid_json = """{
            "days": [
                {
                    "date": "2026-05-30",
                    "meals": {
                        "breakfast": "Oats",
                        "lunch": "Leftovers",
                        "dinner": "some-uuid",
                        "prep_note": "Batch cook veggies"
                    }
                }
            ]
        }"""
        response = WeeklyMealPlanResponse.model_validate_json(valid_json)
        self.assertEqual(len(response.days), 1)
        self.assertEqual(response.days[0].date, "2026-05-30")
        self.assertEqual(response.days[0].meals.dinner, "some-uuid")

    def test_recipe_nutrition_imputation(self):
        valid_json = """{
            "calories": "350",
            "proteinContent": "23",
            "carbohydrateContent": "48",
            "fatContent": "9",
            "fiberContent": "20",
            "sodiumContent": "650",
            "sugarContent": "5",
            "cholesterolContent": "0"
        }"""
        imputation = RecipeNutritionImputation.model_validate_json(valid_json)
        self.assertEqual(imputation.calories, "350")
        self.assertEqual(imputation.fiberContent, "20")

    def test_compiled_shopping_list(self):
        valid_json = """[
            {
                "active_item_index": 1,
                "name": "Spinach",
                "quantity": 2.5,
                "unit": "oz",
                "checked": false,
                "category": "Produce"
            }
        ]"""
        shopping_list = CompiledShoppingList.model_validate_json(valid_json).root
        self.assertEqual(len(shopping_list), 1)
        self.assertEqual(shopping_list[0].name, "Spinach")
        self.assertEqual(shopping_list[0].active_item_index, 1)

    def test_standardize_ingredients(self):
        valid_json = '["2 lbs Chicken Breast", "1 cup White Rice"]'
        ingredients = StandardizedIngredients.model_validate_json(valid_json).root
        self.assertEqual(ingredients, ["2 lbs Chicken Breast", "1 cup White Rice"])

    @patch("requests.Session.post")
    def test_gemini_client_payload_construction(self, mock_post):
        # Configure mock response
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "responseId": "test-id",
            "candidates": [{
                "content": {
                    "parts": [{"text": "[]"}]
                }
            }]
        }
        mock_post.return_value = mock_resp
        
        client = GeminiClient(api_key="dummy_key")
        
        # Call with Pydantic model
        client.call("Test prompt", response_schema=ParsedIngredientList)
        
        # Verify that requests.Session.post was called with the correct generationConfig payload
        self.assertTrue(mock_post.called)
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        
        generation_config = payload["generationConfig"]
        self.assertEqual(generation_config["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", generation_config)
        
        schema = generation_config["responseJsonSchema"]
        self.assertEqual(schema["type"], "array")
        # Verify the raw JSON schema is passed directly (including $defs)
        self.assertIn("$defs", schema)

    @patch("mealie_planner.gemini_client.GeminiClient.call")
    def test_check_blackstone_compatibility(self, mock_gemini_call):
        import os
        old_key = os.environ.get("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = "dummy_key"
        try:
            from mealie_planner.recipe_crawler import check_blackstone_compatibility
            
            # Test Case 1: Fast-path via name keyword
            recipe_griddle = {"name": "Smashed Griddle Burgers", "recipeInstructions": []}
            self.assertTrue(check_blackstone_compatibility(recipe_griddle))
            
            # Test Case 2: Fast-path via instructions keyword
            recipe_instructions = {"name": "Stir Fry", "recipeInstructions": [{"text": "Cook on the Blackstone griddle"}]}
            self.assertTrue(check_blackstone_compatibility(recipe_instructions))
            
            # Test Case 3: AI Fallback returning YES
            recipe_ai_yes = {"name": "Fajitas", "recipeInstructions": [{"text": "Sear chicken and peppers on a flat pan"}]}
            mock_gemini_call.return_value = "YES"
            self.assertTrue(check_blackstone_compatibility(recipe_ai_yes))
            mock_gemini_call.assert_called_once()
            
            # Test Case 4: AI Fallback returning NO
            mock_gemini_call.reset_mock()
            recipe_ai_no = {"name": "Slow Cooker Beef Stew", "recipeInstructions": [{"text": "Simmer in a slow cooker for 8 hours"}]}
            mock_gemini_call.value = "NO"
            mock_gemini_call.return_value = "NO"
            self.assertFalse(check_blackstone_compatibility(recipe_ai_no))
            mock_gemini_call.assert_called_once()
        finally:
            if old_key is not None:
                os.environ["GOOGLE_API_KEY"] = old_key
            else:
                os.environ.pop("GOOGLE_API_KEY", None)

    def test_normalize_ingredient_name_spacing(self):
        from mealie_planner.shopping_sync import normalize_ingredient_name
        # Test double space normalization
        self.assertEqual(normalize_ingredient_name("fresh red onion"), "red onion")
        self.assertEqual(normalize_ingredient_name("chicken raw breast"), "chicken breast")
        self.assertEqual(normalize_ingredient_name("3 cloves   garlic"), "garlic")
        self.assertEqual(normalize_ingredient_name("1/2 cup organic spinach"), "spinach")

    @patch("httpx.Client")
    def test_unified_mealie_client_singleton(self, mock_httpx_client):
        # Configure mock get request inside MealieClient initialization connection check
        mock_client_instance = MagicMock()
        mock_httpx_client.return_value = mock_client_instance
        
        from mealie_planner.unified_client import UnifiedMealieClient
        
        # Reset singleton state for testing
        UnifiedMealieClient._instance = None
        
        # Instantiate twice
        c1 = UnifiedMealieClient(base_url="http://mock-mealie", api_key="dummy-key")
        c2 = UnifiedMealieClient(base_url="http://mock-mealie", api_key="dummy-key")
        
        # Assert they are the exact same instance
        self.assertIs(c1, c2)
        # Assert connection test get was called only once
        self.assertEqual(mock_client_instance.get.call_count, 1)

if __name__ == "__main__":
    unittest.main()
