---
name: weekly-meal-selection
description: Generate a complete 7-day meal plan (Breakfast, Lunch, Dinner) based on family preferences, perishability rules, and intelligent lunch selection.
---

# Mealie Weekly Meal Selection Skill

This skill is responsible for generating a complete 7-day meal plan. It intelligently selects dinner recipes from a provided catalogue, assigns breakfasts, and strategically chooses lunches based on the previous night's dinner and nutritional balance.

## Inputs
- `family_dietary_rules_prompt`: Family-specific dietary rules and preferences.
- `start_date`: The first day of the plan (always a Saturday).
- `exclusions`: A JSON object mapping day names to lists of meals to skip (e.g., `{"Monday": ["dinner"]}`).
- `freezer_pantry_fridge_items_priority`: Items to use up this week (comma-separated text from the user).
- `mandatory_priority_recipes`: A JSON object mapping each user-specified item to its resolved recipe ID from the catalogue (e.g., `{"pesto": "uuid-1", "frozen chicken thighs": "uuid-2"}`). **Every recipe ID listed here MUST appear in the final plan.**
- `special_requests`: Theme or specific request text.
- `recently_planned_recipes`: List of recipe names to avoid repeating.
- `recipe_catalogue_json`: Available Mealie dinner recipes.

## Workflow

1.  **Plan Dinners (Selection):** Select exactly the required number of dinner recipes from the catalogue (one for each non-excluded night).
    *   **Anti-Hallucination:** ONLY select IDs from the provided catalogue.
    *   **MANDATORY "Use Up" Items (HIGHEST PRIORITY):** If `mandatory_priority_recipes` is provided, you **MUST** include **EVERY** recipe ID from that mapping in the plan. This is non-negotiable. Do not skip any of them. If there are 3 items, all 3 corresponding recipes must appear as dinners. The remaining dinner slots should be filled with other catalogue recipes following the priorities below.
    *   **Other Priorities:** Medium: Special requests; General: Variety, fiber, no processed meats.
    *   **Ingredient Synergy / Re-use:** Prioritize selecting recipes that share overlapping fresh/perishable ingredients (e.g., cilantro, lime, cabbage, spinach, broccoli, fresh herbs) to minimize grocery waste.
    *   **Banned Recipes & Processed Meats Exclusions:** 
        *   **Strict Prohibition:** You MUST NOT select any recipes that contain processed, sausage-type meats. This includes: Sausages, Hot Dogs, Chorizo, Salami, Pepperoni, Bacon, Ham, and Pancetta.
        *   **Banned Recipes Skill:** Strictly avoid recipes matching the names, variants, or themes of banned recipes defined in the Banned Recipes Skill (e.g., cilantro/coriander soups). Use semantic reasoning for enforcement.

2.  **Plan Dinners (Ordering & Griddle Prep):** 
    *   **Perishability & 'Use Up' Sequencing (STRICT RULE):** 
        *   **Early Week (Sat-Tue):** Reserve these days for recipes using fresh/highly-perishable ingredients (e.g., fresh fish, soft greens, berries, fresh herbs).
        *   **Late Week (Wed-Fri):** Use these days for recipes using frozen, canned, or shelf-stable ingredients.
        *   **'Use Up' Item Analysis:** Look at the descriptions/names in `mandatory_priority_recipes` and `freezer_pantry_fridge_items_priority`. 
            *   If an item contains keywords like **"frozen"**, **"canned"**, **"shelf-stable"**, **"dry"**, or **"pantry"**, you **MUST** schedule the corresponding recipe for **Wednesday, Thursday, or Friday**.
            *   Conversely, if an item is described as **"fresh"** or is a fresh vegetable/fruit, it **MUST** be scheduled for **Saturday, Sunday, Monday, or Tuesday**.
    *   **Blackstone Griddle & Batch Optimization:** 
        *   **Semantic Detection:** Identify if a recipe is compatible with a Blackstone griddle (even if not explicitly named so) based on ingredients and techniques (e.g., stir-fries, smashed burgers, seared proteins, chopped vegetables).
        *   **Prep Notes:** If a dinner is griddle-compatible, or if adjacent dinners share prep steps, you **MUST** provide a `prep_note`.
        *   **Batch Cooking:** Sequence dinners to maximize batch-cooking. For example, if cooking chicken on the griddle for Saturday, suggest prepping Monday's fajita vegetables or Sunday's stir-fry tofu at the same time.
    *   **Nutritional Balance:** Avoid scheduling heavy, high-calorie dinners or low-protein/low-fiber dinners consecutively. Distribute nutritional loads evenly across the week.

3.  **Plan Lunches (Intelligent Selection):** For each day, choose between **"Leftovers"** or **"PB&J Sandwich"**.
    *   **Leftovers Rule:** Assign "Leftovers" for lunch if the PREVIOUS night's dinner was a large, home-cooked meal suitable for leftovers.
    *   **PB&J Rule:** Assign "PB&J Sandwich" if:
        1. The previous night's dinner was "Eating Out" (no leftovers available).
        2. The previous night's dinner was a smaller or lighter meal.
        3. To provide variety after several consecutive days of leftovers.
    *   **Nutritional Balance:** If the upcoming dinner is very heavy, lean toward a lighter lunch.

4.  **Plan Breakfasts:** Assign standard options providing daily variety. The allowed options are: "Cereal & Milk", "Yogurt with Granola", "Bagels & Cream Cheese", "English Muffins with Jam", "Oats", and "Toast with Jam". Do not use any other breakfast titles.

## Output
Return a JSON object containing a `days` array. Each day must have `date`, and a `meals` object with `breakfast`, `lunch`, `dinner`, and `prep_note`. 
For `dinner`, use the `id` from the catalogue. For `breakfast` and `lunch`, use the string title (e.g., "Leftovers", "PB&J Sandwich", "Cereal & Milk").
For `prep_note`, provide a short, actionable tip (string) if there is an opportunity to batch-cook ingredients or prep ahead for subsequent days (especially on the Blackstone griddle), otherwise set it to `null`.

## Example Output
```json
{
  "days": [
    {
      "date": "2026-05-30",
      "meals": {
        "breakfast": "Cereal & Milk",
        "lunch": "Leftovers",
        "dinner": "recipe-uuid-123",
        "prep_note": "While griddling the chicken tonight, cook the tofu for Sunday's stir-fry to save prep time."
      }
    },
    {
      "date": "2026-05-31",
      "meals": {
        "breakfast": "Yogurt with Granola",
        "lunch": "Leftovers",
        "dinner": "recipe-uuid-456",
        "prep_note": null
      }
    }
  ]
}
```