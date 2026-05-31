import os
import json
import requests
from .exceptions import MealieAPIError, ConfigurationError

def get_mealie_token():
    """Retrieve the API token from the MEALIE_TOKEN env var."""
    token = os.getenv('MEALIE_TOKEN')
    if token and token != 'your_mealie_api_token_here':
        return token
    return None

class MealieClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MealieClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.api_url = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
        self.token = get_mealie_token()
        if not self.token:
            raise ConfigurationError("Mealie API Token (MEALIE_TOKEN) is missing or invalid.")
            
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self._recipe_details_cache = {}
        self._initialized = True

    def _request(self, method, path, **kwargs):
        """Internal helper to handle requests and raise custom exceptions."""
        url = f"{self.api_url}{path}"
        try:
            r = requests.request(method, url, headers=self.headers, **kwargs)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response else None
            text = e.response.text if e.response else str(e)
            raise MealieAPIError(f"Mealie API {method} {path} failed: {str(e)}", 
                               status_code=status_code, response_text=text) from e

    def get_users(self):
        """Fetch all users registered in Mealie using the admin endpoint."""
        r = self._request("GET", "/api/admin/users")
        return r.json().get('items', [])

    def get_all_recipes(self):
        """Fetch all recipes from Mealie."""
        r = self._request("GET", "/api/recipes?perPage=500")
        return r.json().get('items', [])

    def get_recipe_details(self, recipe_id):
        """Fetch full details of a specific recipe, using a cache."""
        if recipe_id in self._recipe_details_cache:
            return self._recipe_details_cache[recipe_id]

        r = self._request("GET", f"/api/recipes/{recipe_id}", timeout=10)
        details = r.json()
        self._recipe_details_cache[recipe_id] = details
        return details

    def get_shopping_list_items(self, list_id):
        """Fetch all items currently on a shopping list."""
        r = self._request("GET", f"/api/households/shopping/lists/{list_id}")
        return r.json().get('listItems', [])

    def clear_shopping_list(self, list_id):
        """Delete all items from a shopping list using Mealie's bulk delete endpoint."""
        items = self.get_shopping_list_items(list_id)
        if not items:
            return
        item_ids = [item['id'] for item in items]
        
        # Chunk requests to prevent extremely long URL queries
        chunk_size = 50
        for i in range(0, len(item_ids), chunk_size):
            chunk = item_ids[i:i+chunk_size]
            self._request("DELETE", "/api/households/shopping/items", params={"ids": chunk})

    def add_shopping_list_items_bulk(self, items):
        """Add multiple items to the shopping list in bulk."""
        if not items:
            return
        self._request("POST", "/api/households/shopping/items/create-bulk", json=items)

    def add_shopping_list_item(self, list_id, note):
        """Add a single item to the shopping list."""
        payload = {
            "shoppingListId": list_id,
            "note": note,
            "checked": False
        }
        self._request("POST", "/api/households/shopping/items", json=payload)

    def update_shopping_list_item(self, item_id, payload):
        """Update a specific shopping list item."""
        self._request("PUT", f"/api/households/shopping/items/{item_id}", json=payload)

    def get_labels(self):
        """Fetch all multi-purpose labels."""
        r = self._request("GET", "/api/groups/labels")
        return r.json().get('items', [])

    def create_label(self, name, color="#959595"):
        """Create a new shopping label."""
        payload = {"name": name, "color": color}
        r = self._request("POST", "/api/groups/labels", json=payload)
        return r.json()

    def get_meal_plan(self, start_date, end_date):
        """Fetch scheduled meal plans for a date range."""
        # Use both sets of params for compatibility across Mealie versions
        params = {
            "start": start_date,
            "end": end_date,
            "startDate": start_date,
            "endDate": end_date,
            "perPage": 100 # Ensure we get all items
        }
        r = self._request("GET", "/api/households/mealplans", params=params)
        data = r.json()
        if isinstance(data, dict):
            return data.get('items', [])
        return data  # Assume it's a list already

    def schedule_meal(self, date_str, entry_type, title="", text="", recipe_id=None):
        """Schedule a meal plan entry."""
        if not recipe_id and not title:
            title = "Planned Meal"

        payload = {
            "date": date_str,
            "entryType": entry_type,
            "title": title,
            "text": text,
            "recipeId": recipe_id
        }
        print(f"[Mealie] Scheduling {entry_type} on {date_str}: {title or recipe_id}")
        
        try:
            self._request("POST", "/api/households/mealplans", json=payload)
        except MealieAPIError as e:
            if e.status_code == 422:
                print(f"[Mealie] 422 Error Payload: {json.dumps(payload)}")
                print(f"[Mealie] 422 Error Response: {e.response_text}")
            raise

    def delete_meal_plan_entry(self, entry_id):
        """Delete a meal plan entry by ID."""
        try:
            self._request("DELETE", f"/api/households/mealplans/{entry_id}")
        except MealieAPIError:
            pass # Often safe to ignore delete failures

    def delete_recipe(self, recipe_id):
        """Delete a recipe by ID."""
        self._request("DELETE", f"/api/recipes/{recipe_id}")

