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
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Constants & family configurations (from config.py)
from config import (
    ACTIVE_LIST_ID, STAPLES_LIST_ID, DIRTY_DOZEN, PROCESSED_MEATS, BREAKFAST_PROFILES,
    LUNCH_LEFTOVER_PROFILE, RDA, FAMILY_RECIPIENT_EMAILS, FAMILY_DIETARY_RULES_PROMPT,
    FAMILY_NAMES, load_skill_md
)

# --- AI Skill Prompts (Loaded from .md files as raw strings) ---
_RECIPE_FINDER_SKILL_DEFINITION = load_skill_md('recipe-finder')
_STAPLE_NAME_CLEANING_SKILL_DEFINITION = load_skill_md('staple-name-cleaning')
_MEAL_EXCLUSION_PARSING_SKILL_DEFINITION = load_skill_md('meal-exclusion-parsing')
_WEEKLY_MEAL_SELECTION_SKILL_DEFINITION = load_skill_md('weekly-meal-selection')
_SHOPPING_LIST_SYNC_SKILL_DEFINITION = load_skill_md('shopping-list-sync')



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
    model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
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

    print("--- AI PROMPT ---")
    print(prompt)
    print("-------------------")

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    print("--- AI RAW RESPONSE ---")
    print(json.dumps(data, indent=2))
    print("-----------------------")
    return data["candidates"][0]["content"]["parts"][0]["text"]

def get_mealie_token():
    """Retrieve the API token from the SQLite DB volume or fallback to MEALIE_TOKEN env var."""
    db_paths = [
        '/mealie-data/mealie.db',
        '/app/data/mealie.db',
        '/var/lib/docker/volumes/mealie_mealie-data/_data/mealie.db'
    ]
    for path in db_paths:
        if os.path.exists(path):
            try:
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                cursor.execute("SELECT token FROM long_live_tokens WHERE name = 'AntigravityToken'")
                row = cursor.fetchone()
                # If 'AntigravityToken' is not found, try 'Gemini' as a fallback
                if not row:
                    cursor.execute("SELECT token FROM long_live_tokens WHERE name = 'Gemini'")
                    row = cursor.fetchone()
                conn.close()
                if row and row[0]:
                    print(f"Loaded auth token dynamically from DB: {path}")
                    return row[0]
            except Exception as e:
                print(f"Error reading token from SQLite {path}: {e}")
                
    # Fallback to env variable
    token = os.getenv('MEALIE_TOKEN')
    if token and token != 'your_mealie_api_token_here':
        return token
        
    raise RuntimeError("Mealie auth token could not be retrieved from DB volume or MEALIE_TOKEN environment variable.")


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
        self._recipe_details_cache = {}

    def get_users(self):
        """Fetch all users registered in Mealie."""
        r = requests.get(f"{self.api_url}/api/users", headers=self.headers)
        r.raise_for_status()
        return r.json().get('items', [])

    def get_all_recipes(self):
        """Fetch all recipes from Mealie."""
        r = requests.get(f"{self.api_url}/api/recipes?perPage=200", headers=self.headers)
        r.raise_for_status()
        return r.json().get('items', [])

    def get_recipe_details(self, recipe_id):
        """Fetch full details of a specific recipe, using a cache."""
        if recipe_id in self._recipe_details_cache:
            return self._recipe_details_cache[recipe_id]

        r = requests.get(f"{self.api_url}/api/recipes/{recipe_id}", headers=self.headers)
        r.raise_for_status()
        details = r.json()
        self._recipe_details_cache[recipe_id] = details
        return details

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

# ---------------------------------------------------------------------------
# AI-powered functions
# ---------------------------------------------------------------------------

def tag_dirty_dozen(note):
    """If an ingredient belongs to the 'Dirty Dozen', automatically append '(Buy Organic)'."""
    if not note:
        return note
        
    note_lower = note.lower()
    for item in DIRTY_DOZEN:
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

    recipients = FAMILY_RECIPIENT_EMAILS

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

def clean_staple_names_batch(notes: list) -> dict:
    """
    Use a single Gemini call to clean an entire list of staple name strings at once, delegating to the AI skill.
    Falls back to simple regex stripping per item if the AI call fails.
    """
    if not notes:
        return {}

    def _regex_fallback(note):
        cleaned = note.strip()
        # Remove leading numbers, fractions, and symbols like ¹/₂
        cleaned = re.sub(r'^[\d\.\s/½⅓¼¾⅛⅖⅗⅘⅙⅚⅛\u00b2\u00b3\u00b9\u2070\u2074-\u2079\u2080-\u2089/]+', '', cleaned).strip()
        # Remove common units if they are the first word
        units_pattern = r'^(?:lbs?|oz|ounces?|g|grams?|kg|cups?|tbsps?|tablespoons?|tsps?|teaspoons?|cloves?|cans?|packets?|packages?|slices?|jars?|tins?)\b\s*'
        cleaned = re.sub(units_pattern, '', cleaned, flags=re.IGNORECASE).strip()
        return cleaned.capitalize() if cleaned else note.strip().capitalize()

    try:
        items_json = json.dumps(notes)
        prompt = (
            """You are an expert in the 'Mealie Staple Name Cleaning Skill'.

""" +
            _STAPLE_NAME_CLEANING_SKILL_DEFINITION + """

### CONTEXT FOR THIS INVOCATION:
""" +
            f"Items: {items_json}\n\n" +
            "Return ONLY the JSON object as specified in the skill definition."
        )
        result = json.loads(call_gemini(prompt, expect_json=True))
        return {note: result.get(note, _regex_fallback(note)) for note in notes}
    except Exception as e:
        print(f"[AI] clean_staple_names_batch fallback: {e}")
        return {note: _regex_fallback(note) for note in notes}

def clean_staple_name(note: str) -> str:
    """
    Clean a single staple name. Delegates to the batch function for a single item.
    """
    if not note:
        return ""
    result = clean_staple_names_batch([note])
    return result.get(note, note.strip().capitalize())

def sync_shopping_list(start_date_str, end_date_str, low_staples_ids=[], progress_callback=None):
    """Sync active shopping list based on scheduled recipes and low staples, reconciling quantities programmatically."""
    client = MealieClient()
    
    print(f"Starting programmatic shopping list sync for {start_date_str} to {end_date_str}...")
    if progress_callback:
        progress_callback("Programmatic shopping list sync started...", 90)
    try:
        # 1. Fetch data from Mealie
        meal_plans = client.get_meal_plan(start_date_str, end_date_str)
        staples = client.get_shopping_list_items(STAPLES_LIST_ID)
        
        # Build set of low staples IDs (hyphen-insensitive)
        low_ids_clean = {s_id.replace('-', '') for s_id in low_staples_ids}
        
        # 2. Clean all staples in batch
        if progress_callback:
            progress_callback("Cleaning staple names in batch using AI/rules...", 92)
        staple_notes = [item['note'] for item in staples]
        cleaned_staple_map = clean_staple_names_batch(staple_notes)
        
        # Build lookup maps for staples: lowercase cleaned name -> staple item
        # and raw ID -> staple item
        staple_lookup = {}
        for item in staples:
            raw_note = item['note']
            cleaned_name = cleaned_staple_map.get(raw_note, raw_note).strip()
            # Save both Title Cased cleaned name and lowercase cleaned name
            item['_cleaned_name'] = cleaned_name
            staple_lookup[cleaned_name.lower()] = item
            
        ingredients_to_add = {} # cleaned_name_lower -> item_dict
        
        def add_to_list(name, quantity=1.0):
            cleaned = name.strip()
            cleaned_lower = cleaned.lower()
            if cleaned_lower == 'water':
                return
            if cleaned_lower in ingredients_to_add:
                ingredients_to_add[cleaned_lower]['quantity'] += quantity
            else:
                tagged = tag_dirty_dozen(cleaned)
                ingredients_to_add[cleaned_lower] = {
                    "shoppingListId": ACTIVE_LIST_ID,
                    "note": tagged,
                    "quantity": quantity,
                    "checked": False
                }
                
        # 3. Process manually marked low staples first
        for item in staples:
            clean_id = item['id'].replace('-', '')
            if clean_id in low_ids_clean:
                cleaned_name = item.get('_cleaned_name', item['note'])
                add_to_list(cleaned_name, quantity=1.0)
                
        # 4. Fetch details of all recipes in the meal plan to extract ingredients
        if progress_callback:
            progress_callback("Extracting ingredients from dinner recipes...", 94)
        recipe_ingredients_by_dinner = []
        raw_ing_texts = []
        
        for p in meal_plans:
            # We only sync ingredients for scheduled dinner recipes
            if p['entryType'] == 'dinner' and p.get('recipeId'):
                try:
                    r_details = client.get_recipe_details(p['recipeId'])
                    recipe_ings = []
                    for ing in r_details.get('recipeIngredient', []):
                        # Extract the ingredient text
                        ing_text = ""
                        food = ing.get('food')
                        if isinstance(food, dict) and food.get('name'):
                            ing_text = food.get('name')
                        elif ing.get('note'):
                            ing_text = ing.get('note')
                        else:
                            ing_text = ing.get('display') or ing.get('originalText') or ""
                        ing_text = ing_text.strip()
                        if ing_text:
                            qty = ing.get('quantity') or 1.0
                            recipe_ings.append((ing_text, qty))
                            raw_ing_texts.append(ing_text)
                    recipe_ingredients_by_dinner.append((p, recipe_ings))
                except Exception as e:
                    print(f"Error fetching recipe details for recipe ID {p.get('recipeId')}: {e}")
                    
        # 5. Clean all recipe ingredient names in batch
        if progress_callback:
            progress_callback("Cleaning recipe ingredients using AI/rules...", 96)
        unique_ing_texts = list(set(raw_ing_texts))
        cleaned_ing_map = clean_staple_names_batch(unique_ing_texts)
        
        # 6. Reconcile dinner recipe ingredients
        for p, recipe_ings in recipe_ingredients_by_dinner:
            for raw_ing, qty in recipe_ings:
                cleaned_name = cleaned_ing_map.get(raw_ing, raw_ing).strip()
                cleaned_name_lower = cleaned_name.lower()
                
                # Check if it matches any staple
                matched_staple = None
                for c_staple_name_lower, staple_item in staple_lookup.items():
                    # Handle exact, singular, and plural matching
                    if (cleaned_name_lower == c_staple_name_lower or 
                        cleaned_name_lower + 's' == c_staple_name_lower or 
                        c_staple_name_lower + 's' == cleaned_name_lower):
                        matched_staple = staple_item
                        break
                
                if matched_staple:
                    # If it is a staple, only add it if it was manually marked as low
                    clean_staple_id = matched_staple['id'].replace('-', '')
                    if clean_staple_id in low_ids_clean:
                        add_to_list(matched_staple.get('_cleaned_name', matched_staple['note']), quantity=1.0)
                else:
                    # If it is not a staple, always add it with its recipe quantity!
                    add_to_list(cleaned_name, quantity=qty)
                    
        ingredients_list = list(ingredients_to_add.values())

        # 7. Clear the active list and add new items
        if progress_callback:
            progress_callback("Clearing active shopping list in Mealie...", 98)
        print(f"Clearing active shopping list {ACTIVE_LIST_ID}...")
        client.clear_shopping_list(ACTIVE_LIST_ID)
        
        if progress_callback:
            progress_callback(f"Bulk adding {len(ingredients_list)} items to active shopping list...", 99)
        print(f"Adding {len(ingredients_list)} items in bulk to active shopping list...")
        client.add_shopping_list_items_bulk(ingredients_list)
        
        print(f"Programmatic shopping list sync completed successfully. Added {len(ingredients_list)} items.")
        if progress_callback:
            progress_callback("Shopping list synchronization complete!", 100)
        return True
    except Exception as e:
        print(f"Error during programmatic shopping list sync: {e}")
        if progress_callback:
            progress_callback(f"Error during shopping list sync: {str(e)}", 100)
        return False


def find_recipe_for_ingredient(ingredient):
    """Look for a recipe in Mealie containing the ingredient in its name or ingredients notes."""
    client = MealieClient()
    recipes = client.get_all_recipes()
    ing_lower = ingredient.lower()
    
    # 1. Match recipe name
    for r in recipes:
        if ing_lower in r['name'].lower():
            return r['id']
            
    # 2. Check recipe ingredients via Mealie API
    for r in recipes:
        for ing in r.get('recipeIngredient', []):
            note = ing.get('display') or ing.get('note')
            if note and ing_lower in note.lower():
                return r['id']            
    return None

def find_and_import_recipe(ingredient, existing_recipe_ids=[]) -> bool:
    """Search for and import a recipe into Mealie using the Mealie Recipe Finder Skill workflow."""
    print(f"No existing recipe using '{ingredient}'. Starting Recipe Finder workflow...")
    client = MealieClient()
    
    # 1. Construct Search Query
    meat_keywords = {'chicken', 'beef', 'salmon', 'turkey', 'pork', 'fish', 'steak', 'tuna', 'poultry', 'lamb'}
    ingredient_lower = ingredient.lower()
    has_meat = any(kw in ingredient_lower for kw in meat_keywords)
    if has_meat:
        query = f"healthy recipe with {ingredient}"
    else:
        query = f"healthy vegetarian recipe with {ingredient}"
        
    print(f"[Recipe Finder] Query: {query}")
    
    # 2. Perform Web Search (DuckDuckGo)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read()
    except Exception as e:
        print(f"[Recipe Finder] DuckDuckGo search request failed: {e}")
        return False
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # 3. Extract and Filter Potential Recipe Links
    potential_links = []
    recipe_keywords = {'recipe', 'food', 'cook', 'kitchen', 'eat'}
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        
        # Unwrap DuckDuckGo proxied links
        if 'uddg=' in href:
            parsed_href = urllib.parse.urlparse(href)
            query_params = urllib.parse.parse_qs(parsed_href.query)
            if 'uddg' in query_params:
                href = query_params['uddg'][0]
                
        # Filter search engine links
        parsed_url = urllib.parse.urlparse(href)
        domain = parsed_url.netloc.lower()
        if 'duckduckgo' in domain or 'yandex' in domain or 'google' in domain or 'bing' in domain:
            continue
            
        # Keyword filter
        href_lower = href.lower()
        if any(kw in href_lower for kw in recipe_keywords):
            if href not in potential_links:
                potential_links.append(href)
                if len(potential_links) >= 5:
                    break
                    
    print(f"[Recipe Finder] Found {len(potential_links)} potential links for validation.")
    
    # 4. AI-Driven Recipe Link Validation & 5. Import Validated Recipes
    for url in potential_links:
        print(f"[Recipe Finder] Fetching page for validation: {url}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                page_html = response.read()
        except Exception as e:
            print(f"[Recipe Finder] Failed to fetch {url}: {e}")
            continue
            
        page_soup = BeautifulSoup(page_html, 'html.parser')
        
        # Extract title and description
        title = page_soup.title.string.strip() if page_soup.title else ""
        desc_meta = page_soup.find('meta', attrs={'name': 'description'})
        description = desc_meta.get('content', '').strip() if desc_meta else ""
        
        # Quick programmatic listicle/collection filter
        import re
        title_lower = title.lower()
        is_listicle = False
        if re.search(r'\b\d+\s*\+?\s*(?:best|delicious|easy|healthy|quick|favorite|great|ideas|recipes|meals|dinners)\b', title_lower):
            is_listicle = True
        elif any(kw in title_lower for kw in ['roundup', 'round-up', 'listicles', 'collection of', 'best recipes', 'favorite recipes']):
            is_listicle = True
            
        if is_listicle:
            print(f"[Recipe Finder] Programmatically rejected listicle/collection: {title}")
            continue
        
        # Validation prompt
        validation_prompt = f"""You are a recipe link validator. Given a URL, page title, and description, determine if the content at the URL is a single, complete recipe.

CRITICAL RULES:
1. Ignore recipe collections, lists, roundups, compilations, galleries, directories, or blog posts about cooking (e.g. "21 Delicious Recipes", "15 Chicken Ideas", "Best ways to cook...").
2. Focus ONLY on pages that contain ONE specific, single recipe with concrete ingredients and instructions for that single dish.
3. If the title, URL, or description contains listicle keywords or patterns like "X recipes", "X best...", "X+ recipes", "roundup", "collection", "ideas for", respond with 'NO'.
4. Respond with 'YES' if it is a single specific recipe, and 'NO' if it is a collection or not a recipe page.
5. Respond with ONLY 'YES' or 'NO'. Do not add any other text, explanation, or punctuation.

URL: {url}
Title: {title}
Description: {description}
Is this a single recipe?
"""
        try:
            val_res = call_gemini(validation_prompt, expect_json=False).strip().upper()
            print(f"[Recipe Finder] Validation response for {url}: {val_res}")
            if "YES" in val_res:
                # Link validated! Attempt Mealie Import.
                print(f"[Recipe Finder] Link validated. Attempting to import into Mealie...")
                payload = {
                    "url": url,
                    "includeCategories": True,
                    "includeTags": True
                }
                # POST to Mealie API
                r = requests.post(f"{client.api_url}/api/recipes/create/url", json=payload, headers=client.headers, timeout=30)
                if r.status_code in (200, 201):
                    resp_json = r.json()
                    slug = resp_json if isinstance(resp_json, str) else resp_json.get('slug')
                    print(f"[Recipe Finder] Successfully imported recipe to Mealie. Slug: {slug}")
                    return True
                else:
                    print(f"[Recipe Finder] Mealie import failed with status {r.status_code}: {r.text}")
        except Exception as e:
            print(f"[Recipe Finder] Error validating or importing link {url}: {e}")
            
    print("[Recipe Finder] Failed to find or import a recipe.")
    return False


def get_recipes_from_db():
    """Fetch all recipes with their nutrition, tags, and ingredients from Mealie via API."""
    client = MealieClient()
    try:
        all_recipes_overview = client.get_all_recipes()
        detailed_recipes = []
        for r_overview in all_recipes_overview:
            try:
                full_recipe = client.get_recipe_details(r_overview['id'])
                
                nutrition = full_recipe.get('nutrition', {})
                
                ingredients_list = []
                for ing in full_recipe.get('recipeIngredient', []):
                    note = ing.get('note') or ""
                    orig = ing.get('originalText') or ""
                    ing_text = f"{note} {orig}".strip()
                    if ing_text:
                        ingredients_list.append(ing_text.lower())
                
                instructions_list = [i.get('text', '').lower() for i in full_recipe.get('recipeInstructions', [])]
                
                detailed_recipes.append({
                    'id': full_recipe['id'],
                    'name': full_recipe['name'],
                    'slug': full_recipe.get('slug'),
                    'description': full_recipe.get('description'),
                    'calories': parse_nutrient_val(nutrition.get('calories')),
                    'fiber_content': parse_nutrient_val(nutrition.get('fiberContent')),
                    'protein_content': parse_nutrient_val(nutrition.get('proteinContent')),
                    'carbohydrate_content': parse_nutrient_val(nutrition.get('carbohydrateContent')),
                    'fat_content': parse_nutrient_val(nutrition.get('fatContent')),
                    'sodium_content': parse_nutrient_val(nutrition.get('sodiumContent')),
                    'sugar_content': parse_nutrient_val(nutrition.get('sugarContent')),
                    'cholesterol_content': parse_nutrient_val(nutrition.get('cholesterolContent')),
                    'tags': [t.get('name', '').lower() for t in full_recipe.get('tags', [])],
                    'ingredients': ingredients_list,
                    'instructions': instructions_list
                })
            except Exception as e:
                print(f"Error fetching detailed recipe for {r_overview.get('id', 'Unknown')}: {e}")
        return detailed_recipes
    except Exception as e:
        print(f"Error fetching all recipes via API: {e}")
        return []

def parse_exclusions(text: str) -> dict:
    """Use Gemini to interpret a free-text description of which meals to skip, delegating to the AI skill."""
    if not text or not text.strip():
        return {}

    today = datetime.now()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    week_dates = {
        (next_monday + timedelta(days=i)).strftime("%A"): (next_monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(7)
    }

    prompt = (
        """You are an expert in the 'Mealie Meal Exclusion Parsing Skill'.

""" +
        _MEAL_EXCLUSION_PARSING_SKILL_DEFINITION +
        """

### CONTEXT FOR THIS INVOCATION:
""" +
        f"User input: {text}\n" +
        f"Week dates: {', '.join(f'{d} ({dt})' for d, dt in week_dates.items())}.\n\n" +
        "Return ONLY the JSON object as specified in the skill definition."
    )

    try:
        raw = call_gemini(prompt, expect_json=True)
        result = json.loads(raw)
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

def generate_weekly_plan(start_date_str, end_date_str, exclude_text="", freezer_items="", special_requests="", low_staples_ids=[], progress_callback=None):
    """Generate weekly plan using an AI-driven intelligent rule-based scoring engine and schedule in Mealie."""
    client = MealieClient()
    
    if progress_callback:
        progress_callback("Analyzing inputs and processing freezer items...", 5)
        
    priority_recipe_ids = []
    if freezer_items:
        items = [i.strip() for i in freezer_items.split(",") if i.strip()]
        for item in items:
            if progress_callback:
                progress_callback(f"Finding/importing recipe for freezer item: {item}...", 15)
            recipe_id = find_recipe_for_ingredient(item)
            if not recipe_id:
                if find_and_import_recipe(item, existing_recipe_ids=priority_recipe_ids): # Pass existing IDs for AI to avoid re-importing
                    recipe_id = find_recipe_for_ingredient(item)
            if recipe_id and recipe_id not in priority_recipe_ids:
                priority_recipe_ids.append(recipe_id)
                
    if progress_callback:
        progress_callback("Retrieving all recipes from Mealie database...", 30)
    all_recipes = get_recipes_from_db()
    
    allowed_recipes = []
    
    for r in all_recipes:
        name_lower = r['name'].lower()
        slug_lower = r.get('slug', '').lower()
        desc_lower = r.get('description', '').lower() if r.get('description') else ''
        tags = [t.lower() for t in r.get('tags', [])]
        
        all_text = f"{name_lower} {slug_lower} {desc_lower} " + " ".join(tags)
        
        r['_all_text'] = all_text
        
        if any(kw in all_text for kw in PROCESSED_MEATS):
            continue
            
        allowed_recipes.append(r)
        
    if not allowed_recipes:
        print("Warning: No recipes left after filtering! Using unfiltered recipes.")
        allowed_recipes = all_recipes
        
    if progress_callback:
        progress_callback("Filtering recipes and checking exclusions...", 40)

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
        """You are an expert in the 'Mealie Weekly Meal Selection Skill'.

""" +
        _WEEKLY_MEAL_SELECTION_SKILL_DEFINITION +
        """

### CONTEXT FOR THIS INVOCATION:
""" +
        f"- **Family Dietary Rules & Preferences**: {FAMILY_DIETARY_RULES_PROMPT}\n" +
        f"- **Dinner nights this week**: {', '.join(dinner_days)}\n" +
        f"- **Number of dinners to plan**: {num_dinners}\n" +
        f"- **Freezer items to prioritize**: {freezer_items or 'none'}\n" +
        f"- **Special requests from the family**: {special_requests or 'none'}\n\n" +
        f"### RECIPE CATALOGUE (JSON):\n" +
        f"{json.dumps(recipe_catalogue, indent=2)}\n\n" +
        "Return ONLY the JSON object as specified in the skill definition."
    )

    if progress_callback:
        progress_callback("Querying Gemini AI for optimal dinner plan based on rules...", 50)
    try:
        raw = call_gemini(selection_prompt, expect_json=True)
        ai_result = json.loads(raw)
        selected_ids = ai_result.get("dinner_ids", [])
        print(f"[AI] Selected {len(selected_ids)} dinner recipe IDs: {selected_ids}")
    except Exception as e:
        print(f"[AI] Recipe selection failed: {e} — falling back to random selection")
        if progress_callback:
            progress_callback(f"Gemini selection failed ({str(e)}), falling back to random selection...", 65)
        random.shuffle(allowed_recipes)
        selected_ids = [r["id"] for r in allowed_recipes[:num_dinners]]

    id_to_recipe = {r["id"]: r for r in allowed_recipes}
    clean_recipes = [id_to_recipe[rid] for rid in selected_ids if rid in id_to_recipe]
    used_ids = {r["id"] for r in clean_recipes}
    remaining = [r for r in allowed_recipes if r["id"] not in used_ids]
    random.shuffle(remaining)
    clean_recipes = clean_recipes + remaining
    
    meals = []
    current_date = start_date
    recipe_index = 0
    breakfasts = list(BREAKFAST_PROFILES.keys())
    while current_date <= end_date:
        d_str = current_date.strftime("%Y-%m-%d")
        day_name = current_date.strftime("%A")
        
        day_exclusions = exclusions.get(day_name, [])
        
        if 'breakfast' in day_exclusions:
            meals.append({"date": d_str, "entryType": "breakfast", "title": "Skipped", "recipeId": None})
        else:
            bf = breakfasts[current_date.weekday() % len(breakfasts)]
            meals.append({"date": d_str, "entryType": "breakfast", "title": bf, "recipeId": None})
            
        if 'lunch' in day_exclusions:
            meals.append({"date": d_str, "entryType": "lunch", "title": "Skipped", "recipeId": None})
        else:
            meals.append({"date": d_str, "entryType": "lunch", "title": "Leftovers", "recipeId": None})
        
        if 'dinner' in day_exclusions:
            meals.append({"date": d_str, "entryType": "dinner", "title": "Eating Out", "recipeId": None})
        else:
            if recipe_index >= len(clean_recipes):
                recipe_index = 0
                
            recipe = clean_recipes[recipe_index]
            meals.append({"date": d_str, "entryType": "dinner", "title": "", "recipeId": recipe['id']})
            recipe_index += 1
            
        current_date += timedelta(days=1)
        
    if progress_callback:
        progress_callback("Clearing old scheduled meals in Mealie calendar...", 70)
    existing_plans = client.get_meal_plan(start_date_str, end_date_str)
    for p in existing_plans:
        client.delete_meal_plan_entry(p['id'])
        
    if progress_callback:
        progress_callback("Scheduling new breakfasts, lunches, and dinners...", 80)
    for m in meals:
        client.schedule_meal(
            date_str=m['date'],
            entry_type=m['entryType'],
            title=m.get('title') or "",
            recipe_id=m.get('recipeId')
        )
        
    sync_shopping_list(start_date_str, end_date_str, low_staples_ids, progress_callback=progress_callback)
    print(f"Rule-based plan successfully generated and scheduled for {start_date_str} to {end_date_str}.")
