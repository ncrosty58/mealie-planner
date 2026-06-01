import os
import json
import requests
from .exceptions import ConfigurationError

class GeminiClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(GeminiClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, api_key=None, model_name=None):
        if self._initialized:
            return
            
        self.api_key = api_key or os.getenv('GOOGLE_API_KEY')
        self.model = model_name or os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
        if not self.api_key:
            raise ConfigurationError("GOOGLE_API_KEY is not set in environment.")
        self._initialized = True

    def call(self, prompt: str, expect_json: bool = True, temperature: float = 0.2, thinking_budget: int = 0, response_schema = None) -> str:
        """
        Send a prompt to the Gemini API and return the text response.
        If expect_json=True or response_schema is set, requests JSON output mode.
        If response_schema is provided (should be a Pydantic model class), it is used
        to configure the response schema constraint in Gemini via responseJsonSchema.
        """
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        generation_config = {
            "temperature": temperature,
            "responseMimeType": "application/json" if (expect_json or response_schema) else "text/plain",
            "thinkingConfig": {
                "thinkingBudget": thinking_budget
            }
        }

        if response_schema:
            from pydantic import BaseModel
            if issubclass(response_schema, BaseModel):
                generation_config["responseJsonSchema"] = response_schema.model_json_schema()

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config
        }

        print("--- AI PROMPT ---")
        print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
        print("-------------------")

        try:
            resp = requests.post(url, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            print("--- AI RAW RESPONSE (Meta) ---")
            print(f"Response ID: {data.get('responseId')}")
            print("-----------------------")
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.RequestException as e:
            print(f"Gemini API call failed: {e}")
            raise

def call_gemini(prompt: str, expect_json: bool = True, temperature: float = 0.2, thinking_budget: int = 0, response_schema = None) -> str:
    """Compatibility wrapper function."""
    client = GeminiClient()
    return client.call(prompt, expect_json, temperature, thinking_budget, response_schema)
