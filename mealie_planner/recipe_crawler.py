import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import requests
import json

from .config import load_skill_md, _RECIPE_FINDER_SKILL_DEFINITION, get_banned_recipes, _BLACKSTONE_COMPATIBILITY_SKILL_DEFINITION, SEMANTIC_MATCH_PROMPT_TEMPLATE
from .exceptions import MealieAPIError, SkillParsingError

class RecipeCrawler:
    def __init__(self, mealie_client, ai_client):
        self.client = mealie_client
        self.ai = ai_client
        self._detailed_recipes_cache = None

    def check_blackstone_compatibility(self, recipe_details):
        """Analyze recipe details using AI semantic reasoning to check flat top griddle compatibility."""
        return check_blackstone_compatibility(recipe_details)

    def get_recipes_from_db(self):
        """Fetch all current recipes from the Mealie DB."""
        return self.client.get_all_recipes()

    def find_recipe_for_ingredient(self, ingredient_name, all_recipes=None):
        """Search the current recipe database for a recipe that matches the title, falling back to semantic AI matching."""
        if not all_recipes:
            all_recipes = self.get_recipes_from_db()
            
        search_term = ingredient_name.lower().strip()
        
        # 1. Fast-Path: Exact name match
        for r in all_recipes:
            if r['name'].lower().strip() == search_term:
                return r['id']
        
        # 2. Fast-Path: Slug match
        for r in all_recipes:
            if search_term.replace(' ', '-') in r.get('slug', '').lower():
                return r['id']

        # 3. Semantic Path: Ask AI to resolve the closest culinary match
        catalogue = [
            {
                "id": r["id"],
                "name": r["name"],
                "description": (r.get("description") or "")[:150],
                "tags": [t.get('name', t) if isinstance(t, dict) else t for t in r.get('tags', [])]
            }
            for r in all_recipes
        ]
        prompt = SEMANTIC_MATCH_PROMPT_TEMPLATE.format(
            ingredient_name=ingredient_name,
            catalogue=json.dumps(catalogue, indent=2)
        )
        try:
            response = self.ai.call(prompt, expect_json=False).strip()
            if response and response.upper() != 'NONE' and len(response) > 20:
                # Validate it's a valid ID from the catalogue
                valid_ids = {r["id"] for r in all_recipes}
                if response in valid_ids:
                    print(f"[Crawler] Semantic match found: '{ingredient_name}' -> recipe ID '{response}'")
                    return response
        except Exception as e:
            print(f"[Crawler] Semantic recipe matching failed: {e}")
            
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
                if 'uddg=' in href:
                    try:
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
        """Use AI to confirm if a URL is actually a single, high-quality recipe."""
        prompt = (
            "You are an expert in the 'Mealie Recipe Link Validator Skill'.\n\n" +
            _RECIPE_FINDER_SKILL_DEFINITION +
            "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
            f"URL: {url}\nTitle: {title}\nDescription: {description}\n\n" +
            "Return ONLY 'YES' or 'NO'."
        )
        try:
            response = self.ai.call(prompt, expect_json=False)
            return 'YES' in response.upper()
        except:
            return False

    def find_and_import_recipe(self, ingredient_name, existing_recipe_ids=None):
        """Search the web for a recipe, validate it with AI, and import it into Mealie."""
        print(f"[Crawler] Searching for recipe for: {ingredient_name}")
        search_results = self.search_recipes(ingredient_name)
        
        for url in search_results:
            try:
                metadata = self.get_url_metadata(url)
                if not metadata:
                    continue
                
                is_valid = self.validate_recipe_link_with_ai(metadata['url'], metadata['title'], metadata['description'])
                if not is_valid:
                    print(f"[Crawler] AI rejected link: {url}")
                    continue
                
                print(f"[Crawler] Importing valid recipe: {url}")
                self.client.create_recipe_from_url(url)
                self._detailed_recipes_cache = None
                print(f"[Crawler] Successfully imported: {ingredient_name}")
                return True
                
            except Exception as e:
                print(f"[Crawler] Error processing link {url}: {e}")
                continue
                
        return False

def _persist_blackstone_verdict(recipe_details, result):
    """Cache a computed Blackstone verdict back onto the Mealie recipe's `extras`
    so subsequent dashboard loads read it instead of re-invoking the AI."""
    slug = recipe_details.get('slug')
    if not slug:
        return
    try:
        from .unified_client import UnifiedMealieClient
        client = UnifiedMealieClient()
        existing_extras = recipe_details.get('extras') or {}
        new_extras = {**existing_extras, 'blackstone_compatible': 'true' if result else 'false'}
        client.patch_recipe(slug, {"extras": new_extras})

        # Keep the in-memory copy and the shared details cache in sync.
        recipe_details['extras'] = new_extras
        cache = getattr(client, '_recipe_details_cache', {})
        rid = recipe_details.get('id')
        if rid and rid in cache and isinstance(cache[rid], dict):
            cache[rid]['extras'] = new_extras
        if slug in cache and isinstance(cache[slug], dict):
            cache[slug]['extras'] = new_extras
    except Exception as e:
        print(f"[Crawler] Failed to persist Blackstone verdict for '{slug}': {e}")


def check_blackstone_compatibility(recipe_details):
    """Standalone utility to check Blackstone compatibility using keyword check and AI fallback.

    The verdict is cached on the recipe's Mealie `extras` (`blackstone_compatible`) so it is
    computed at most once per recipe rather than on every dashboard render.
    """
    if not recipe_details:
        return False

    # 0. Cached verdict (avoids the keyword scan AND the AI call entirely)
    extras = recipe_details.get('extras') or {}
    cached = extras.get('blackstone_compatible')
    if cached is not None:
        return str(cached).lower() in ('true', '1', 'yes')

    name_lower = recipe_details.get('name', '').lower()
    instructions = recipe_details.get('recipeInstructions', [])
    instructions_text = " ".join([i.get('text', '').lower() for i in instructions if i.get('text')]).lower()

    # 1. Fast path: explicit keyword mention
    if ('blackstone' in name_lower or 'griddle' in name_lower or 'flat top' in name_lower
            or 'blackstone' in instructions_text or 'griddle' in instructions_text):
        _persist_blackstone_verdict(recipe_details, True)
        return True

    # 2. AI Fallback
    name = recipe_details.get('name', '')
    instructions_list = [i.get('text', '') for i in instructions if i.get('text')]
    prompt = (
        "You are an expert in the 'Blackstone Griddle Compatibility Skill'.\n\n" +
        _BLACKSTONE_COMPATIBILITY_SKILL_DEFINITION +
        "\n\n### CONTEXT FOR THIS INVOCATION:\n" +
        f"Recipe Name: {name}\n" +
        f"Instructions:\n{' '.join(instructions_list)}\n\n" +
        "Return ONLY 'YES' or 'NO'."
    )
    try:
        from .ai_client import AIClient
        ai = AIClient()
        response = ai.call(prompt, expect_json=False)
        result = 'YES' in response.upper()
        _persist_blackstone_verdict(recipe_details, result)
        return result
    except Exception as e:
        print(f"[Crawler] Standalone Blackstone griddle AI check failed, falling back: {e}")
        return False
