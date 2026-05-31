import json
from config import load_skill_md

# Import from sub-modules
from gemini_client import call_gemini
from mealie_client import MealieClient
from recipe_nutrition import (
    impute_recipe_nutrition, calculate_nutrition_for_range, parse_nutrient_val
)
from recipe_crawler import (
    find_recipe_for_ingredient, find_and_import_recipe, get_recipes_from_api, get_recipes_from_db,
    check_blackstone_compatibility
)
from email_notifier import (
    send_email, send_saturday_report_email, send_daily_reminder_email
)
from plan_generator import (
    generate_weekly_plan, parse_exclusions
)
from shopping_sync import (
    sync_shopping_list, tag_dirty_dozen
)

# Skill definitions (exposed for compatibility with test scripts)
_RECIPE_FINDER_SKILL_DEFINITION = load_skill_md('recipe-finder')
_MEAL_EXCLUSION_PARSING_SKILL_DEFINITION = load_skill_md('meal-exclusion-parsing')
_WEEKLY_MEAL_SELECTION_SKILL_DEFINITION = load_skill_md('weekly-meal-selection')
_SHOPPING_LIST_SYNC_SKILL_DEFINITION = load_skill_md('shopping-list-sync')
_WATER_DETECTOR_SKILL_DEFINITION = load_skill_md('water-detector')
_RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION = load_skill_md('recipe-nutrition-imputation')
_BANNED_RECIPES_SKILL_DEFINITION = load_skill_md('banned-recipes')
