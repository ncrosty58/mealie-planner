import os
import re
import json
import random
import sqlite3
import smtplib
import requests
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Constants
DIRTY_DOZEN = {
    'strawberry', 'strawberries', 'spinach', 'kale', 'collard', 'mustard green', 
    'mustard greens', 'grape', 'grapes', 'peach', 'peaches', 'pear', 'pears', 
    'nectarine', 'nectarines', 'apple', 'apples', 'bell pepper', 'bell peppers', 
    'hot pepper', 'hot peppers', 'chili pepper', 'chili peppers', 'cherry', 
    'cherries', 'blueberry', 'blueberries', 'green bean', 'green beans'
}

# Processed meats to always exclude from meal planning
PROCESSED_MEATS = {
    'sausage', 'hotdog', 'hot dog', 'chorizo', 'salami',
    'pepperoni', 'bacon', 'ham', 'pancetta'
}

BREAKFAST_PROFILES = {
    "English Muffins with Jam": {
        "calories": 220, "protein": 5, "carbs": 40, "fat": 2, "fiber": 2, "sodium": 320, "sugar": 10, "cholesterol": 0
    },
    "Toast with Jam": {
        "calories": 200, "protein": 4, "carbs": 35, "fat": 2, "fiber": 2, "sodium": 300, "sugar": 10, "cholesterol": 0
    },
    "Bagels & Cream Cheese": {
        "calories": 380, "protein": 11, "carbs": 55, "fat": 12, "fiber": 2, "sodium": 500, "sugar": 6, "cholesterol": 30
    },
    "Yogurt with Granola": {
        "calories": 250, "protein": 12, "carbs": 35, "fat": 5, "fiber": 3, "sodium": 100, "sugar": 15, "cholesterol": 15
    },
    "Cereal & Milk": {
        "calories": 300, "protein": 8, "carbs": 50, "fat": 6, "fiber": 3, "sodium": 200, "sugar": 12, "cholesterol": 15
    }
}

LUNCH_LEFTOVER_PROFILE = {
    "calories": 500, "protein": 22, "carbs": 55, "fat": 15, "fiber": 5, "sodium": 600, "sugar": 5, "cholesterol": 40
}

# RECOMMENDED DAILY ALLOWANCES (Individual Baseline Reference)
RDA = {
    "calories": 2000,
    "protein": 50,
    "carbs": 275,
    "fat": 70,
    "fiber": 28,  # Target high fiber
    "sodium": 2300,
    "sugar": 50,
    "cholesterol": 300
}

ACTIVE_LIST_ID = "9a1e2d1e33f24f27a01fef55c89a92de"
STAPLES_LIST_ID = "1196f23a527b42a9a75b1c3850251948"


# ---------------------------------------------------------------------------
# Gemini AI Client
# ---------------------------------------------------------------------------

def call_gemini(prompt: str, expect_json: bool = True) -> str:
    """
    Send a prompt to the Gemini API and return the text response.
    If expect_json=True, requests JSON output mode and returns the raw text
    so callers can parse it themselves.
    """
    api_key = os.getenv('GOOGLE_API_KEY')
    model = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set in environment.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json" if expect_json else "text/plain"
        }
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

def get_mealie_token():
    """Retrieve the API token automatically from the Mealie SQLite database."""
    token = os.getenv('MEALIE_TOKEN')
    if token:
        return token
        
    db_path = os.getenv('MEALIE_DB_PATH', '/mealie-data/mealie.db')
    if not os.path.exists(db_path):
        # Check if database is in /app/data (like inside the mealie container context)
        fallback_path = '/app/data/mealie.db'
        if os.path.exists(fallback_path):
            db_path = fallback_path
            
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return None
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT token FROM long_live_tokens WHERE name = 'AntigravityToken' LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        print(f"Error reading token from SQLite: {e}")
    return None

class MealieClient:
    def __init__(self):
        self.api_url = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
        self.token = get_mealie_token()
        if not self.token:
            raise Exception("Mealie API Token could not be retrieved. Please check your DB or environment.")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_users(self):
        """Fetch all users registered in the Mealie database."""
        r = requests.get(f"{self.api_url}/api/users", headers=self.headers)
        r.raise_for_status()
        return r.json().get('items', [])

    def get_all_recipes(self):
        """Fetch all recipes from Mealie."""
        r = requests.get(f"{self.api_url}/api/recipes?perPage=200", headers=self.headers)
        r.raise_for_status()
        return r.json().get('items', [])

    def get_recipe_details(self, recipe_id):
        """Fetch full details of a specific recipe."""
        r = requests.get(f"{self.api_url}/api/recipes/{recipe_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def get_shopping_list_items(self, list_id):
        """Fetch all items currently on a shopping list."""
        r = requests.get(f"{self.api_url}/api/households/shopping/lists/{list_id}", headers=self.headers)
        r.raise_for_status()
        return r.json().get('listItems', [])

    def clear_shopping_list(self, list_id):
        """Delete all items from a shopping list using Mealie's bulk delete endpoint."""
        items = self.get_shopping_list_items(list_id)
        if not items:
            return
        item_ids = [item['id'] for item in items]
        
        # Chunk requests to prevent extremely long URL queries
        chunk_size = 50
        for i in range(0, len(item_ids), chunk_size):
            chunk = item_ids[i:i+chunk_size]
            r = requests.delete(f"{self.api_url}/api/households/shopping/items", params={"ids": chunk}, headers=self.headers)
            r.raise_for_status()


    def add_shopping_list_items_bulk(self, items):
        """Add multiple items to the shopping list in bulk."""
        if not items:
            return
        r = requests.post(f"{self.api_url}/api/households/shopping/items/create-bulk", json=items, headers=self.headers)
        r.raise_for_status()

    def update_shopping_list_item(self, item_id, payload):
        """Update a specific shopping list item."""
        r = requests.put(f"{self.api_url}/api/households/shopping/items/{item_id}", json=payload, headers=self.headers)
        r.raise_for_status()

    def get_meal_plan(self, start_date, end_date):
        """Fetch scheduled meal plans for a date range."""
        r = requests.get(f"{self.api_url}/api/households/mealplans?startDate={start_date}&endDate={end_date}", headers=self.headers)
        r.raise_for_status()
        return r.json().get('items', [])

    def schedule_meal(self, date_str, entry_type, title="", text="", recipe_id=None):
        """Schedule a meal plan entry."""
        payload = {
            "date": date_str,
            "entryType": entry_type,
            "title": title,
            "text": text,
            "recipeId": recipe_id
        }
        r = requests.post(f"{self.api_url}/api/households/mealplans", json=payload, headers=self.headers)
        r.raise_for_status()

    def delete_meal_plan_entry(self, entry_id):
        """Delete a meal plan entry by ID."""
        requests.delete(f"{self.api_url}/api/households/mealplans/{entry_id}", headers=self.headers)



def tag_dirty_dozen(note):
    """If an ingredient belongs to the 'Dirty Dozen', automatically append '(Buy Organic)'."""
    if not note:
        return note
        
    note_lower = note.lower()
    # Simple regex word boundary check for each item in the dirty dozen
    for item in DIRTY_DOZEN:
        # Match word boundaries or plural variants
        pattern = r'\b' + re.escape(item) + r's?\b'
        if re.search(pattern, note_lower):
            if "(buy organic)" not in note_lower and "organic" not in note_lower:
                return f"{note} (Buy Organic)"
            break
    return note


def check_blackstone_compatibility(recipe):
    """Check if a recipe uses the Blackstone griddle."""
    name_lower = recipe['name'].lower()
    instructions = recipe.get('recipeInstructions', [])
    instructions_text = " ".join([i.get('text', '').lower() for i in instructions if i.get('text')]).lower()
    
    return 'blackstone' in name_lower or 'griddle' in name_lower or 'blackstone' in instructions_text or 'griddle' in instructions_text


def send_email(subject, html_content):
    """Send an email using SMTP settings."""
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASSWORD')
    from_email = os.getenv('SMTP_FROM_EMAIL')
    from_name = os.getenv('SMTP_FROM_NAME', 'Mealie Planner')

    if not smtp_user or not smtp_pass:
        print("SMTP settings are missing. Cannot send email.")
        return False

    recipients = []
    try:
        db_path = os.getenv('MEALIE_DB_PATH', '/mealie-data/mealie.db')
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM users WHERE email IS NOT NULL AND email != ''")
            recipients = [row[0] for row in cursor.fetchall()]
            conn.close()
    except Exception as e:
        print(f"Error querying SQLite users for email: {e}")

    if not recipients:
        try:
            client = MealieClient()
            users = client.get_users()
            recipients = [u['email'] for u in users if u.get('email')]
        except Exception as e:
            print(f"Error fetching email recipients via API: {e}")
            recipients = [smtp_user]

    if not recipients:
        print("No recipient emails found. Cannot send email.")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{from_name} <{from_email}>"
    msg['To'] = ", ".join(recipients)

    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, recipients, msg.as_string())
        print(f"Successfully sent email: '{subject}' to {recipients}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def parse_nutrient_val(val):
    if not val:
        return 0.0
    try:
        cleaned = "".join(c for c in str(val) if c.isdigit() or c == '.')
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0


def calculate_nutrition_for_range(start_date_str, end_date_str):
    """Calculate daily nutrient totals and weekly averages for the date range."""
    client = MealieClient()
    meal_plans = client.get_meal_plan(start_date_str, end_date_str)
    
    daily_nutrients = {}
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    current_date = start_date
    while current_date <= end_date:
        d_str = current_date.strftime("%Y-%m-%d")
        daily_nutrients[d_str] = {
            "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
            "fiber": 0.0, "sodium": 0.0, "sugar": 0.0, "cholesterol": 0.0
        }
        current_date += timedelta(days=1)
        
    for item in meal_plans:
        d_str = item['date']
        if d_str not in daily_nutrients:
            continue
            
        entry_type = item['entryType']
        title = item.get('title') or ""
        recipe_id = item.get('recipeId')
        
        nutrients = {
            "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
            "fiber": 0.0, "sodium": 0.0, "sugar": 0.0, "cholesterol": 0.0
        }
        
        if entry_type == 'breakfast':
            matched = False
            for k, profile in BREAKFAST_PROFILES.items():
                if k.lower() in title.lower():
                    nutrients = profile
                    matched = True
                    break
            if not matched and title:
                nutrients = BREAKFAST_PROFILES["Toast with Jam"]
                
        elif entry_type == 'lunch':
            if "leftover" in title.lower() or not title:
                nutrients = LUNCH_LEFTOVER_PROFILE
            else:
                nutrients = BREAKFAST_PROFILES["Yogurt with Granola"]
                
        elif entry_type == 'dinner' and recipe_id:
            try:
                recipe = client.get_recipe_details(recipe_id)
                db_nutrition = recipe.get('nutrition', {})
                if db_nutrition:
                    nutrients = {
                        "calories": parse_nutrient_val(db_nutrition.get('calories')),
                        "protein": parse_nutrient_val(db_nutrition.get('proteinContent')),
                        "carbs": parse_nutrient_val(db_nutrition.get('carbohydrateContent')),
                        "fat": parse_nutrient_val(db_nutrition.get('fatContent')),
                        "fiber": parse_nutrient_val(db_nutrition.get('fiberContent')),
                        "sodium": parse_nutrient_val(db_nutrition.get('sodiumContent')),
                        "sugar": parse_nutrient_val(db_nutrition.get('sugarContent')),
                        "cholesterol": parse_nutrient_val(db_nutrition.get('cholesterolContent'))
                    }
            except Exception as e:
                print(f"Error fetching recipe nutrition for {recipe_id}: {e}")
                
        for k in daily_nutrients[d_str]:
            daily_nutrients[d_str][k] += nutrients.get(k, 0.0)
            
    active_days = 0
    averages = {k: 0.0 for k in RDA}
    
    for d_str, nut in daily_nutrients.items():
        if nut['calories'] > 100:
            active_days += 1
            for k in averages:
                averages[k] += nut.get(k, 0.0)
                
    if active_days > 0:
        for k in averages:
            averages[k] = round(averages[k] / active_days, 1)
            
    return daily_nutrients, averages


# ---------------------------------------------------------------------------
# AI-powered: strip quantities/units from a staple name
# ---------------------------------------------------------------------------

def clean_staple_name(note: str) -> str:
    """
    Use Gemini to intelligently remove any quantity, number, or unit of measure
    from a grocery item string, returning only the item name, properly capitalised.
    Falls back to the raw note if the AI call fails.
    """
    if not note:
        return ""
    try:
        prompt = (
            "You are a grocery list editor. "
            "Given the following grocery item string, remove any leading or embedded quantity, "
            "number, fraction, or unit of measure (e.g. '6 tbsp', '1 gallon', '2 cloves', '10 oz') "
            "and return ONLY the clean item name, properly Title Cased. "
            "Do not add any explanation. Return a JSON object with a single key 'name'.\n\n"
            f"Item: {note}"
        )
        result = json.loads(call_gemini(prompt, expect_json=True))
        clean = result.get("name", "").strip()
        return clean if clean else note.strip().capitalize()
    except Exception as e:
        print(f"[AI] clean_staple_name fallback for '{note}': {e}")
        # Simple numeric-prefix fallback
        fallback = re.sub(r'^[\d\.\s/]+(\w+\s+)?', '', note.strip()).strip()
        return fallback.capitalize() if fallback else note.strip().capitalize()


def find_matching_staple(ing_note, staples):
    """
    Check if a recipe ingredient note matches any staple item.
    Returns the staple item if found, else None.
    """
    ing_lower = ing_note.lower()
    for s_item in staples:
        s_note_lower = s_item['note'].lower()
        s_clean = clean_staple_name(s_note_lower).lower()
        
        # Match if the cleaned staple name is a distinct word in the ingredient note
        pattern = r'\b' + re.escape(s_clean) + r'\b'
        if re.search(pattern, ing_lower) or s_clean in ing_lower:
            return s_item
    return None


def clean_staples_list(client):
    """
    Fetch all items in the Staples shopping list and update any items
    that have quantities or units in their names to be clean/amount-free.
    """
    try:
        staples = client.get_shopping_list_items(STAPLES_LIST_ID)
        for item in staples:
            note = item.get('note')
            if not note:
                continue
            clean_name = clean_staple_name(note)
            if clean_name != note or item.get('quantity') != 0.0:
                payload = {
                    'id': item['id'],
                    'shoppingListId': item['shoppingListId'],
                    'note': clean_name,
                    'display': clean_name,
                    'checked': item['checked'],
                    'position': item['position'],
                    'quantity': 0.0,
                    'labelId': item.get('labelId')
                }
                client.update_shopping_list_item(item['id'], payload)
    except Exception as e:
        print(f"Error cleaning staples list: {e}")


def sync_shopping_list(start_date_str, end_date_str, low_staples_ids=[]):
    """Sync active shopping list based on scheduled recipes and low staples, reconciling quantities for staples."""
    client = MealieClient()
    
    # Automatically clean the staples list first
    clean_staples_list(client)
    
    print(f"Syncing shopping list for range {start_date_str} to {end_date_str}...")
    meal_plans = client.get_meal_plan(start_date_str, end_date_str)
    
    ingredients_to_add = []
    staples = client.get_shopping_list_items(STAPLES_LIST_ID)
    
    # Normalise low staples IDs for comparison
    low_staple_cleaned_ids = [s_id.replace('-', '') for s_id in low_staples_ids]
    
    # We maintain a set of added items (lowercase name/note) to prevent duplication
    added_items = set()
    
    # 1. Process manually checked low staples
    for s_id in low_staples_ids:
        s_id_clean = s_id.replace('-', '')
        matched_staple = None
        for item in staples:
            item_id_clean = item['id'].replace('-', '')
            if item_id_clean == s_id_clean:
                matched_staple = item
                break
                
        if matched_staple:
            note = matched_staple['note']
            clean_name = clean_staple_name(note)
            
            # Prevent duplicates
            if clean_name.lower() in added_items:
                continue
                
            note_tagged = tag_dirty_dozen(clean_name)
            ingredients_to_add.append({
                "shoppingListId": ACTIVE_LIST_ID,
                "note": note_tagged,
                "display": note_tagged,
                "checked": False,
                "quantity": 0.0  # Setting quantity to 0.0 hides quantity in Mealie's UI
            })
            added_items.add(clean_name.lower())
            
    # 2. Process recipe ingredients
    for plan in meal_plans:
        if plan['entryType'] == 'dinner' and plan.get('recipeId'):
            try:
                recipe = client.get_recipe_details(plan['recipeId'])
                recipe_ingredients = recipe.get('recipeIngredient', [])
                for ing in recipe_ingredients:
                    note = ing.get('display') or ing.get('note')
                    if note:
                        # Check if this ingredient matches any staple
                        matched_s_item = find_matching_staple(note, staples)
                        
                        if matched_s_item:
                            # It is a staple. Check if it is marked as low
                            s_item_id_clean = matched_s_item['id'].replace('-', '')
                            if s_item_id_clean in low_staple_cleaned_ids:
                                # It is low! We want to add it, but using the clean amount-free name
                                clean_name = clean_staple_name(matched_s_item['note'])
                                if clean_name.lower() not in added_items:
                                    note_tagged = tag_dirty_dozen(clean_name)
                                    ingredients_to_add.append({
                                        "shoppingListId": ACTIVE_LIST_ID,
                                        "note": note_tagged,
                                        "display": note_tagged,
                                        "checked": False,
                                        "quantity": 0.0  # 0.0 quantity for clean display
                                    })
                                    added_items.add(clean_name.lower())
                            # If it is NOT marked as low, we skip adding it entirely (stock is sufficient)
                            continue
                        
                        # It is NOT a staple, so we add it as a normal ingredient with its original quantities
                        note_tagged = tag_dirty_dozen(note)
                        # Avoid duplicates for identical recipe ingredients
                        if note_tagged.lower() not in added_items:
                            ingredients_to_add.append({
                                "shoppingListId": ACTIVE_LIST_ID,
                                "note": note_tagged,
                                "display": note_tagged,
                                "checked": False,
                                "quantity": 1.0
                            })
                            added_items.add(note_tagged.lower())
            except Exception as e:
                print(f"Error fetching recipe ingredients for {plan['recipeId']}: {e}")
                
    client.clear_shopping_list(ACTIVE_LIST_ID)
    client.add_shopping_list_items_bulk(ingredients_to_add)
    print(f"Successfully synced {len(ingredients_to_add)} items to active shopping list.")


def find_recipe_for_ingredient(ingredient):
    """Look for a recipe in Mealie containing the ingredient in its name or ingredients notes."""
    client = MealieClient()
    recipes = client.get_all_recipes()
    ing_lower = ingredient.lower()
    
    # 1. Match recipe name
    for r in recipes:
        if ing_lower in r['name'].lower():
            return r['id']
            
    # 2. Check database recipes_ingredients notes
    db_path = os.getenv('MEALIE_DB_PATH', '/mealie-data/mealie.db')
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT recipe_id FROM recipes_ingredients WHERE note LIKE ?", (f"%{ing_lower}%",))
            row = cursor.fetchone()
            conn.close()
            if row:
                return format_uuid(row[0])
        except Exception as e:
            print(f"Error querying SQLite for ingredients: {e}")
            
    return None


def find_and_import_recipe(ingredient):
    """Search DuckDuckGo HTML for a recipe, and attempt to scrape and import it into Mealie."""
    print(f"No existing recipe using '{ingredient}'. Searching the web...")
    meat_kws = {'chicken', 'turkey', 'pork', 'salmon', 'fish', 'tuna', 'shrimp', 'beef', 'steak', 'meat'}
    if any(kw in ingredient.lower() for kw in meat_kws):
        query = f"healthy recipe with {ingredient}"
    else:
        query = f"healthy vegetarian recipe with {ingredient}"
    data = urllib.parse.urlencode({'q': query}).encode()
    url = 'https://html.duckduckgo.com/html/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        html = urllib.request.urlopen(req).read().decode('utf-8')
        links = re.findall(r'href=\"(https?://[^\"]+)\"', html)
        
        recipe_links = []
        for l in links:
            if 'uddg=' in l:
                parsed_url = urllib.parse.urlparse(l)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if 'uddg' in query_params:
                    l = query_params['uddg'][0]
            
            l_lower = l.lower()
            if 'duckduckgo.com' in l_lower or 'yandex.com' in l_lower:
                continue
            if any(kw in l_lower for kw in ['recipe', 'food', 'cook', 'kitchen', 'eat']):
                if l not in recipe_links:
                    recipe_links.append(l)
                    
        print(f"Found recipe links for '{ingredient}': {recipe_links[:5]}")
        
        client = MealieClient()
        for link in recipe_links[:5]:
            try:
                print(f"Scraping from: {link}")
                payload = {
                    "url": link,
                    "includeCategories": True,
                    "includeTags": True
                }
                r = requests.post(f"{client.api_url}/api/recipes/create/url", json=payload, headers=client.headers)
                if r.status_code in [200, 201]:
                    new_recipe_slug = r.json()
                    print(f"Scraped and imported recipe successfully! Slug: {new_recipe_slug}")
                    return True
            except Exception as ex:
                print(f"Failed to scrape from {link}: {ex}")
                
    except Exception as e:
        print(f"Error searching DuckDuckGo: {e}")
    return False


def format_uuid(r_id):
    """Convert a 32-character hex string to a 36-character UUID string with dashes."""
    if r_id and '-' not in r_id and len(r_id) == 32:
        return f"{r_id[:8]}-{r_id[8:12]}-{r_id[12:16]}-{r_id[16:20]}-{r_id[20:]}"
    return r_id

def get_recipes_from_db():
    """Fetch all recipes with their nutrition, tags, and ingredients from Mealie SQLite DB."""
    db_path = os.getenv('MEALIE_DB_PATH', '/mealie-data/mealie.db')
    if not os.path.exists(db_path):
        # Fallback to MealieClient API if database is not available
        try:
            client = MealieClient()
            return client.get_all_recipes()
        except Exception as e:
            print(f"Error fetching via API fallback: {e}")
            return []
            
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. Fetch recipes and their nutrition
        query = """
            SELECT 
                r.id, r.name, r.slug, r.description,
                n.calories, n.fiber_content, n.protein_content, n.carbohydrate_content,
                n.fat_content, n.sodium_content, n.sugar_content, n.cholesterol_content
            FROM recipes r
            LEFT JOIN recipe_nutrition n ON r.id = n.recipe_id
        """
        cursor.execute(query)
        recipes = [dict(row) for row in cursor.fetchall()]
        
        # 2. Fetch tags
        cursor.execute("""
            SELECT rt.recipe_id, t.name 
            FROM recipes_to_tags rt
            JOIN tags t ON rt.tag_id = t.id
        """)
        tags_rows = cursor.fetchall()
        recipe_tags = {}
        for row in tags_rows:
            r_id = row[0]
            tag_name = row[1]
            if r_id not in recipe_tags:
                recipe_tags[r_id] = []
            recipe_tags[r_id].append(tag_name.lower())
            
        # 3. Fetch ingredients (using note and original_text)
        cursor.execute("""
            SELECT recipe_id, note, original_text
            FROM recipes_ingredients
        """)
        ing_rows = cursor.fetchall()
        recipe_ings = {}
        for row in ing_rows:
            r_id = row[0]
            note = row[1] or ""
            orig = row[2] or ""
            ing_text = f"{note} {orig}".strip()
            if r_id not in recipe_ings:
                recipe_ings[r_id] = []
            recipe_ings[r_id].append(ing_text.lower())
            
        # 4. Fetch instructions for Blackstone text checks
        cursor.execute("""
            SELECT recipe_id, text
            FROM recipe_instructions
        """)
        inst_rows = cursor.fetchall()
        recipe_insts = {}
        for row in inst_rows:
            r_id = row[0]
            text = row[1] or ""
            if r_id not in recipe_insts:
                recipe_insts[r_id] = []
            recipe_insts[r_id].append(text.lower())

        conn.close()
        
        formatted_recipes = []
        for r in recipes:
            r_id = r['id']
            api_id = format_uuid(r_id)
            r['id'] = api_id
            r['tags'] = recipe_tags.get(r_id, [])
            r['ingredients'] = recipe_ings.get(r_id, [])
            r['instructions'] = recipe_insts.get(r_id, [])
            formatted_recipes.append(r)
            
        return formatted_recipes
    except Exception as e:
        print(f"Error fetching recipes from DB: {e}")
        # Fallback to API
        try:
            client = MealieClient()
            return client.get_all_recipes()
        except:
            return []

# ---------------------------------------------------------------------------
# AI-powered: parse free-text meal exclusions
# ---------------------------------------------------------------------------

def parse_exclusions(text: str) -> dict:
    """
    Use Gemini to interpret a free-text description of which meals to skip,
    and return a structured dict: {"Monday": ["dinner"], "Friday": ["breakfast", "dinner"], ...}.
    Valid meal values are: breakfast, lunch, dinner.
    Valid day keys are: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.
    """
    if not text or not text.strip():
        return {}

    today = datetime.now()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    week_dates = {
        (next_monday + timedelta(days=i)).strftime("%A"): (next_monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(7)
    }

    prompt = (
        "You are a meal planning assistant. The user has described which meals they want to SKIP "
        "or OPT OUT of for the upcoming week. "
        f"The week runs: {', '.join(f'{d} ({dt})' for d, dt in week_dates.items())}.\n\n"
        "Based on the user's input below, return a JSON object where:\n"
        "  - Keys are day names: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday\n"
        "  - Values are arrays of meal names to SKIP for that day\n"
        "  - Valid meal names are: breakfast, lunch, dinner\n"
        "  - Only include days where at least one meal should be skipped\n"
        "  - If no meals should be skipped, return an empty object {}\n\n"
        "Examples:\n"
        "  Input: 'skip dinner Saturday and Sunday'\n"
        "  Output: {\"Saturday\": [\"dinner\"], \"Sunday\": [\"dinner\"]}\n\n"
        "  Input: 'we are eating out all week'\n"
        "  Output: {\"Monday\": [\"dinner\"], \"Tuesday\": [\"dinner\"], \"Wednesday\": [\"dinner\"], "
        "\"Thursday\": [\"dinner\"], \"Friday\": [\"dinner\"], \"Saturday\": [\"dinner\"], \"Sunday\": [\"dinner\"]}\n\n"
        "  Input: 'Monday through Wednesday no cooking at all'\n"
        "  Output: {\"Monday\": [\"breakfast\", \"lunch\", \"dinner\"], \"Tuesday\": [\"breakfast\", \"lunch\", \"dinner\"], "
        "\"Wednesday\": [\"breakfast\", \"lunch\", \"dinner\"]}\n\n"
        f"User input: {text}\n\n"
        "Return ONLY the JSON object, nothing else."
    )

    try:
        raw = call_gemini(prompt, expect_json=True)
        result = json.loads(raw)
        # Validate structure
        valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
        valid_meals = {"breakfast", "lunch", "dinner"}
        exclusions = {}
        for day, meals in result.items():
            if day in valid_days and isinstance(meals, list):
                cleaned_meals = [m for m in meals if m in valid_meals]
                if cleaned_meals:
                    exclusions[day] = cleaned_meals
        print(f"[AI] Parsed exclusions: {exclusions}")
        return exclusions
    except Exception as e:
        print(f"[AI] parse_exclusions failed: {e} — no exclusions applied")
        return {}


def generate_weekly_plan(start_date_str, end_date_str, exclude_text="", freezer_items="", special_requests="", low_staples_ids=[]):
    """Generate weekly plan using an intelligent rule-based scoring engine, schedule in Mealie, and sync active shopping list."""
    client = MealieClient()
    
    # 1. Handle Freezer Items Scraping & Import
    priority_recipe_ids = []
    if freezer_items:
        items = [i.strip() for i in freezer_items.split(",") if i.strip()]
        for item in items:
            recipe_id = find_recipe_for_ingredient(item)
            if not recipe_id:
                if find_and_import_recipe(item):
                    recipe_id = find_recipe_for_ingredient(item)
            if recipe_id and recipe_id not in priority_recipe_ids:
                priority_recipe_ids.append(recipe_id)
                
    # 2. Fetch all recipes (freshly imported or from DB)
    all_recipes = get_recipes_from_db()
    
    # 3. Clean and filter recipes (exclude processed meats via PROCESSED_MEATS constant)
    allowed_recipes = []
    
    for r in all_recipes:
        name_lower = r['name'].lower()
        slug_lower = r.get('slug', '').lower()
        desc_lower = r.get('description', '').lower() if r.get('description') else ''
        tags = [t.lower() for t in r.get('tags', [])]
        
        all_text = f"{name_lower} {slug_lower} {desc_lower} " + " ".join(tags)
        
        # Cache all_text on the recipe dict to reuse in the scoring loop below
        r['_all_text'] = all_text
        
        if any(kw in all_text for kw in PROCESSED_MEATS):
            continue
            
        allowed_recipes.append(r)
        
    if not allowed_recipes:
        print("Warning: No recipes left after filtering! Using unfiltered recipes.")
        allowed_recipes = all_recipes

    # 4. Use Gemini to select and rank dinners for the week
    #    We tell it everything: family preferences, dietary rules, special requests,
    #    freezer items, and the full allowed recipe catalogue.
    #    It returns an ordered list of recipe IDs — one per dinner slot.

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    num_days = (end_date - start_date).days + 1
    exclusions = parse_exclusions(exclude_text)
    dinner_days = [
        (start_date + timedelta(days=i)).strftime("%A")
        for i in range(num_days)
        if 'dinner' not in exclusions.get((start_date + timedelta(days=i)).strftime("%A"), [])
    ]
    num_dinners = len(dinner_days)

    # Build a compact recipe catalogue for the AI prompt
    recipe_catalogue = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": (r.get("description") or "")[:120],
            "tags": r.get("tags", []),
            "fiber_g": r.get("fiber_content"),
            "ingredients_preview": ", ".join(r.get("ingredients", [])[:5]),
            "instructions_preview": " ".join(r.get("instructions", []))[:80]
        }
        for r in allowed_recipes
    ]

    selection_prompt = (
        "You are a meal planner for the Crosty family. "
        "Your job is to select the best dinners for the upcoming week from the recipe catalogue below, "
        "following all family rules and preferences.\n\n"
        "=== FAMILY DIETARY RULES ===\n"
        "- Avoid processed meats entirely: sausage, hotdog, chorizo, salami, pepperoni, bacon, ham, pancetta\n"
        "- Beef and steak are expensive and eaten seldom — give them a significant penalty unless specifically requested\n"
        "- Pork is acceptable\n"
        "- Prefer high-fiber meals where possible\n"
        "- Variety matters — do not repeat the same recipe more than once in a week\n"
        "- The family enjoys: salmon, chicken, turkey, vegetarian dishes, Mexican, Italian, and Asian cuisine\n"
        "- The family has a Blackstone griddle and enjoys using it occasionally\n\n"
        "=== THIS WEEK'S CONTEXT ===\n"
        f"- Dinner nights this week: {', '.join(dinner_days)}\n"
        f"- Number of dinners to plan: {num_dinners}\n"
        f"- Freezer items to prioritise (use recipes containing these first): {freezer_items or 'none'}\n"
        f"- Special requests from the family: {special_requests or 'none'}\n\n"
        "=== RECIPE CATALOGUE (JSON) ===\n"
        f"{json.dumps(recipe_catalogue, indent=2)}\n\n"
        "=== YOUR TASK ===\n"
        f"Select exactly {num_dinners} recipe IDs from the catalogue above, one for each dinner night. "
        "Return them in order (first ID = first dinner night). "
        "Prioritise variety, family preferences, freezer items, and special requests. "
        "Return a JSON object with a single key 'dinner_ids' containing the ordered list of recipe ID strings. "
        "Example: {\"dinner_ids\": [\"abc123\", \"def456\", ...]}"
    )

    try:
        raw = call_gemini(selection_prompt, expect_json=True)
        ai_result = json.loads(raw)
        selected_ids = ai_result.get("dinner_ids", [])
        print(f"[AI] Selected {len(selected_ids)} dinner recipe IDs: {selected_ids}")
    except Exception as e:
        print(f"[AI] Recipe selection failed: {e} — falling back to random selection")
        random.shuffle(allowed_recipes)
        selected_ids = [r["id"] for r in allowed_recipes[:num_dinners]]

    # Map selected IDs back to recipe objects (validate against catalogue)
    id_to_recipe = {r["id"]: r for r in allowed_recipes}
    clean_recipes = [id_to_recipe[rid] for rid in selected_ids if rid in id_to_recipe]
    # If AI hallucinated IDs or we got too few, pad with random allowed recipes
    used_ids = {r["id"] for r in clean_recipes}
    remaining = [r for r in allowed_recipes if r["id"] not in used_ids]
    random.shuffle(remaining)
    clean_recipes = clean_recipes + remaining
    
    # 5. Build calendar meals list
    meals = []
    current_date = start_date
    recipe_index = 0
    # Derive breakfast rotation directly from the nutrition profiles so the two can't drift
    breakfasts = list(BREAKFAST_PROFILES.keys())
    while current_date <= end_date:
        d_str = current_date.strftime("%Y-%m-%d")
        day_name = current_date.strftime("%A")
        
        day_exclusions = exclusions.get(day_name, [])
        
        # Schedule breakfast
        if 'breakfast' in day_exclusions:
            meals.append({"date": d_str, "entryType": "breakfast", "title": "Skipped", "recipeId": None})
        else:
            bf = breakfasts[current_date.weekday() % len(breakfasts)]
            meals.append({"date": d_str, "entryType": "breakfast", "title": bf, "recipeId": None})
            
        # Schedule lunch
        if 'lunch' in day_exclusions:
            meals.append({"date": d_str, "entryType": "lunch", "title": "Skipped", "recipeId": None})
        else:
            meals.append({"date": d_str, "entryType": "lunch", "title": "Leftovers", "recipeId": None})
        
        # Schedule dinner
        if 'dinner' in day_exclusions:
            meals.append({"date": d_str, "entryType": "dinner", "title": "Eating Out", "recipeId": None})
        else:
            if recipe_index >= len(clean_recipes):
                recipe_index = 0
                
            recipe = clean_recipes[recipe_index]
            meals.append({"date": d_str, "entryType": "dinner", "title": "", "recipeId": recipe['id']})
            recipe_index += 1
            
        current_date += timedelta(days=1)
        
    # 6. Execute the generated plan to Mealie
    # Delete existing entries in range
    existing_plans = client.get_meal_plan(start_date_str, end_date_str)
    for p in existing_plans:
        client.delete_meal_plan_entry(p['id'])
        
    # Schedule all meals
    for m in meals:
        client.schedule_meal(
            date_str=m['date'],
            entry_type=m['entryType'],
            title=m.get('title') or "",
            recipe_id=m.get('recipeId')
        )
        
    # 7. Sync active shopping list with selected low staples
    sync_shopping_list(start_date_str, end_date_str, low_staples_ids)
    print(f"Rule-based plan successfully generated and scheduled for {start_date_str} to {end_date_str}.")



