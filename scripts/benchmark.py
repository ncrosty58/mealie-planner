import time


class DummyClient:
    def __init__(self):
        self.cache = {}

    def get_recipe_details(self, recipe_id):
        # Simulate network latency
        time.sleep(0.05)
        return {"recipeIngredient": [{"display": "Salt"}]}

    def get_recipes_details_bulk(self, recipe_ids):
        # Simulate bulk fetching which might be optimized
        time.sleep(0.05)
        return {rid: {"recipeIngredient": [{"display": "Salt"}]} for rid in recipe_ids}

def benchmark():
    meal_plans = [{"entryType": "dinner", "recipeId": str(i)} for i in range(10)]
    meal_plans = meal_plans * 2 # 20 meals, 10 unique

    # Baseline
    client = DummyClient()
    t0 = time.perf_counter()
    raw_recipe_ingredients = []
    for p in meal_plans:
        if p['entryType'] == 'dinner' and p.get('recipeId'):
            r_details = client.get_recipe_details(p['recipeId'])
            for ing in r_details.get('recipeIngredient', []):
                disp = ing.get('display') or ing.get('originalText') or ""
                if disp.strip():
                    raw_recipe_ingredients.append(disp.strip())
    baseline_time = time.perf_counter() - t0

    # Optimized
    client2 = DummyClient()
    t0 = time.perf_counter()
    raw_recipe_ingredients_opt = []
    recipe_ids = {p['recipeId'] for p in meal_plans if p['entryType'] == 'dinner' and p.get('recipeId')}
    bulk_details = client2.get_recipes_details_bulk(list(recipe_ids))
    for p in meal_plans:
        if p['entryType'] == 'dinner' and p.get('recipeId'):
            r_details = bulk_details.get(p['recipeId'], {})
            for ing in r_details.get('recipeIngredient', []):
                disp = ing.get('display') or ing.get('originalText') or ""
                if disp.strip():
                    raw_recipe_ingredients_opt.append(disp.strip())
    optimized_time = time.perf_counter() - t0

    print("--- Benchmark Results ---")
    print(f"Baseline Time: {baseline_time:.3f}s")
    print(f"Optimized Time: {optimized_time:.3f}s")
    print(f"Improvement: {baseline_time - optimized_time:.3f}s")

if __name__ == "__main__":
    benchmark()