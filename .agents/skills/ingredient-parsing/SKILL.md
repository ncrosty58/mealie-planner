---
name: ingredient-parsing
description: Parse free-text freezer/pantry/fridge items into structured ingredient data with core food terms for recipe matching.
---

# Ingredient Parsing Skill

This skill takes a free-text description of freezer, pantry, or refrigerated items the user wants to use up and extracts structured ingredient data for recipe matching.

## Input
- `raw_text`: The user's free-text input, typically comma-separated (e.g., "1lb frozen chicken thighs, fresh cilantro bunch, pesto sauce, 2 cans black beans").

## Workflow
1. Split the input into individual items.
2. For each item, extract the **core food ingredient** by stripping:
   - Quantities and numbers (e.g., "1lb", "2 cans")
   - Units of measurement (e.g., "lb", "bunch", "cans")
   - Storage/state modifiers (e.g., "frozen", "fresh", "canned", "leftover")
   - Filler words (e.g., "of", "a", "the")
3. Identify whether each item contains meat/seafood for recipe search targeting.

## Output
Return a JSON array of objects. Each object has:
- `raw`: The original text for this item, trimmed.
- `core_ingredient`: The essential food term for recipe matching (e.g., "chicken thighs", "cilantro", "black beans").
- `has_meat`: Boolean — true if this item contains meat, poultry, or seafood.
- `is_main_dish`: Boolean — true if this item is a main dish, entree, or primary protein/meal component (e.g. "chicken thighs", "beef", "salmon"). False if it is a sauce, condiment, dip, dressing, herb, side dish, or basic base ingredient (e.g. "Tzatziki sauce", "hummus", "pesto", "sour cream", "cilantro", "romaine lettuce").

## Example

**Input:** `"1lb frozen chicken thighs, fresh cilantro bunch, pesto sauce, 2 cans black beans"`

**Output:**
```json
[
  {"raw": "1lb frozen chicken thighs", "core_ingredient": "chicken thighs", "has_meat": true, "is_main_dish": true},
  {"raw": "fresh cilantro bunch", "core_ingredient": "cilantro", "has_meat": false, "is_main_dish": false},
  {"raw": "pesto sauce", "core_ingredient": "pesto", "has_meat": false, "is_main_dish": false},
  {"raw": "2 cans black beans", "core_ingredient": "black beans", "has_meat": false, "is_main_dish": false}
]
```
