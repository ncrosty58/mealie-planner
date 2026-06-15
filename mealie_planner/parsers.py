from datetime import datetime, timedelta
from .config import (
    _INGREDIENT_PARSING_SKILL_DEFINITION,
    _MEAL_EXCLUSION_PARSING_SKILL_DEFINITION
)
from .exceptions import SkillParsingError
from .models import ParsedIngredientList, MealExclusions

def parse_freezer_items(ai_client, text: str) -> list:
    """Use AI to parse free-text freezer/pantry/fridge items into structured ingredient data."""
    if not text or not text.strip():
        return []
    
    prompt = (
        "You are an expert in the 'Ingredient Parsing Skill'.\n\n" +
        _INGREDIENT_PARSING_SKILL_DEFINITION +
        "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
        f"User input: {text}\n\n" +
        "Return ONLY the JSON array as specified in the skill definition."
    )
    
    raw = ai_client.call(prompt, response_schema=ParsedIngredientList)
    # Parse and validate with Pydantic
    result = ParsedIngredientList.model_validate_json(raw).root
    return [item.model_dump() for item in result]

def parse_exclusions(ai_client, text: str, start_date, end_date) -> dict:
    """Use AI to interpret a free-text description of which meals to skip."""
    if not text or not text.strip():
        return {}

    num_days = (end_date - start_date).days + 1
    week_dates = {
        (start_date + timedelta(days=i)).strftime("%A"): (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(num_days)
    }

    prompt = (
        """You are an expert in the 'Mealie Meal Exclusion Parsing Skill'.

""" +
        _MEAL_EXCLUSION_PARSING_SKILL_DEFINITION +
        """

### CONTEXT FOR THIS INVOCATION:
""" +
        f"User input: {text}\n" +
        f"Week dates: {', '.join(f'{d} ({dt})' for d, dt in week_dates.items())}.\n\n" +
        "Return ONLY the JSON object as specified in the skill definition."
    )

    raw = ai_client.call(prompt, response_schema=MealExclusions)
    result = MealExclusions.model_validate_json(raw).root

    # Filter days and meals based on the pydantic model output
    exclusions = {}
    for day, meals in result.items():
        if meals:
            exclusions[day] = meals
    return exclusions
