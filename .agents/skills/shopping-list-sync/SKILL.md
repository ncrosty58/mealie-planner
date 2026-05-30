---
name: shopping-list-sync
description: Generate the final active shopping list by filtering out plain water and non-low staples from weekly ingredients, cleaning names, and aggregating quantities.
---

# Shopping List Sync Skill

This skill takes the raw ingredient strings from dinner recipes, a list of household staples, and a list of manually identified low staples, and generates the final structured active shopping list.

## Inputs
- `ingredients_json`: A JSON list of raw recipe ingredient strings (e.g. `["2 cloves garlic, minced", "1 lb chicken breast", "2 cups cold water", "1 tsp salt"]`).
- `staples_json`: A JSON list of staple names (e.g. `["salt", "pepper", "olive oil", "garlic"]`).
- `low_staples_json`: A JSON list of staple names that are currently running low and need to be replenished (e.g. `["garlic"]`).

## Workflow

1.  **Exclude Plain Water:**
    - Detect any ingredients representing plain tap water (e.g., "water", "cold water", "hot water", "tap water", "water to cover"). Exclude them entirely from the output.
    - Keep specialty waters that must be purchased (e.g., "coconut water", "rose water", "sparkling water").

2.  **Filter Staples:**
    - Compare each recipe ingredient against the `staples` list (handle exact, singular/plural, and minor semantic variations, e.g. "cloves of garlic" or "garlic cloves" or "garlic" vs "garlic").
    - If the ingredient matches a staple:
      - Exclude it *unless* it matches an item in the `low_staples` list.
      - If it is in the `low_staples` list, include it.
    - If the ingredient does not match a staple, include it.

3.  **Clean Ingredient Names:**
    - Clean the ingredient names by removing quantities, fractions, numbers, and units of measure.
    - Format and capitalize the ingredient name in Title Case (e.g., "1 lb chicken breast" -> "Chicken Breast", "3 cloves garlic, minced" -> "Garlic").

4.  **Aggregate and Sum Quantities:**
    - If the same cleaned ingredient name appears multiple times, aggregate their quantities by summing them if the units are compatible.
    - If units are incompatible or missing, default to a sensible aggregate quantity or a default quantity of 1.0.

5.  **Include Manually Added Low Staples:**
    - Ensure any item from `low_staples` that was marked as low is included in the output list.

6.  **Construct Output:**
    - Return a JSON array of objects representing the final shopping list items.
    - Each object must have:
      - `name`: Cleaned, Title Cased ingredient name (e.g. "Chicken Breast").
      - `quantity`: Aggregated numeric quantity as a float (e.g. 1.0 or 2.0).
    - Do not include any extra text or conversational response.

## Example Input
```json
{
  "ingredients": ["2 lbs chicken breast", "1/2 cup salt", "3 cloves garlic", "2 cups water", "1 can coconut water"],
  "staples": ["salt", "pepper", "garlic", "olive oil"],
  "low_staples": ["garlic"]
}
```

## Example Output
```json
[
  {
    "name": "Chicken Breast",
    "quantity": 2.0
  },
  {
    "name": "Garlic",
    "quantity": 3.0
  },
  {
    "name": "Coconut Water",
    "quantity": 1.0
  }
]
```