import re
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import requests

from .config import load_skill_md, _RECIPE_FINDER_SKILL_DEFINITION, get_banned_recipes
from .exceptions import MealieAPIError, SkillParsingError

class RecipeCrawler:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client
        self._detailed_recipes_cache = None

    def check_blackstone_compatibility(self, recipe_details):
        """Analyze recipe name and instructions to see if it's compatible with a Blackstone griddle."""
        if not recipe_details:
            return False
        name_lower = recipe_details.get('name', '').lower()
        instructions = recipe_details.get('recipeInstructions', [])
        instructions_text = " ".join([i.get('text', '').lower() for i in instructions if i.get('text')]).lower()
        
        return 'blackstone' in name_lower or 'griddle' in name_lower or 'blackstone' in instructions_text or 'griddle' in instructions_text

    def get_recipes_from_db(self):
        """Fetch all current recipes from the Mealie DB."""
        return self.client.get_all_recipes()

    def find_recipe_for_ingredient(self, ingredient_name, all_recipes=None):
        """Search the current recipe database for a recipe that matches the ingredient name."""
        if not all_recipes:
            all_recipes = self.get_recipes_from_db()
            
        search_term = ingredient_name.lower().strip()
        # 1. Look for exact name match
        for r in all_recipes:
            if r['name'].lower().strip() == search_term:
                return r['id']
        
        # 2. Look for name containing term
        for r in all_recipes:
            if search_term in r['name'].lower():
                return r['id']
                
        # 3. Look for term in slug
        for r in all_recipes:
            if search_term.replace(' ', '-') in r.get('slug', '').lower():
                return r['id']

        # 4. Look inside recipe ingredients (fetch details in parallel)
        # Check singular/plural and key noun variants to handle e.g. "chicken thighs" -> "chicken thigh" or "thigh"
        variants = [search_term]
        if search_term.endswith('s'):
            variants.append(search_term[:-1])
        if search_term.endswith('es'):
            variants.append(search_term[:-2])
            
        words = search_term.split()
        if len(words) > 1:
            last_word = words[-1]
            variants.append(last_word)
            if last_word.endswith('s'):
                variants.append(last_word[:-1])
            if last_word.endswith('es'):
                variants.append(last_word[:-2])
                
        # Remove empty strings or duplicates, sorted by length descending
        variants = sorted(list(set(v for v in variants if v)), key=len, reverse=True)

        if self._detailed_recipes_cache is None:
            def fetch_details(r):
                try:
                    return self.client.get_recipe_details(r['id'])
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=15) as executor:
                self._detailed_recipes_cache = list(executor.map(fetch_details, all_recipes))

        for r_details in self._detailed_recipes_cache:
            if not r_details:
                continue
            
            for ing in r_details.get('recipeIngredient', []):
                texts = []
                if isinstance(ing, dict):
                    if ing.get('ingredient') and isinstance(ing['ingredient'], dict):
                        texts.append(ing['ingredient'].get('name') or '')
                    texts.append(ing.get('display') or '')
                    texts.append(ing.get('note') or '')
                    texts.append(ing.get('originalText') or '')
                else:
                    texts.append(str(ing))
                    
                full_ing_text = " ".join(texts).lower()
                for variant in variants:
                    if variant in full_ing_text:
                        print(f"[Crawler] Found ingredient match for variant '{variant}' of '{search_term}' in recipe: {r_details['name']}")
                        return r_details['id']
                
        return None

    def search_recipes(self, query):
        """Perform a web search for recipe URLs."""
        search_query = f"{query} recipe"
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, 'html.parser')
            links = []
            for a in soup.find_all('a', class_='result__a', href=True):
                href = a['href']
                # Clean DuckDuckGo redirect URLs
                if 'uddg=' in href:
                    try:
                        # Extract uddg query param
                        parsed_href = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed_href.query)
                        href = qs.get('uddg', [href])[0]
                    except Exception:
                        href = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                if 'youtube.com' not in href and 'pinterest.com' not in href:
                    links.append(href)
            return links[:5]
        except Exception as e:
            print(f"[Crawler] Web search failed: {e}")
            return []

    def get_url_metadata(self, url):
        """Fetch the title and description of a URL for AI validation."""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            title = soup.title.string if soup.title else ""
            desc = ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                desc = meta_desc.get('content', '')
            return {'url': url, 'title': title.strip(), 'description': desc.strip()}
        except:
            return None

    def validate_recipe_link_with_ai(self, url, title, description):
        """Use Gemini to confirm if a URL is actually a single, high-quality recipe."""
        prompt = (
            "You are an expert in the 'Mealie Recipe Link Validator Skill'.\n\n" +
            _RECIPE_FINDER_SKILL_DEFINITION +
            "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
            f"URL: {url}\nTitle: {title}\nDescription: {description}\n\n" +
            "Return ONLY 'YES' or 'NO'."
        )
        try:
            response = self.gemini.call(prompt, expect_json=False)
            return 'YES' in response.upper()
        except:
            return False

    def find_and_import_recipe(self, ingredient_name, existing_recipe_ids=None):
        """Search the web for a recipe, validate it with AI, and import it into Mealie."""
        print(f"[Crawler] Searching for recipe for: {ingredient_name}")
        search_results = self.search_recipes(ingredient_name)
        
        for url in search_results:
            try:
                # 1. Fetch metadata for AI validation
                metadata = self.get_url_metadata(url)
                if not metadata:
                    continue
                
                # 2. Use AI to validate if it's a good single recipe link
                is_valid = self.validate_recipe_link_with_ai(metadata['url'], metadata['title'], metadata['description'])
                if not is_valid:
                    print(f"[Crawler] AI rejected link: {url}")
                    continue
                
                # 3. Import into Mealie
                print(f"[Crawler] Importing valid recipe: {url}")
                import_url = f"{self.client.api_url}/api/recipes/create/url"
                payload = {"url": url}
                # Use internal _request helper if possible, or just standard requests for this one-off
                r = requests.post(import_url, json=payload, headers=self.client.headers)
                r.raise_for_status()
                # Clear detailed recipes cache on successful import
                self._detailed_recipes_cache = None
                print(f"[Crawler] Successfully imported: {ingredient_name}")
                return True
                
            except Exception as e:
                print(f"[Crawler] Error processing link {url}: {e}")
                continue
                
        return False

def check_blackstone_compatibility(recipe_details):
    """Standalone utility to check Blackstone compatibility without needing a crawler instance."""
    if not recipe_details:
        return False
    name_lower = recipe_details.get('name', '').lower()
    instructions = recipe_details.get('recipeInstructions', [])
    instructions_text = " ".join([i.get('text', '').lower() for i in instructions if i.get('text')]).lower()
    
    return 'blackstone' in name_lower or 'griddle' in name_lower or 'blackstone' in instructions_text or 'griddle' in instructions_text

