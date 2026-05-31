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
    - `available_labels`: A list of actual category labels from the user's Mealie instance (e.g. `["Vegetables & Greens", "Poultry", "Dairy & Eggs"]`).
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

6.  **Categorize Using Available Labels (Grocery Store Path Logic):**
    - You must categorize items to reflect the **physical path** of a standard grocery store to make shopping as efficient as possible.
    - **Department Mapping:** Map ingredients to the most descriptive label provided in `available_labels` based on these standard store "zones":
        1. **Produce / Fresh Greens**: (e.g. "Vegetables & Greens", "Fruits", "Mushrooms", "Herbs") - This is always the first stop.
        2. **Bakery / Bread**: Freshly baked goods.
        3. **Meat & Seafood**: Butchery and fish counters.
        4. **Dairy & Eggs**: Refrigerated milk, cheese, and egg cases.
        5. **Center Aisles (Pantry/Canned)**: Dry goods, pasta, canned beans, stocks.
        6. **Baking & Spices**: Flour, sugars, oils, dried seasonings.
        7. **Beverages**: Bottled water, soda, wine/beer.
        8. **Frozen**: Ice cream, frozen veggies, frozen meals.
        9. **Household**: Paper towels, cleaning supplies, miscellaneous.
    - If multiple labels could fit, prioritize the most descriptive one (e.g. prefer "Vegetables & Greens" over a generic "Produce").
    - If a label matches exactly or is a very strong semantic fit for a store zone, use it.
    - If no provided label is a good fit, set `category` to `null`.

7.  **Construct Output:**
    - Return a JSON array of objects representing the final shopping list items.
    - Each object must have:
      - `name`: Cleaned, Title Cased ingredient name (e.g. "Chicken Breast").
      - `quantity`: Aggregated numeric quantity as a float (e.g. 1.0 or 2.0).
      - `unit`: The extracted unit of measure (e.g. "lb", "cup", "can", "clove", "tsp", "tbsp"). For staples, this MUST be `null`.
      - `category`: The EXACT name of the selected label from `available_labels`, or `null`.
    - Do not include any extra text or conversational response.

## Example Input
```json
{
  "ingredients": ["2 lbs chicken breast", "1/2 cup salt", "3 cloves garlic", "2 cups water", "1 can coconut water", "1/2 tsp fresh ginger (, minced or finely chopped)"],
  "staples": ["salt", "pepper", "garlic", "olive oil"],
  "low_staples": ["garlic"],
  "available_labels": ["Vegetables & Greens", "Poultry", "Dairy & Eggs", "Beverages"]
}
```

## Example Output
```json
[
  {
    "name": "Fresh Ginger",
    "quantity": 0.5,
    "unit": "tsp",
    "category": "Vegetables & Greens"
  },
  {
    "name": "Garlic",
    "quantity": 3.0,
    "unit": null,
    "category": "Vegetables & Greens"
  },
  {
    "name": "Chicken Breast",
    "quantity": 2.0,
    "unit": "lbs",
    "category": "Poultry"
  },
  {
    "name": "Coconut Water",
    "quantity": 1.0,
    "unit": "can",
    "category": "Beverages"
  }
]
```