"""The plan-signature cache that avoids re-running nutrition imputation on unchanged weeks."""
import unittest
from unittest.mock import MagicMock

from mealie_planner.recipe_nutrition import RecipeNutrition


def _dinner_plan(recipe_id="r1", date="2030-01-01"):
    return {"id": "e1", "date": date, "entryType": "dinner", "recipeId": recipe_id, "title": ""}


class TestNutritionCache(unittest.TestCase):

    def _make_nutrition(self, plans):
        client = MagicMock()
        client.get_meal_plan.return_value = plans
        # Recipe already carries recipe-api-sourced nutrition -> no AI needed
        client.get_recipe_details.return_value = {
            "name": "Tacos", "slug": "tacos",
            "extras": {"nutrition_source": "recipe-api"},
            "nutrition": {"calories": "500", "proteinContent": "30", "carbohydrateContent": "40",
                          "fatContent": "20", "fiberContent": "6", "sodiumContent": "800",
                          "sugarContent": "4", "cholesterolContent": "60"},
        }
        return RecipeNutrition(client, MagicMock()), client

    def test_second_call_with_unchanged_plan_uses_cache(self):
        nutrition, client = self._make_nutrition([_dinner_plan(date="2030-01-01")])

        first = nutrition.calculate_nutrition_for_range("2030-01-01", "2030-01-01")
        calls_after_first = client.get_recipe_details.call_count
        second = nutrition.calculate_nutrition_for_range("2030-01-01", "2030-01-01")

        self.assertEqual(first, second)
        self.assertEqual(client.get_recipe_details.call_count, calls_after_first)

    def test_changed_plan_invalidates_cache(self):
        nutrition, client = self._make_nutrition([_dinner_plan(date="2030-02-01")])
        nutrition.calculate_nutrition_for_range("2030-02-01", "2030-02-01")
        calls_after_first = client.get_recipe_details.call_count

        # Swap the dinner to a different recipe -> signature changes -> recompute
        client.get_meal_plan.return_value = [_dinner_plan(recipe_id="r2", date="2030-02-01")]
        nutrition.calculate_nutrition_for_range("2030-02-01", "2030-02-01")
        self.assertGreater(client.get_recipe_details.call_count, calls_after_first)

    def test_cached_result_not_poisoned_by_caller_mutation(self):
        nutrition, _ = self._make_nutrition([_dinner_plan(date="2030-03-01")])
        daily, averages = nutrition.calculate_nutrition_for_range("2030-03-01", "2030-03-01")
        original_calories = daily["2030-03-01"]["calories"]
        daily["2030-03-01"]["calories"] = -999
        averages["calories"] = -999

        daily2, averages2 = nutrition.calculate_nutrition_for_range("2030-03-01", "2030-03-01")
        self.assertEqual(daily2["2030-03-01"]["calories"], original_calories)
        self.assertNotEqual(averages2["calories"], -999)


if __name__ == "__main__":
    unittest.main()
