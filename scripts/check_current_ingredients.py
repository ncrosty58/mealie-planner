import json, os, sys
sys.path.insert(0, os.path.abspath("."))
from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.utils import get_active_week_strings

def check():
    client = UnifiedMealieClient()
    s, e = get_active_week_strings()
    plans = client.get_detailed_meal_plan(s, e)
    ings = []
    for p in plans:
        if p.get("recipe"):
            for i in p["recipe"].get("recipeIngredient", []):
                ings.append(i.get("display"))
    print(json.dumps(list(set(ings)), indent=2))

if __name__ == "__main__":
    check()
