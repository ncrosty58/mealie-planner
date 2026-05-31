class ShoppingListMixin:
    def get_shopping_list_items(self, list_id):
        """Fetch all items currently on a shopping list."""
        res = self._request("GET", f"/api/households/shopping/lists/{list_id}")
        if isinstance(res, dict):
            return res.get('listItems', [])
        return []

    def clear_shopping_list(self, list_id):
        """Delete all items from a shopping list using Mealie's bulk delete endpoint in parallel."""
        items = self.get_shopping_list_items(list_id)
        if not items:
            return
        item_ids = [item['id'] for item in items]
        
        # Chunk requests to prevent extremely long URL queries
        chunk_size = 50
        chunks = [item_ids[i:i+chunk_size] for i in range(0, len(item_ids), chunk_size)]
        
        from concurrent.futures import ThreadPoolExecutor
        def delete_chunk(chunk):
            try:
                self._request("DELETE", "/api/households/shopping/items", params={"ids": chunk})
            except Exception as e:
                print(f"[Mealie] Error deleting chunk: {e}")

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(delete_chunk, chunks))

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
        """Update a specific shopping list item using the fetch-merge-update pattern to preserve existing fields."""
        current_item = self._request("GET", f"/api/households/shopping/items/{item_id}")
        if isinstance(current_item, dict):
            merged = {**current_item, **payload}
            return self._request("PUT", f"/api/households/shopping/items/{item_id}", json=merged)
        return self._request("PUT", f"/api/households/shopping/items/{item_id}", json=payload)

    def add_recipe_to_shopping_list(self, list_id, recipe_id, multiplier=None):
        """Add a single recipe's ingredients to a shopping list with optional batch scaling."""
        payload = {}
        if multiplier is not None:
            payload["recipeIncrementQuantity"] = multiplier
        return self._request(
            "POST",
            f"/api/households/shopping/lists/{list_id}/recipe/{recipe_id}",
            json=payload
        )
