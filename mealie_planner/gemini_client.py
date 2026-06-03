import os
import json
import requests
from .exceptions import ConfigurationError
from .ai_client import AIClient as GeminiClient

def call_gemini(prompt: str, expect_json: bool = True, temperature: float = 0.2, thinking_budget: int = 0, response_schema = None) -> str:
    """Compatibility wrapper function."""
    client = GeminiClient()
    return client.call(prompt, expect_json, temperature, thinking_budget, response_schema)
