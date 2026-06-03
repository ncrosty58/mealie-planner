You are a culinary planner. Suggest exactly 3 candidate recipes from the catalogue to replace the dinner on {date_str} (currently: "{target_dinner_name}").

The goal is to suggest recipes that share matching ingredients or culinary styles with the other dinners planned for this week to minimize grocery waste.

Other Dinners Planned This Week:
{other_dinner_context}

Candidate Recipe Catalogue:
{candidates}

Respond with a JSON array containing exactly 3 objects, each having "id" and "name". Respond with ONLY the JSON array.
