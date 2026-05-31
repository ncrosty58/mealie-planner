class MealplanMixin:
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
        data = self._request("GET", "/api/households/mealplans", params=params)
        if isinstance(data, dict):
            return data.get('items', [])
        return data  # Assume it's a list already

    def schedule_meal(self, date_str, entry_type, title="", text="", recipe_id=None):
        """Schedule a meal plan entry."""
        import json
        from ..exceptions import MealieAPIError
        
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
        from ..exceptions import MealieAPIError
        try:
            self._request("DELETE", f"/api/households/mealplans/{entry_id}")
        except MealieAPIError:
            pass # Often safe to ignore delete failures
