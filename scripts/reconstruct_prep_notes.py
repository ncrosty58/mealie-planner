import os
import sys
import json
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from mealie_planner.unified_client import UnifiedMealieClient

from mealie_planner.ai_client import AIClient
from mealie_planner.utils import get_active_week_strings

class DinnerPrepNote(BaseModel):
    date: str
    prep_note: Optional[str] = None

class PrepNotesResponse(BaseModel):
    notes: List[DinnerPrepNote]

def reconstruct_prep_notes():
    client = UnifiedMealieClient()
    ai = AIClient()
    
    start_date_str, end_date_str = get_active_week_strings()
    print(f"Reconstructing prep notes for active week: {start_date_str} to {end_date_str}...")
    
    plans = client.get_meal_plan(start_date_str, end_date_str)
    dinners = [p for p in plans if p.get('entryType') == 'dinner']
    
    if not dinners:
        print("No dinners scheduled for this week.")
        return
        
    # Gather recipe details
    dinner_details = []
    for d in dinners:
        d_date = d['date']
        d_id = d['id']
        r_id = d.get('recipeId')
        title = d.get('title') or ""
        
        recipe_data = None
        if r_id:
            try:
                recipe_data = client.get_recipe_details(r_id)
                title = recipe_data.get('name') or title
            except Exception as e:
                print(f"Error fetching recipe {r_id}: {e}")
                
        dinner_details.append({
            "date": d_date,
            "entry_id": d_id,
            "title": title,
            "recipe": {
                "name": recipe_data.get('name') if recipe_data else title,
                "ingredients": [i.get('note') or i.get('display') for i in recipe_data.get('recipeIngredient', [])] if recipe_data else [],
                "instructions": [inst.get('text') for inst in recipe_data.get('recipeInstructions', [])] if recipe_data else []
            }
        })
        
    # Build prompt
    prompt = (
        "You are an AI assistant helping a family optimize their meal prep for the week.\n"
        "Here is the list of dinners scheduled for the week:\n\n"
    )
    for dd in dinner_details:
        prompt += f"Date: {dd['date']}\n"
        prompt += f"Meal: {dd['title']}\n"
        if dd['recipe']['ingredients']:
            prompt += f"Ingredients: {', '.join(dd['recipe']['ingredients'])}\n"
        prompt += "\n"
        
    prompt += (
        "Instructions:\n"
        "Analyze the scheduled dinners and identify opportunities for:\n"
        "1. Blackstone griddle compatibility and batch-cooking (e.g. if one meal uses the griddle, can they prep/cook elements for another meal?).\n"
        "2. Chopping/prepping shared ingredients ahead of time.\n"
        "3. Any other useful prep tips for these specific meals.\n\n"
        "For each date, provide a short, actionable prep_note (string) to be saved in the database. "
        "If there are no useful prep or batch-cooking opportunities for a specific day, set prep_note to null.\n\n"
        "Return the output as a JSON object matching the requested schema."
    )
    
    try:
        raw_response = ai.call(prompt, response_schema=PrepNotesResponse, temperature=0.7)
        parsed = PrepNotesResponse.model_validate_json(raw_response)
        
        notes_map = {n.date: n.prep_note for n in parsed.notes}
        
        print("\nGenerated Prep Notes:")
        for date, note in notes_map.items():
            print(f"- {date}: {note}")
            
        print("\nUpdating Mealie database...")
        for dd in dinner_details:
            date = dd['date']
            note = notes_map.get(date)
            if note:
                entry_id = dd['entry_id']
                # Fetch full entry to preserve required fields (groupId, userId, etc.)
                full_entry = next(p for p in plans if p['id'] == entry_id)
                full_entry['text'] = note
                try:
                    client._handle_request('PUT', f'/api/households/mealplans/{entry_id}', json=full_entry)
                    print(f"Successfully updated prep note for {date}")
                except Exception as e:
                    print(f"Failed to update entry {entry_id} for {date}: {e}")
            else:
                print(f"No prep note for {date}")
                
    except Exception as e:
        print(f"AI generation failed: {e}")

if __name__ == '__main__':
    reconstruct_prep_notes()
