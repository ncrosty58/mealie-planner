"""Destructive maintenance operations (plan/list wipes) shared by the web app and CLI."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .utils import get_active_week_range

logger = logging.getLogger(__name__)


def wipe_mealie_data(week='both', what='both', clear_past=False, client=None):
    """Wipe data for current week, next week, or both.

    `what` controls which data is wiped: 'plan' (meal plan entries only),
    'shopping' (shopping list items only), or 'both'.
    """
    if client is None:
        from .unified_client import UnifiedMealieClient
        client = UnifiedMealieClient()

    tz = ZoneInfo(config.TIMEZONE)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    current_start, current_end = get_active_week_range()

    if what in ('plan', 'both'):
        if week in ('current', 'both'):
            current_end_str = current_end.strftime("%Y-%m-%d")
            # Clear current week starting from today (or start of week if clear_past is True)
            if clear_past:
                clear_start_str = current_start.strftime("%Y-%m-%d")
            else:
                clear_start_str = max(today_str, current_start.strftime("%Y-%m-%d"))

            logger.info("Clearing meal plan for current week from %s to %s", clear_start_str, current_end_str)
            existing = client.get_meal_plan(clear_start_str, current_end_str)
            for p in existing:
                logger.info("Deleting meal plan entry: %s on %s", p.get('title', p.get('entryType')), p['date'])
                client.delete_meal_plan_entry(p['id'])
            logger.info("Cleared %d entries for current week.", len(existing))

        if week in ('next', 'both'):
            next_start_str = (current_start + timedelta(days=7)).strftime("%Y-%m-%d")
            next_end_str = (current_end + timedelta(days=7)).strftime("%Y-%m-%d")

            logger.info("Clearing meal plan for next week: %s to %s", next_start_str, next_end_str)
            existing = client.get_meal_plan(next_start_str, next_end_str)
            for p in existing:
                logger.info("Deleting meal plan entry: %s on %s", p.get('title', p.get('entryType')), p['date'])
                client.delete_meal_plan_entry(p['id'])
            logger.info("Cleared %d entries for next week.", len(existing))

    if what in ('shopping', 'both'):
        if week in ('current', 'both'):
            logger.info("Clearing active shopping list (ID: %s)", config.ACTIVE_LIST_ID)
            client.clear_shopping_list(config.ACTIVE_LIST_ID)

        if week in ('next', 'both') and config.NEXT_LIST_ID != config.ACTIVE_LIST_ID:
            logger.info("Clearing next week shopping list (ID: %s)", config.NEXT_LIST_ID)
            client.clear_shopping_list(config.NEXT_LIST_ID)

    logger.info("Mealie data wiped successfully.")
