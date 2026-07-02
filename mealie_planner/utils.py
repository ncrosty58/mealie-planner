from collections import namedtuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import TIMEZONE

# Resolved view of a UI week selection: canonical week name, date range strings,
# and the Mealie shopping list backing that week.
WeekContext = namedtuple('WeekContext', ['week', 'start_str', 'end_str', 'list_id'])


def resolve_week(week=None, mode='planning'):
    """Resolve the rolling next 7 days selection to a WeekContext.
    
    Ignores the week parameter to always use the next 7 days, pointing to ACTIVE_LIST_ID.
    """
    from .config import ACTIVE_LIST_ID

    start, end = get_next_7_days_range()
    return WeekContext('current', start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), ACTIVE_LIST_ID)

def get_next_7_days_range():
    """Calculate the rolling next 7 days range starting today."""
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today + timedelta(days=6)
    return today, end_date

def get_active_week_range():
    """Fallback compatibility wrapper returning next 7 days."""
    return get_next_7_days_range()

def get_next_week_range():
    """Fallback compatibility wrapper returning next week range."""
    start_date, end_date = get_active_week_range()
    next_start = start_date + timedelta(days=7)
    next_end = end_date + timedelta(days=7)
    return next_start, next_end

def get_active_week_strings():
    """Return YYYY-MM-DD strings for start and end of next 7 days."""
    start, end = get_next_7_days_range()
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def get_planning_week_range(today=None):
    """Fallback compatibility wrapper returning next 7 days."""
    return get_next_7_days_range()

def get_planning_week_strings():
    """Return YYYY-MM-DD strings for start and end of planning range."""
    start, end = get_planning_week_range()
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def sanitize_input(text, max_length=1000):
    """Basic sanitization and length limiting for user text inputs."""
    if not text:
        return ""
    # Strip whitespace and truncate
    return text.strip()[:max_length]

def extract_ingredient_text(ing):
    """Build a human-readable ingredient string from a Mealie recipe ingredient object.

    Prefers the pre-rendered `display`/`originalText` fields, falling back to
    assembling quantity + unit + food + note when those are missing.
    """
    text = ing.get('display') or ing.get('originalText')
    if not text:
        note = ing.get('note') or ""
        food = ing.get('food') or {}
        food_name = food.get('name') if isinstance(food, dict) else ""
        quantity = ing.get('quantity') or ""
        unit = ing.get('unit') or {}
        unit_name = unit.get('name') if isinstance(unit, dict) else ""
        text = f"{quantity} {unit_name} {food_name} {note}".strip()
    return text

def extract_ingredient_texts(recipe_details):
    """Return a list of cleaned ingredient strings from raw Mealie recipe details."""
    if not recipe_details:
        return []
    out = []
    for ing in recipe_details.get('recipeIngredient', []):
        text = extract_ingredient_text(ing)
        if text and text.strip():
            out.append(text.strip())
    return out
