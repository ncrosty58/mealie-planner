---
name: meal-planner
description: Handle meal planning, diet rules, griddle batch cooking, organic tagging, shopping lists, and recipe scraping for the Crosty family Mealie instance.
---

# Mealie Meal Planner Skill

This skill contains the constraints, business rules, and integration workflows for managing the Crosty family Mealie companion meal planner.

## When to use this skill
- Use this when editing, debugging, or maintaining the `mealie-planner` application code under `/opt/mealie-planner`.
- Use this when modifying database sync rules, dietary filtering logic, or scheduling scripts.
- Use this when resolving issues related to shopping list calculations, Blackstone griddle checks, or nutrition summaries.

## Household & Dietary Constraints
- **Family Members**: Nathan, Kristin, Charlotte (11), Leah (6).
- **Diet**: Predominantly vegetarian/pescatarian. Prioritize fish (salmon, tuna), poultry (chicken, turkey), and vegetarian dishes.
- **Pork**: Pork is OK (except processed pork like bacon, ham, and chorizo).
- **Beef & Steak**: We still eat beef and steak, but seldom (due to cost). Apply a penalty in the scoring engine so they are scheduled rarely unless explicitly requested by the user.
- **Forbidden Meats**: Strictly avoid processed sausage-type meats (hot dogs, chorizo, salami, pepperoni, bacon, ham, pancetta).
- **Fiber Target**: Highly prioritize dietary fiber (target `28g` daily per person baseline). Focus on beans, lentils, whole grains, and fiber-rich vegetables.
- **Organic Target**: Automatically append `(Buy Organic)` to ingredients matching the USDA "Dirty Dozen" (strawberries, spinach, kale, collard/mustard greens, grapes, peaches, pears, nectarines, apples, bell peppers, hot/chili peppers, cherries, blueberries, green beans).

## Mealie Setup & State Constants
- **Active Shopping List ID**: `9a1e2d1e33f24f27a01fef55c89a92de` (renamed from "Nathans Shopping List" to "Active Shopping list").
- **Staples List ID**: `1196f23a527b42a9a75b1c3850251948` (named "Staple items").
- **Auth Token**: Retrieved dynamically from the Mealie SQLite DB volume (`/mealie-data/mealie.db` or `/app/data/mealie.db`) where `name = 'AntigravityToken'`.
- **Planning Week format**: Anchored strictly on a **Saturday-to-Friday** schedule.

## Blackstone Griddle Logic
- **Compatibility**: Check if a recipe name, description, or instructions mention `blackstone`, `griddle`, or `flat top`.
- **Batch Optimization**: If Blackstone dinners are scheduled, prompt suggestions in the emails to batch-cook ingredients for subsequent dinners.

## Double-Submission Protection
- When both parents load the planning questionnaire URL (`/`), the app must check if dinner plans are already scheduled in Mealie for the upcoming Saturday-to-Friday week.
- If plans are found, the questionnaire is hidden and they are redirected to the Active Week Dashboard showing the active calendar and shopping list.

## Scraping & Web Searching
- If a freezer item is specified and no local recipe exists in Mealie:
  1. Search DuckDuckGo HTML for recipes. Use query `healthy recipe with {ingredient}` if ingredient contains meat keywords (chicken, turkey, pork, fish, salmon, beef, steak, etc.); otherwise, use `healthy vegetarian recipe with {ingredient}`.
  2. Attempt to scrape the recipe into Mealie using the Mealie REST API URL import endpoint (`/api/recipes/create/url`).
  3. Schedule the newly imported recipe.

## Recalculation & List Syncing
- The `/sync` route recalculates the active shopping list dynamically.
- Low staples checked in the questionnaire are appended.
- Ingredients of scheduled recipes are copied over, but any ingredient matching a staple that was *not* marked as running low must be excluded.

## Communication Schedule
- **Saturday Q/A email**: Sent at 8:00 AM (New York time) to prompt questionnaire completion.
- **Saturday Report email**: Sent immediately upon questionnaire submission summarizing the plan, shopping list, griddle tips, and weekly nutrition averages.
- **Daily Reminder email**: Sent Sunday to Friday at 7:00 AM (New York time) containing today's menu, griddle reminders, and macro/micro nutrition totals compared to daily RDAs.
