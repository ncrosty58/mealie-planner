import os
import sys

import requests

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.unified_client import UnifiedMealieClient


def import_samples():
    print("Initializing UnifiedMealieClient...")
    try:
        client = UnifiedMealieClient()
    except Exception as e:
        print(f"Error: {e}")
        return

    sample_urls = [
        "https://www.mediterraneandish.com/greek-salad-recipe/",
        "https://www.cafedelites.com/garlic-butter-salmon/",
        "https://www.chelseasmessyapron.com/sheet-pan-chicken-and-veggies/",
        "https://www.loveandlemons.com/lemon-rice-recipe/",
        "https://www.aheadofthyme.com/easy-coconut-chickpea-curry/"
    ]

    print(f"Importing {len(sample_urls)} sample recipes...")
    for idx, url in enumerate(sample_urls):
        print(f"[{idx+1}/{len(sample_urls)}] Importing {url}...")
        payload = {
            "url": url,
            "includeCategories": True,
            "includeTags": True
        }
        try:
            r = requests.post(f"{client.api_url}/api/recipes/create/url", json=payload, headers=client.headers, timeout=45)
            if r.status_code in (200, 201):
                print(f"  Successfully imported: {r.json()}")
            else:
                print(f"  Failed with status {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  Error importing: {e}")

if __name__ == "__main__":
    import_samples()
