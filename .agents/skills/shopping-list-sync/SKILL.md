---
name: shopping-list-sync
description: Generate the final active shopping list by filtering out plain water and non-low staples from weekly ingredients, cleaning names, aggregating quantities, and merging with the active Mealie shopping list.
---

# Shopping List Sync Skill

This skill takes the raw ingredient strings from dinner recipes, a list of household staples, manually identified low staples, and the current active shopping list, and generates the final structured shopping list ready for database import.

## Inputs
- `payload`: A JSON object containing:
    - `ingredients`: A list of raw recipe ingredient strings (e.g. `["2 cloves garlic, minced", "1 lb chicken breast"]`).
    - `staples`: A list of staple names already in the house (e.g. `["salt", "pepper"]`).
    - `inventory_items`: A list of specific items the user wants to "use up" from their freezer/pantry/fridge (e.g. `["1 lb chicken thighs", "pesto sauce"]`).
    - `low_staples`: A list of staple names that are currently running low and MUST be added (e.g. `["garlic"]`).
    - `available_labels`: A list of actual category labels from the user's Mealie instance (e.g. `["1. Produce: Vegetables & Greens", "2. Bakery & Bread"]`).
    - `active_shopping_list`: A list of objects representing the current active shopping list:
        - `index`: Integer, the array index of the item.
        - `note`: String, the item note/description.
        - `checked`: Boolean, the active checked state in Mealie.
- `family_dietary_rules`: The family-specific dietary rules and preferences (which includes the "Dirty Dozen" list).

## Workflow

1.  **Exclude Plain Water:**
    - Detect any ingredients representing plain tap water (e.g., "water", "cold water", "hot water", "tap water", "water to cover"). Exclude them entirely.
    - Keep specialty waters that must be purchased (e.g., "coconut water", "rose water", "sparkling water").

2.  **Filter Staples and Inventory (Rigorous Semantic Matching):**
    - Compare every recipe ingredient against `staples` and `inventory_items`.
    - **Deep Semantic Filtering:** Do not just look for exact name matches. Use culinary knowledge to identify if an ingredient is a form of a staple.
        - *Example:* If "Olive Oil" is a staple, filter out "Extra Virgin Olive Oil", "2 tbsp Olive Oil", "Olive oil for frying", etc.
        - *Example:* If "Garlic" is a staple, filter out "3 cloves Garlic", "Minced Garlic", etc.
        - *Reverse Variant Matching:* If the recipe calls for a generic ingredient (e.g., "Olive Oil" or "Vinegar") and a specific variety is listed in the `staples` list (e.g., "Extra virgin olive oil" or "Red wine vinegar"), treat it as a match and filter it out.
    - **Exception Rule**: If the matched staple is explicitly listed in `low_staples` or is already on `active_shopping_list`, you MUST include it.
    - **Inventory Rule**: If an ingredient matches an `inventory_item`, filter it out.
    - **Rule of Thumb**: If Nathan and Kristin already have it (Staple) or want to use it up (Inventory), and it's NOT low (Low Staples), do not put it on the shopping list.

3.  **Clean Ingredient Names & Organic Tagging:**
    - For each ingredient, extract the core name by removing quantities, units, and preparation instructions.
    - **Organic Tagging (Dirty Dozen)**: If the cleaned ingredient name matches any item from the "Dirty Dozen" list found in the `family_dietary_rules`, automatically append **(Buy Organic)** to the name.
    - Format and capitalize the resulting ingredient name in Title Case (e.g. "1 lb spinach" -> "Spinach (Buy Organic)", "3 cloves garlic" -> "Garlic").

4.  **Extract Unit and Aggregate Quantities:**
    - For each ingredient, extract the unit of measure (e.g., "lb", "oz", "cup", "can", "clove", "tsp", "tbsp").
    - If the ingredient matches a staple, the `unit` should be `null`.
    - If the same cleaned ingredient name appears multiple times, sum their quantities if the units are compatible. If incompatible or missing, default to a sensible aggregate quantity or a default quantity of 1.0.

5.  **Include Manually Added Low Staples:**
    - Ensure any item from `low_staples` that was marked as low is included in the output list with `unit: null`.

6.  **Physical Layout Categorization (Grocery Store Path Logic):**
    - Categorize items into exactly one of the provided `available_labels`.
    - **Layout Logic**: Group items using standard grocery store layouts. The provided labels are ordered 1-9 to reflect a standard walking path.
        - *Fresh Herbs*: (e.g. Thyme, Rosemary, Parsley, Cilantro, Basil) MUST be categorized under "1. Produce: Vegetables & Greens", NOT spices.
        - *Jarred/Canned Goods/Condiments*: (e.g. Artichoke Hearts, Olives, Dijon Mustard, Tahini, Balsamic Glaze, Chicken Broth, Rice) MUST be categorized under "5. Pantry & Grains".
        - *Spices/Baking/Oils*: Only dried spices, baking ingredients, and cooking oils (e.g. Olive Oil, Paprika, Red Pepper Flakes, Onion Powder) should be categorized under "6. Baking, Spices & Oils".
    - Use the EXACT string from `available_labels` for the `category` field.
    - **Sorting**: Sort the final JSON array first by the category number (1-9), and then alphabetically by ingredient name within each category.

7.  **Active List Merging & ID/Checked Retention Rules:**
    - Merge the newly compiled shopping list with the current `active_shopping_list` using robust semantic matching to preserve their database IDs (mapped via array index) and checked status:
    - **Semantic Match Checklist**:
        - Ignore leading/trailing quantities (e.g. "1", "2.5"), units, and minor misspellings.
        - Ignore plural vs. singular differences (e.g. "Tomato" matches "Tomatoes").
        - Ignore descriptive prefixes, suffixes, preparation words, and adjectives (e.g., "Fresh", "Freshly Chopped", "Raw", "Canned", "Frozen", "Organic", "Leaves"). For example, "Lemon Juice" MUST match "tablespoon Fresh Lemon Juice", and "Cilantro" MUST match "cup Fresh Cilantro Leaves".
        - If both strings share the same core ingredient name (e.g. "Cilantro", "Thyme", "Asparagus", "Tomato"), they MUST be matched.
    - If matched:
        - Set `active_item_index` to the matching item's `index` integer from `active_shopping_list`.
        - Retain the `checked` status (boolean) from the matched item.
    - If not matched:
        - Set `active_item_index` to null.
        - Set `checked` to false.
    - **Staples Preservation Rule**: If there is an item in `active_shopping_list` that matches a staple in `staples` (using semantic matching), you MUST include it in the final output (with `unit: null`, setting `active_item_index` to its `index` and preserving its `checked` status) even if it is not required by any recipe.
    - **Low Staples Rule**: Any staple in `low_staples` MUST be in the final output. If already in `active_shopping_list`, reuse its `index` and `checked` status. Otherwise, set `active_item_index` to null and `checked` to false.
    - **Staples Exclude Rule**: If a recipe ingredient matches a staple, filter it out and do NOT include it in the final output, unless it is explicitly listed in `low_staples` or is already on the `active_shopping_list`.
    - Do not include any other items from `active_shopping_list` in the output that do not belong to the compiled shopping list anymore.

## Output
Return a JSON array of objects, where each object has these exact fields:
- `active_item_index`: The matched active item's index integer, or null if it's a new item.
- `name`: Cleaned, Title Cased name (e.g. "Chicken Breast").
- `quantity`: Aggregated numeric quantity as a float.
- `unit`: The extracted unit of measure (e.g. "lb", "cup", "can"), or null for staples.
- `checked`: The matched `checked` state (boolean).
- `category`: The EXACT zone name from `available_labels`.
- Do not include any other text or conversational response.