---
name: banned-recipes
description: Detect and filter out banned or forbidden recipes that the household does not eat.
---

# Banned Recipes Skill

This skill contains the list of recipes that are strictly banned from the family's meal plans. These recipes must never be selected by the meal selection engine, and must never be imported from the web.

## Banned Recipes List
- **[Example Banned Recipe Name]**: [Reason, e.g., allergy, preference]

> [!NOTE]
> The application will automatically prioritize loading your custom banned recipes from `data/banned_recipes.txt` (one recipe name per line) if that file exists.

