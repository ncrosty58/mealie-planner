from datetime import datetime, timedelta
import pytz
import os
from .config import TIMEZONE

def get_active_week_range():
    """
    Calculate the current planning week range.
    Starts on the most recent Saturday and ends the following Friday.
    """
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz)
    
    # Find the most recent Saturday (or today if it is Saturday)
    # weekday(): Mon=0, ..., Fri=4, Sat=5, Sun=6
    days_since_saturday = (today.weekday() - 5 + 7) % 7
    start_date = today - timedelta(days=days_since_saturday)
    
    # Planning week is 7 days: Saturday to Friday
    end_date = start_date + timedelta(days=6)
    
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    return start_date, end_date

def get_active_week_strings():
    """Return YYYY-MM-DD strings for start and end dates."""
    start, end = get_active_week_range()
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def get_planning_week_range(today=None):
    """
    Calculate the week range that should be planned/edited.
    Starts today and ends on the Friday of the current active week.
    """
    if today is None:
        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz)
        
    # Find the most recent Saturday to determine the current week's Friday
    days_since_saturday = (today.weekday() - 5 + 7) % 7
    start_of_week = today - timedelta(days=days_since_saturday)
    end_of_week = start_of_week + timedelta(days=6)
    
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Safety fallback
    if start_date > end_date:
        end_date = start_date
        
    return start_date, end_date

def get_planning_week_strings():
    """Return YYYY-MM-DD strings for start and end dates of the planning week."""
    start, end = get_planning_week_range()
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def sanitize_input(text, max_length=1000):
    """Basic sanitization and length limiting for user text inputs."""
    if not text:
        return ""
    # Strip whitespace and truncate
    return text.strip()[:max_length]
