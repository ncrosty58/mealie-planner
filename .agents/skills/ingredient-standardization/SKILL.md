---
name: ingredient-standardization
description: Clean and standardize raw ingredient strings by removing brand names, formatting noise, and parentheticals.
---

# Ingredient Standardization Skill

This skill takes a raw list of ingredient strings and cleans/standardizes each item to produce a consistent culinary reference.

## Workflow & Constraints
1.  **Remove Brand Names**: Strip brand identifiers, trademarks, or retailer prefixes (e.g. "Success®", "Heinen's", "Trader Joe's", "Kraft").
2.  **Preserve Quantities & Units**: Retain numeric amounts and measurement units at the beginning (e.g. "2 lbs", "1 cup", "3 cloves", "1/2 tsp").
3.  **Strip Preparation Details**: Remove parenthetical notes, secondary cuts, or preparation adjectives (e.g. "minced", "finely chopped", "sliced", "drained", "room temperature").
4.  **Format consistently**: Produce a clean, simple title-cased culinary name.
5.  **Output**: Return ONLY a JSON array of strings containing the standardized ingredients. No conversation or codeblocks.

## Example
*   **Input**: `"2 lbs Heinen's Chicken Breast, minced"` -> **Output**: `"2 lbs Chicken Breast"`
*   **Input**: `"1 cup Success® White Rice (uncooked)"` -> **Output**: `"1 cup White Rice"`
