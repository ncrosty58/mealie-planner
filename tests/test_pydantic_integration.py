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

    @patch("requests.post")
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
        
        # Verify that requests.post was called with the correct generationConfig payload
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

if __name__ == "__main__":
    unittest.main()
