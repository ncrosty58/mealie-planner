import os
import sys

from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.config import STAPLES_LIST_ID
from mealie_planner.unified_client import UnifiedMealieClient


def check_and_add_honey():
    client = UnifiedMealieClient()
    print(f"Fetching current items from staples shopping list (ID: {STAPLES_LIST_ID})...")
    items = client.get_shopping_list_items_for_list(STAPLES_LIST_ID)
    
    honey_exists = False
    max_position = 0
    
    print("Current staples:")
    for item in items:
        note = item.get('note', '')
        pos = item.get('position', 0)
        max_position = max(max_position, pos)
        print(f"- {note}")
        if note.strip().lower() == "honey":
            honey_exists = True
            
    if honey_exists:
        print("\n'Honey' is already listed as a staple in Mealie.")
    else:
        print("\n'Honey' not found in staples. Adding it now...")
        new_item = {
            "shoppingListId": STAPLES_LIST_ID,
            "note": "Honey",
            "quantity": 1,
            "checked": False,
            "position": max_position + 1
        }
        client.add_shopping_list_items_bulk([new_item])
        print("Successfully added 'Honey' to the staples list in Mealie.")

if __name__ == '__main__':
    check_and_add_honey()
