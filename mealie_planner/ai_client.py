import os
import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class AIClient:
    """Generic, vendor‑agnostic client for OpenAI‑compatible chat APIs.

    By default it uses DeepSeek's API endpoint, but you can switch to any
    provider (e.g. OpenAI, Anthropic via proxy, local Ollama) by setting the
    environment variables:

        AI_API_KEY          – API key (falls back to DEEPSEEK_API_KEY)
        AI_BASE_URL         – base URL for the API (defaults to DeepSeek)
        AI_MODEL_NAME       – model identifier (defaults to deepseek-chat)
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True

        self.api_key = (
            api_key
            or os.getenv("AI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "AI API key not provided. Set AI_API_KEY (or DEEPSEEK_API_KEY) environment variable."
            )

        self.base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com")
        self.model_name = (
            model_name
            or os.getenv("AI_MODEL_NAME", "deepseek-chat")
        )
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def call(
        self,
        prompt: str,
        expect_json: bool = True,
        temperature: float = 0.2,
        thinking_budget: Optional[int] = None,  # ignored for non‑reasoning models
        response_schema=None,  # Pydantic model or dict schema
    ) -> str:
        """
        Call the AI API and return the response text.

        Args:
            prompt: The user prompt.
            expect_json: If True, requests JSON output via response_format.
            temperature: Sampling temperature.
            thinking_budget: Ignored (not supported by all vendors).
            response_schema: Optional Pydantic model or JSON schema dict.
                             If provided, its schema is appended to the prompt
                             to guide the model.

        Returns:
            The model's response as a string.
        """
        if thinking_budget is not None:
            logger.warning("thinking_budget is not supported by all vendors; ignoring it.")

        # If a schema is provided, add it to the prompt as guidance.
        if response_schema is not None:
            try:
                # Pydantic v2 model
                schema = response_schema.model_json_schema()
            except AttributeError:
                # assume it's already a dict
                schema = response_schema
            schema_text = json.dumps(schema, indent=2)
            prompt = (
                prompt
                + "\n\n---\nYou MUST output a single JSON object that strictly follows this JSON schema:\n"
                + schema_text
            )

        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }

        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
