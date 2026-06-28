import pytest
from datetime import datetime
import pytz
from freezegun import freeze_time

from mealie_planner.utils import (
    get_active_week_range,
    get_next_week_range,
    get_active_week_strings,
    get_planning_week_range,
    get_planning_week_strings,
    sanitize_input,
    extract_ingredient_text,
    extract_ingredient_texts,
)
from mealie_planner.config import TIMEZONE


class TestWeekRangeFunctions:
    @freeze_time("2023-10-18 12:00:00") # Wednesday
    def test_get_active_week_range_wednesday(self):
        tz = pytz.timezone(TIMEZONE)
        start, end = get_active_week_range()

        # 2023-10-18 is Wednesday. Most recent Saturday was 2023-10-14
        # Following Friday is 2023-10-20
        assert start.year == 2023 and start.month == 10 and start.day == 14
        assert start.hour == 0 and start.minute == 0 and start.second == 0

        assert end.year == 2023 and end.month == 10 and end.day == 20
        assert end.hour == 0 and end.minute == 0 and end.second == 0

    @freeze_time("2023-10-14 12:00:00") # Saturday
    def test_get_active_week_range_saturday(self):
        start, end = get_active_week_range()

        # Today is Saturday, it should start today.
        # Following Friday is 2023-10-20
        assert start.year == 2023 and start.month == 10 and start.day == 14
        assert end.year == 2023 and end.month == 10 and end.day == 20

    @freeze_time("2023-10-15 12:00:00") # Sunday
    def test_get_active_week_range_sunday(self):
        start, end = get_active_week_range()

        # Today is Sunday. Most recent Saturday was 2023-10-14
        # Following Friday is 2023-10-20
        assert start.year == 2023 and start.month == 10 and start.day == 14
        assert end.year == 2023 and end.month == 10 and end.day == 20

    @freeze_time("2023-10-18 12:00:00") # Wednesday
    def test_get_next_week_range(self):
        start, end = get_next_week_range()

        # Active start is 2023-10-14, end is 2023-10-20
        # Next start is 2023-10-21, next end is 2023-10-27
        assert start.year == 2023 and start.month == 10 and start.day == 21
        assert end.year == 2023 and end.month == 10 and end.day == 27

    @freeze_time("2023-10-18 12:00:00")
    def test_get_active_week_strings(self):
        start_str, end_str = get_active_week_strings()
        assert start_str == "2023-10-14"
        assert end_str == "2023-10-20"

    @freeze_time("2023-10-18 12:00:00") # Wednesday
    def test_get_planning_week_range_no_args(self):
        start, end = get_planning_week_range()

        # Starts "today" (2023-10-18)
        # Ends on Friday of current active week (2023-10-20)
        assert start.year == 2023 and start.month == 10 and start.day == 18
        assert end.year == 2023 and end.month == 10 and end.day == 20

    def test_get_planning_week_range_with_args(self):
        tz = pytz.timezone(TIMEZONE)
        today = datetime(2023, 10, 18, 12, 0, 0, tzinfo=tz) # Wednesday
        start, end = get_planning_week_range(today)

        assert start.year == 2023 and start.month == 10 and start.day == 18
        assert end.year == 2023 and end.month == 10 and end.day == 20


    @freeze_time("2023-10-18 12:00:00")
    def test_get_planning_week_strings(self):
        start_str, end_str = get_planning_week_strings()
        assert start_str == "2023-10-18"
        assert end_str == "2023-10-20"


class TestSanitizeInput:
    def test_sanitize_input_empty_or_none(self):
        assert sanitize_input(None) == ""
        assert sanitize_input("") == ""

    def test_sanitize_input_whitespace(self):
        assert sanitize_input("   hello world   ") == "hello world"
        assert sanitize_input("\t\nhello\n\t") == "hello"

    def test_sanitize_input_truncation(self):
        text = "a" * 1500
        result = sanitize_input(text, max_length=1000)
        assert len(result) == 1000
        assert result == "a" * 1000

        # Test custom max_length
        result = sanitize_input("hello world", max_length=5)
        assert len(result) == 5
        assert result == "hello"

    def test_sanitize_input_truncation_with_whitespace(self):
        text = "   " + ("a" * 1500) + "   "
        result = sanitize_input(text, max_length=1000)
        assert len(result) == 1000
        assert result == "a" * 1000


class TestIngredientTextExtraction:
    def test_extract_ingredient_text_display(self):
        ing = {'display': '1 cup chopped apples', 'originalText': 'apples, 1 cup'}
        assert extract_ingredient_text(ing) == '1 cup chopped apples'

    def test_extract_ingredient_text_originalText(self):
        ing = {'originalText': 'apples, 1 cup'}
        assert extract_ingredient_text(ing) == 'apples, 1 cup'

    def test_extract_ingredient_text_fallback(self):
        ing = {
            'quantity': '2',
            'unit': {'name': 'tbsp'},
            'food': {'name': 'sugar'},
            'note': 'brown'
        }
        assert extract_ingredient_text(ing) == '2 tbsp sugar brown'

    def test_extract_ingredient_text_fallback_missing_parts(self):
        ing = {
            'food': {'name': 'salt'}
        }
        assert extract_ingredient_text(ing) == 'None salt'

        ing = {
            'quantity': '1',
            'unit': {'name': 'pinch'}
        }
        assert extract_ingredient_text(ing) == '1 pinch None'

        # Strings instead of dicts for food/unit
        ing = {
            'quantity': '1',
            'unit': 'pinch', # Should be ignored because it's not a dict
            'food': 'salt'   # Should be ignored because it's not a dict
        }
        # Based on logic: unit_name = unit.get('name') if isinstance(unit, dict) else ""
        assert extract_ingredient_text(ing) == '1'

    def test_extract_ingredient_texts_empty(self):
        assert extract_ingredient_texts(None) == []
        assert extract_ingredient_texts({}) == []
        assert extract_ingredient_texts({'recipeIngredient': []}) == []

    def test_extract_ingredient_texts_valid(self):
        recipe = {
            'recipeIngredient': [
                {'display': '1 cup chopped apples'},
                {'originalText': 'apples, 1 cup'},
                {'quantity': '2', 'unit': {'name': 'tbsp'}, 'food': {'name': 'sugar'}},
                {'display': '   '} # Should be ignored because it's empty after strip
            ]
        }
        result = extract_ingredient_texts(recipe)
        assert len(result) == 3
        assert result[0] == '1 cup chopped apples'
        assert result[1] == 'apples, 1 cup'
        assert result[2] == '2 tbsp sugar'
