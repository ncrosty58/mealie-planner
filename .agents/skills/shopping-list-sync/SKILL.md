---
name: shopping-list-sync
description: Generate the final active shopping list by filtering out plain water and non-low staples from weekly ingredients, cleaning names, and aggregating quantities.
---

# Shopping List Sync Skill

This skill takes the raw ingredient strings from dinner recipes, a list of household staples, and a list of manually identified low staples, and generates the final structured active shopping list.

## Inputs
- `payload`: A JSON object containing:
    - `ingredients`: A list of raw recipe ingredient strings (e.g. `["2 cloves garlic, minced", "1 lb chicken breast"]`).
    - `staples`: A list of staple names already in the house (e.g. `["salt", "pepper"]`).
    - `inventory_items`: A list of specific items the user wants to "use up" from their freezer/pantry/fridge (e.g. `["1 lb chicken thighs", "pesto sauce"]`).
    - `low_staples`: A list of staple names that are currently running low and MUST be added (e.g. `["garlic"]`).
- `family_dietary_rules`: The family-specific dietary rules and preferences (which includes the "Dirty Dozen" list).

## Workflow

1.  **Exclude Plain Water:**
    - Detect any ingredients representing plain tap water (e.g., "water", "cold water", "hot water", "tap water", "water to cover"). Exclude them entirely from the output.
    - Keep specialty waters that must be purchased (e.g., "coconut water", "rose water", "sparkling water").

2.  **Filter Staples and Inventory:**
    - Compare each recipe ingredient against the combined list of `staples` and `inventory_items`.
    - Handle exact, singular/plural, and minor semantic variations (e.g. "cloves of garlic" or "garlic cloves" or "garlic" vs "garlic").
    - For `inventory_items`, prioritize matching the core ingredient (e.g., "1 lb chicken thighs" should match "chicken thighs" in a recipe).
    - If the ingredient matches a staple or an inventory item:
      - Exclude it *unless* it matches an item in the `low_staples` list.
      - If it is in the `low_staples` list, include it.
    - If the ingredient does not match a staple or inventory item, include it.

3.  **Clean Ingredient Names & Organic Tagging:**
    - For each ingredient, extract the core name by removing quantities, units, and preparation instructions.
    - **Organic Tagging (Dirty Dozen):** If the cleaned ingredient name matches any item from the "Dirty Dozen" list found in the `family_dietary_rules`, automatically append **(Buy Organic)** to the name.
    - Format and capitalize the resulting ingredient name in Title Case (e.g. "1 lb spinach" -> "Spinach (Buy Organic)", "3 cloves garlic" -> "Garlic").

4.  **Extract Unit and Aggregate Quantities:**
    - For each ingredient, extract the unit of measure (e.g., "lb", "oz", "cup", "can", "clove", "tsp", "tbsp").
    - If the ingredient matches a staple, the `unit` should be `null` (units are not used for staple items).
    - If the same cleaned ingredient name appears multiple times, aggregate their quantities by summing them if the units are compatible.
    - If units are incompatible or missing, default to a sensible aggregate quantity or a default quantity of 1.0.

5.  **Include Manually Added Low Staples:**
    - Ensure any item from `low_staples` that was marked as low is included in the output list with `unit: null`.

6.  **Sort by Grocery Store Aisle/Path:**
    - Sort the final list of items in the typical path order of a standard grocery store layout. The physical layout/path order is:
      1. Produce (Fresh vegetables, fruits, herbs, root vegetables e.g., Onions, Garlic, Cilantro, Limes, Ginger, Carrots, Green Onions, Potatoes, Peppers, Mushrooms)
      2. Bakery (Bread, tortillas, pita, buns)
      3. Meat, Seafood & Vegetarian Alternatives (Chicken, Salmon, Beef, Turkey, Pork, Tofu)
      4. Dairy, Cheese & Eggs (Milk, Cream, Yogurt, Butter, Mozzarella, Parmesan, Cheddar, Eggs)
      5. Pantry / Center Aisle Grains & Canned Goods (Beans, Chickpeas, Lentils, Rice, Pasta, Noodles, Canned Tomatoes, Tomato Paste, Broth, Soup, Oatmeal, Cereal)
      6. Baking, Spices, Oils & Condiments (Baking powder, Flour, Oils, Vinegars, Soy Sauce, Sugar, Honey, Maple Syrup, Chili Paste, Herbs/Spices/Seasonings, Garlic Bread)
      7. Frozen Foods (Frozen vegetables, frozen meals, ice cream)
      8. Beverages (Coconut water, juices, soda, sparkling water)
      9. Household / Miscellaneous / Non-Food items
    - Group items belonging to the same category/aisle together, and order the categories according to the list above. Within each category, sort items alphabetically.

7.  **Construct Output:**
    - Return a JSON array of objects representing the final shopping list items.
    - Each object must have:
      - `name`: Cleaned, Title Cased ingredient name (e.g. "Chicken Breast").
      - `quantity`: Aggregated numeric quantity as a float (e.g. 1.0 or 2.0).
      - `unit`: The extracted unit of measure (e.g. "lb", "cup", "can", "clove", "tsp", "tbsp"). For staples, this MUST be `null`.
      - `category`: The numbered category this item belongs to. MUST be exactly one of:
        - "1. Produce"
        - "2. Bakery"
        - "3. Meat, Seafood & Vegetarian Alternatives"
        - "4. Dairy, Cheese & Eggs"
        - "5. Pantry / Center Aisle Grains & Canned Goods"
        - "6. Baking, Spices, Oils & Condiments"
        - "7. Frozen Foods"
        - "8. Beverages"
        - "9. Household / Miscellaneous / Non-Food items"
    - Do not include any extra text or conversational response.

## Example Input
```json
{
  "ingredients": ["2 lbs chicken breast", "1/2 cup salt", "3 cloves garlic", "2 cups water", "1 can coconut water", "1/2 tsp fresh ginger (, minced or finely chopped)"],
  "staples": ["salt", "pepper", "garlic", "olive oil"],
  "low_staples": ["garlic"]
}
```

## Example Output
```json
[
  {
    "name": "Fresh Ginger",
    "quantity": 0.5,
    "unit": "tsp",
    "category": "1. Produce"
  },
  {
    "name": "Garlic",
    "quantity": 3.0,
    "unit": null,
    "category": "1. Produce"
  },
  {
    "name": "Chicken Breast",
    "quantity": 2.0,
    "unit": "lbs",
    "category": "3. Meat, Seafood & Vegetarian Alternatives"
  },
  {
    "name": "Coconut Water",
    "quantity": 1.0,
    "unit": "can",
    "category": "8. Beverages"
  }
]
```