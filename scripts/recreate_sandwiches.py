import sys
import os
import requests
import uuid
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.unified_client import UnifiedMealieClient

def create_basic_sandwiches():
    client = UnifiedMealieClient()
    api_url = client.api_url
    headers = client.headers
    
    # 1. Define IDs for Units
    units = {
        'slices': 'ac91c218-13ba-4b4e-8cf1-ddb624f5c20d',
        'tablespoon': 'eaaa7bc2-a8b0-47d7-ba3a-2a41f3e9842b',
        'teaspoon': 'b5d6ca7e-f2cf-4c0c-853f-96ecaf734515',
        'ounce': '63ac9ef0-55db-420c-a322-b9f6b549692d'
    }

    # 2. Fetch all foods for matching
    r_foods = requests.get(f"{api_url}/api/foods?perPage=500", headers=headers)
    food_map = {f['name'].lower(): f for f in r_foods.json().get('items', [])}

    def get_or_create_food(name):
        low_name = name.lower()
        if low_name in food_map:
            return food_map[low_name]
        
        print(f"Creating food: {name}")
        payload = {"name": name, "description": ""}
        try:
            r = requests.post(f"{api_url}/api/foods", json=payload, headers=headers)
            r.raise_for_status()
            new_food = r.json()
            food_map[low_name] = new_food
            return new_food
        except:
            # If creation fails (likely exists), search again specifically for it
            r = requests.get(f"{api_url}/api/foods?perPage=10&search={name}", headers=headers)
            items = r.json().get('items', [])
            for f in items:
                if f['name'].lower() == name.lower():
                    return f
            return items[0] # Best effort

    # 3. Define Recipe Data
    recipes_to_create = [
        {
            "name": "PB&J Sandwich",
            "slug": "pb-j-sandwich",
            "description": "A classic, basic PB&J sandwich.",
            "image": "https://images.unsplash.com/photo-1594911772125-07fc7a2d8d9f?q=80&w=1000&auto=format&fit=crop",
            "ingredients": [
                ("Sliced bread", 2, "slices"),
                ("Peanut Butter", 2, "tablespoon"),
                ("Fruit jam/jelly", 1, "tablespoon")
            ]
        },
        {
            "name": "Classic Deli Sandwich",
            "slug": "classic-deli-sandwich",
            "description": "A basic deli-style sandwich with meat and cheese.",
            "image": "https://images.unsplash.com/photo-1554433607-66b5efe9d304?q=80&w=1000&auto=format&fit=crop",
            "ingredients": [
                ("Sliced bread", 2, "slices"),
                ("Deli Meat", 4, "ounce"),
                ("Sliced Cheese", 2, "slices"),
                ("Mayonnaise", 1, "tablespoon"),
                ("Mustard", 1, "teaspoon")
            ]
        }
    ]

    for data in recipes_to_create:
        print(f"--- Creating {data['name']} ---")
        
        # 1. Create the base recipe
        recipe_payload = {
            "name": data['name'],
            "slug": data['slug'],
            "description": data['description'],
            "image": data['image'],
            "recipeInstructions": [{"text": "Assemble the sandwich and enjoy.", "id": str(uuid.uuid4()), "title": ""}],
            "settings": {"public": True, "showNutrition": True}
        }
        
        r = requests.post(f"{api_url}/api/recipes", json=recipe_payload, headers=headers)
        if r.status_code not in (200, 201):
            print(f"Failed to create {data['name']}: {r.status_code} - {r.text}")
            continue

        print(f"Successfully created {data['name']} shell. Performing structured update...")

        # 2. Re-fetch full object to get ID and structure
        recipe = requests.get(f"{api_url}/api/recipes/{data['slug']}", headers=headers).json()
        
        # 3. Build structured ingredients
        new_ings = []
        for food_name, qty, unit_name in data['ingredients']:
            food = get_or_create_food(food_name)
            unit_id = units[unit_name]
            
            new_ings.append({
                "referenceId": str(uuid.uuid4()),
                "note": food_name,
                "display": f"{qty} {unit_name} {food_name}",
                "quantity": qty,
                "unitId": unit_id,
                "foodId": food['id'],
                "food": food,
                "originalText": f"{qty} {unit_name} {food_name}",
                "disableAmount": False
            })
            
        recipe['recipeIngredient'] = new_ings
        
        # 4. Save via PUT
        save_r = requests.put(f"{api_url}/api/recipes/{data['slug']}", json=recipe, headers=headers)
        print(f"Structured update for {data['name']}: {save_r.status_code}")

if __name__ == "__main__":
    create_basic_sandwiches()
