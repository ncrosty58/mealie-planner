"""Composition root: constructs the client/service object graph used by the web app."""
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Services:
    mealie: Any
    ai: Any
    crawler: Any
    shopping: Any
    notifier: Any
    nutrition: Any
    plan_generator: Any
    # Per-week locks so overlapping plan generations / syncs can't mutate the
    # same Mealie lists concurrently.
    week_locks: dict = field(default_factory=lambda: {
        'current': threading.Lock(),
        'next': threading.Lock(),
    })

    def week_lock(self, week):
        return self.week_locks.get(week, self.week_locks['current'])


def build_services() -> Services:
    # Imported lazily so tests can build an app with mocked services without
    # touching the network or requiring Mealie/AI credentials.
    from mealie_planner.ai_client import AIClient
    from mealie_planner.email_notifier import EmailNotifier
    from mealie_planner.plan_generator import PlanGenerator
    from mealie_planner.recipe_crawler import RecipeCrawler
    from mealie_planner.recipe_nutrition import RecipeNutrition
    from mealie_planner.shopping_sync import ShoppingListSync
    from mealie_planner.unified_client import UnifiedMealieClient

    mealie = UnifiedMealieClient()
    ai = AIClient()
    crawler = RecipeCrawler(mealie, ai)
    shopping = ShoppingListSync(mealie, ai, crawler)
    notifier = EmailNotifier(mealie, ai)
    nutrition = RecipeNutrition(mealie, ai)
    plan_generator = PlanGenerator(mealie, ai, crawler, shopping, notifier)

    return Services(
        mealie=mealie,
        ai=ai,
        crawler=crawler,
        shopping=shopping,
        notifier=notifier,
        nutrition=nutrition,
        plan_generator=plan_generator,
    )
