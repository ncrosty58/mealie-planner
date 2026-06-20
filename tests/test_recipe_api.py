import unittest
from unittest.mock import patch, MagicMock
import requests
from mealie_planner.recipe_nutrition import RecipeNutrition

class TestRecipeAPIIntegration(unittest.TestCase):

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_ai = MagicMock()
        self.nutrition = RecipeNutrition(self.mock_client, self.mock_ai)

    @patch("mealie_planner.recipe_nutrition.RECIPE_API_KEY", None)
    def test_impute_nutrition_no_api_key_falls_back_to_ai(self):
        recipe_details = {"name": "Tacos", "ingredients": [], "recipeServings": "4"}
        
        # Mock AI response
        self.mock_ai.call.return_value = (
            '{"calories": "400", "proteinContent": "25", "carbohydrateContent": "30", '
            '"fatContent": "15", "fiberContent": "5", "sodiumContent": "400", '
            '"sugarContent": "2", "cholesterolContent": "50"}'
        )

        result = self.nutrition.impute_nutrition_with_ai(recipe_details)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["calories"], "400")
        self.assertEqual(result["proteinContent"], "25")
        # Ensure AI call was made
        self.assertTrue(self.mock_ai.call.called)

    @patch("mealie_planner.recipe_nutrition.RECIPE_API_KEY", "rapi_test_key")
    @patch("requests.get")
    def test_impute_nutrition_with_api_success(self, mock_get):
        recipe_details = {"name": "Texas Chili", "ingredients": [], "recipeServings": "4"}
        
        # Mock search response
        mock_search_res = MagicMock()
        mock_search_res.json.return_value = {
            "data": [{"id": "chili-uuid-123", "name": "Texas Chili con Carne"}]
        }
        mock_search_res.raise_for_status = MagicMock()
        
        # Mock details response
        mock_detail_res = MagicMock()
        mock_detail_res.json.return_value = {
            "data": {
                "id": "chili-uuid-123",
                "nutrition": {
                    "per_serving": {
                        "calories": 569.0,
                        "protein_g": 44.0,
                        "carbohydrates_g": 5.0,
                        "fat_g": 42.0,
                        "fiber_g": 2.0,
                        "sodium_mg": 350.0,
                        "sugar_g": 1.8,
                        "cholesterol_mg": 154.0
                    }
                }
            }
        }
        mock_detail_res.raise_for_status = MagicMock()
        
        mock_get.side_effect = [mock_search_res, mock_detail_res]
        
        result = self.nutrition.impute_nutrition_with_ai(recipe_details)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["calories"], "569.0")
        self.assertEqual(result["proteinContent"], "44.0")
        self.assertEqual(result["carbohydrateContent"], "5.0")
        self.assertEqual(result["sodiumContent"], "350.0")
        
        # Ensure AI call was NOT made
        self.assertFalse(self.mock_ai.call.called)

    @patch("mealie_planner.recipe_nutrition.RECIPE_API_KEY", "rapi_test_key")
    @patch("requests.get")
    def test_impute_nutrition_api_empty_data_falls_back_to_ai(self, mock_get):
        recipe_details = {"name": "Strange Unknown Dish", "ingredients": [], "recipeServings": "4"}
        
        # Mock search response with no results
        mock_search_res = MagicMock()
        mock_search_res.json.return_value = {"data": []}
        mock_search_res.raise_for_status = MagicMock()
        mock_get.return_value = mock_search_res
        
        # Mock AI response
        self.mock_ai.call.return_value = (
            '{"calories": "300", "proteinContent": "10", "carbohydrateContent": "40", '
            '"fatContent": "10", "fiberContent": "2", "sodiumContent": "500", '
            '"sugarContent": "5", "cholesterolContent": "10"}'
        )
        
        result = self.nutrition.impute_nutrition_with_ai(recipe_details)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["calories"], "300")
        # Ensure AI call was made as a fallback
        self.assertTrue(self.mock_ai.call.called)

    @patch("mealie_planner.recipe_nutrition.RECIPE_API_KEY", "rapi_test_key")
    @patch("requests.get")
    def test_impute_nutrition_api_failure_falls_back_to_ai(self, mock_get):
        recipe_details = {"name": "Error Dish", "ingredients": [], "recipeServings": "4"}
        
        # Simulate connection error
        mock_get.side_effect = requests.RequestException("Connection timeout")
        
        # Mock AI response
        self.mock_ai.call.return_value = (
            '{"calories": "200", "proteinContent": "15", "carbohydrateContent": "20", '
            '"fatContent": "5", "fiberContent": "1", "sodiumContent": "300", '
            '"sugarContent": "1", "cholesterolContent": "5"}'
        )
        
        result = self.nutrition.impute_nutrition_with_ai(recipe_details)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["calories"], "200")
        # Ensure AI call was made as a fallback
        self.assertTrue(self.mock_ai.call.called)
