import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.unified_client import UnifiedMealieClient


def test_concurrency(max_workers):
    client = UnifiedMealieClient()
    recipes = client.get_all_recipes()
    print(f"\nTesting with max_workers={max_workers} (Total recipes to fetch: {len(recipes)})...")
    
    success_count = 0
    error_count = 0
    t0 = time.perf_counter()
    
    def fetch_one(r):
        nonlocal success_count, error_count
        try:
            # Short timeout to prevent long hangs
            resp = requests.get(f"{client.api_url}/api/recipes/{r['id']}", headers=client.headers, timeout=5)
            if resp.status_code == 200:
                success_count += 1
            else:
                error_count += 1
        except Exception:
            error_count += 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(fetch_one, recipes)
        
    duration = time.perf_counter() - t0
    print(f"  Duration: {duration:.3f}s")
    print(f"  Successful: {success_count} | Errors: {error_count}")
    return duration

def main():
    print("=== TESTING SQLite CONCURRENCY CONGESTION IN MEALIE ===")
    
    # Test different worker counts
    results = {}
    for workers in [1, 2, 4, 8, 16]:
        try:
            results[workers] = test_concurrency(workers)
        except Exception as e:
            print(f"Error testing with workers={workers}: {e}")
            
    print("\nSummary:")
    for workers, duration in results.items():
        print(f"  Workers: {workers:>2} | Duration: {duration:>6.3f}s")

if __name__ == "__main__":
    main()
