class RecipeMixin:
    def get_all_recipes(self):
        """Fetch all recipes from Mealie."""
        res = self._request("GET", "/api/recipes?perPage=500")
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def get_recipe_details(self, recipe_id):
        """Fetch full details of a specific recipe, using a cache."""
        if recipe_id in self._recipe_details_cache:
            return self._recipe_details_cache[recipe_id]

        details = self._request("GET", f"/api/recipes/{recipe_id}", timeout=10)
        self._recipe_details_cache[recipe_id] = details
        return details

    def get_recipes_details_bulk(self, recipe_ids):
        """Fetch full details for a list of recipes in parallel using a thread pool."""
        from concurrent.futures import ThreadPoolExecutor
        
        # Filter out already cached IDs
        uncached_ids = [rid for rid in recipe_ids if rid not in self._recipe_details_cache]
        
        if uncached_ids:
            def fetch_single(recipe_id):
                try:
                    return recipe_id, self.get_recipe_details(recipe_id)
                except Exception as e:
                    print(f"[Mealie] Error bulk fetching recipe {recipe_id}: {e}")
                    return recipe_id, None
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = executor.map(fetch_single, uncached_ids)
                for recipe_id, details in results:
                    if details:
                        self._recipe_details_cache[recipe_id] = details

        return {rid: self._recipe_details_cache.get(rid) for rid in recipe_ids}

    def delete_recipe(self, recipe_id):
        """Delete a recipe by ID."""
        self._request("DELETE", f"/api/recipes/{recipe_id}")
