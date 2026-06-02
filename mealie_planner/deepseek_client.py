import os
import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """Singleton client for the DeepSeek API (OpenAI-compatible).

    Replaces GeminiClient with the same call signature.
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

        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not provided. Set DEEPSEEK_API_KEY environment variable."
            )
        self.model_name = model_name or "deepseek-chat"
        self.client = OpenAI(base_url="https://api.deepseek.com", api_key=self.api_key)

    def call(
        self,
        prompt: str,
        expect_json: bool = True,
        temperature: float = 0.2,
        thinking_budget: Optional[int] = None,  # ignored
        response_schema=None,  # Pydantic model or dict schema
    ) -> str:
        """
        Call the DeepSeek API and return the response text.

        Args:
            prompt: The user prompt.
            expect_json: If True, requests JSON output via response_format.
            temperature: Sampling temperature.
            thinking_budget: Ignored (DeepSeek has no thinking budget).
            response_schema: Optional Pydantic model or JSON schema dict.
                             If provided, its schema is appended to the prompt
                             to guide the model.

        Returns:
            The model's response as a string.
        """
        if thinking_budget is not None:
            logger.warning("thinking_budget is not supported by DeepSeek; ignoring it.")

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
