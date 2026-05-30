---
name: weekly-meal-selection
description: Select dinner recipes for the week based on family preferences and freezer items.
---

# Mealie Weekly Meal Selection Skill

This skill is responsible for intelligently selecting the best dinner recipes for an upcoming week from a provided catalogue, adhering to family preferences, dietary rules, special requests, and prioritizing freezer items.

## Inputs
- `family_dietary_rules_prompt`: A string containing family-specific dietary rules and preferences.
- `dinner_days`: A list of day names (e.g., "Monday", "Tuesday") for which dinners need to be planned.
- `num_dinners_to_plan`: The exact number of dinner recipes to select.
- `freezer_items_priority`: A string listing freezer items to prioritize in meal selection (e.g., "chicken thighs, ground beef").
- `special_requests`: A string detailing any special meal requests from the family.
- `recently_planned_recipes`: A list of recipe names that were planned recently and should be avoided to prevent repeating them week-to-week.
- `recipe_catalogue_json`: A JSON string representing an array of available recipe objects. Each recipe object will have at least:
    - `id`: Unique identifier of the recipe.
    - `name`: Name of the recipe.
    - `description`: A short description of the recipe.
    - `tags`: A list of tags associated with the recipe (e.g., "vegetarian", "italian").
    - `fiber_g`: Fiber content in grams.
    - `ingredients_preview`: A comma-separated string of key ingredients.
    - `instructions_preview`: A short preview of the instructions.

## Workflow

1.  **Understand Constraints:** Carefully read and internalize the `family_dietary_rules_prompt`, `dinner_days`, `num_dinners_to_plan`, `freezer_items_priority`, `special_requests`, and `recently_planned_recipes`.

2.  **Evaluate Recipe Catalogue:** Parse the `recipe_catalogue_json` into a list of recipe objects.

3.  **Select Dinners:** Select exactly `num_dinners_to_plan` recipe IDs from the catalogue, following these priorities:
    *   **High Priority:** Recipes containing `freezer_items_priority` ingredients.
    *   **Medium Priority:** Recipes that fulfill `special_requests`.
    *   **Adherence to Rules:** Strictly follow `family_dietary_rules_prompt` (e.g., avoiding processed meats, penalizing expensive ingredients like beef/steak unless requested, preferring high-fiber, ensuring variety).
    *   **Variety:** Avoid repeating the same recipe or very similar recipes within the planned week. Do not select any recipes from the `recently_planned_recipes` list unless absolutely necessary due to a lack of other options.
    *   **Family Preferences:** Factor in family preferences (e.g., salmon, chicken, turkey, Mexican, Italian, Asian cuisine, Blackstone griddle compatibility if relevant).

4.  **Order Selection:** Return the selected recipe IDs in the order they should be scheduled for the `dinner_days`.
    *   **Freezer Items Order:** Schedule any selected recipes that utilize prioritized freezer items towards the *end of the week* (the last elements in the list). Fresh ingredient recipes (which require items bought fresh from the store) must be scheduled first, at the *beginning of the week* (the first elements in the list). Since the planning week starts on Saturday and ends on Friday, this means freezer meal recipes should go on days like Wednesday, Thursday, or Friday.

## Output
Return a JSON object with a single key `dinner_ids` containing the ordered list of selected recipe ID strings. Do not include any additional text or explanation.

## Example Output
```json
{
  "dinner_ids": [
    "recipe-id-1",
    "recipe-id-2",
    "recipe-id-3",
    "recipe-id-4",
    "recipe-id-5",
    "recipe-id-6",
    "recipe-id-7"
  ]
}
```