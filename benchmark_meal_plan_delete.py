import time
import requests
from unittest.mock import MagicMock
from mealie_planner.unified_client import UnifiedMealieClient

def run_benchmark(num_items=50, use_threads=False):
    # Mock the client
    client = MagicMock()

    # Simulate network latency of 50ms per request
    def mock_delete(id):
        time.sleep(0.05)

    client.delete_meal_plan_entry = mock_delete

    plans = [{"id": f"id_{i}", "date": "2023-10-10"} for i in range(num_items)]

    start_time = time.time()
    if use_threads:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(client.delete_meal_plan_entry, p['id']) for p in plans]
            concurrent.futures.wait(futures)
    else:
        for p in plans:
            client.delete_meal_plan_entry(p['id'])

    end_time = time.time()
    print(f"Time taken (use_threads={use_threads}): {end_time - start_time:.2f} seconds")

print("Running baseline (sequential)...")
run_benchmark(num_items=50, use_threads=False)

print("Running optimized (threaded)...")
run_benchmark(num_items=50, use_threads=True)
