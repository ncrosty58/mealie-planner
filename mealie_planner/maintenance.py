"""Destructive maintenance operations (plan/list wipes) shared by the web app and CLI."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .utils import get_active_week_range

logger = logging.getLogger(__name__)


def wipe_mealie_data(week='both', what='both', clear_past=False, client=None):
    """Wipe data for the rolling next 7 days.

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
        current_end_str = current_end.strftime("%Y-%m-%d")
        if clear_past:
            clear_start_str = current_start.strftime("%Y-%m-%d")
        else:
            clear_start_str = max(today_str, current_start.strftime("%Y-%m-%d"))

        logger.info("Clearing meal plan from %s to %s", clear_start_str, current_end_str)
        existing = client.get_meal_plan(clear_start_str, current_end_str)
        for p in existing:
            logger.info("Deleting meal plan entry: %s on %s", p.get('title', p.get('entryType')), p['date'])
            client.delete_meal_plan_entry(p['id'])
        logger.info("Cleared %d entries.", len(existing))

    if what in ('shopping', 'both'):
        logger.info("Clearing active shopping list (ID: %s)", config.ACTIVE_LIST_ID)
        client.clear_shopping_list(config.ACTIVE_LIST_ID)

    logger.info("Mealie data wiped successfully.")
