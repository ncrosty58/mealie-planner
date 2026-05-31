import os
import sys
import time
from datetime import datetime, timedelta
import pytz

# Add project root to path
sys.path.insert(0, '/app')

from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.gemini_client import GeminiClient
from mealie_planner.recipe_crawler import RecipeCrawler
from mealie_planner.plan_generator import PlanGenerator
from mealie_planner import config

def run_profile():
    print("====================================================")
    print("        PROFILING WEEKLY MEALPLAN CREATION          ")
    print("====================================================\n")

    timers = {}
    
    # Define date range
    today = datetime.now(pytz.timezone(config.TIMEZONE))
    days_to_sat = (5 - today.weekday() + 7) % 7
    start_date = today + timedelta(days=days_to_sat)
    end_date = start_date + timedelta(days=6)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Planning dates: {start_str} to {end_str}")
    print("Bypassing DB queries - RESTful API ONLY\n")

    # 1. Mealie Client Init / Auth
    t_start = time.perf_counter()
    client = UnifiedMealieClient()
    gemini = GeminiClient()
    crawler = RecipeCrawler(client, gemini)
    generator = PlanGenerator(client, gemini)
    timers['Client Init & Token Validation'] = time.perf_counter() - t_start
    print(f"[Phase 1] Client Init & Auth: {timers['Client Init & Token Validation']:.3f}s")

    # 2. Scrape and Import freezer items
    # Since we cleared all recipes, this will trigger the web search, page scraping,
    # AI validation, and Mealie URL import.
    freezer_item = "salmon"
    print(f"\n[Phase 2] Finding/Importing recipe for freezer item '{freezer_item}' (Scraper & AI Validation)...")
    t_start = time.perf_counter()
    
    # We will track finding & importing manually to measure detailed scraper steps
    recipe_id = crawler.find_recipe_for_ingredient(freezer_item)
    if not recipe_id:
        success = crawler.find_and_import_recipe(freezer_item)
        timers['Freezer Item Scrape & Import'] = time.perf_counter() - t_start
        print(f"  Scrape and Import Result: {'Success' if success else 'Failed'}")
    else:
        timers['Freezer Item Scrape & Import'] = time.perf_counter() - t_start
        print("  Recipe already existed.")
    print(f"  Duration: {timers['Freezer Item Scrape & Import']:.3f}s")

    # 3. Retrieve all recipes details via REST API
    print("\n[Phase 3] Retrieving all detailed recipes via Mealie REST API (concurrent details)...")
    t_start = time.perf_counter()
    all_recipes = crawler.get_recipes_from_db()  # Now routed to REST API only
    timers['Fetch Recipe Details via API'] = time.perf_counter() - t_start
    print(f"  Recipes found: {len(all_recipes)}")
    print(f"  Duration: {timers['Fetch Recipe Details via API']:.3f}s")

    # 4. Generate the weekly plan (AI Selection and Scheduling)
    print("\n[Phase 4] Running Full Weekly Plan Generator (Exclusion Parsing + AI Selection + Scheduling)...")
    t_start = time.perf_counter()
    
    # Run the full generate_weekly_plan function
    # Note: we pass freezer_items="salmon" (which now exists) to see how it resolves it
    success = generator.generate_weekly_plan(
        start_date_str=start_str,
        end_date_str=end_str,
        exclude_text="No dinners on Wednesday",
        freezer_items="salmon",
        special_requests="High fiber, vegetarian priority",
        low_staples_ids=[]
    )
    
    timers['AI Selection & Scheduling (Total)'] = time.perf_counter() - t_start
    print(f"  Plan Generation Result: {'Success' if success else 'Failed'}")
    print(f"  Duration: {timers['AI Selection & Scheduling (Total)']:.3f}s")

    # Display Summary report
    print("\n====================================================")
    print("               PERFORMANCE SUMMARY                   ")
    print("====================================================")
    total_time = sum(timers.values())
    for phase, duration in timers.items():
        percentage = (duration / total_time) * 100
        print(f"{phase:<40}: {duration:>7.3f}s ({percentage:>5.1f}%)")
    print("----------------------------------------------------")
    print(f"{'Total Execution Time':<40}: {total_time:>7.3f}s (100.0%)")
    print("====================================================\n")

if __name__ == "__main__":
    run_profile()
