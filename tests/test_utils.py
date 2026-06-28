import pytest
from mealie_planner.utils import sanitize_input

def test_sanitize_input_empty():
    assert sanitize_input(None) == ""
    assert sanitize_input("") == ""

def test_sanitize_input_normal():
    assert sanitize_input("hello world") == "hello world"

def test_sanitize_input_whitespace():
    assert sanitize_input("   hello world   ") == "hello world"
    assert sanitize_input("\t\nhello world\n\t") == "hello world"

def test_sanitize_input_default_truncation():
    # default max_length is 1000
    long_string = "a" * 1500
    sanitized = sanitize_input(long_string)
    assert len(sanitized) == 1000
    assert sanitized == "a" * 1000

def test_sanitize_input_custom_truncation():
    assert sanitize_input("abcdef", max_length=3) == "abc"
    assert sanitize_input("  abcdef  ", max_length=4) == "abcd"
