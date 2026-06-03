import os
import json
import logging
import requests
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AIClient:
    """Unified AI Client supporting both Google Gemini and OpenAI/DeepSeek backends.

    Configuration can be switched easily via the AI_VENDOR environment variable
    or the centralized config file.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        # Allow re-initialization if api_key or model_name is explicitly passed,
        # otherwise use singleton check.
        if self._initialized and api_key is None and model_name is None:
            return

        from .config import AI_VENDOR, ACTIVE_CORE_MODEL
        self.vendor = AI_VENDOR

        if self.vendor == "gemini":
            self.api_key = api_key or os.getenv('GOOGLE_API_KEY')
            self.model_name = model_name or os.getenv('GEMINI_MODEL', ACTIVE_CORE_MODEL)
            if not self.api_key:
                from .exceptions import ConfigurationError
                raise ConfigurationError("GOOGLE_API_KEY is not set in environment.")
            self.session = requests.Session()
        else:
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
                or os.getenv("AI_MODEL_NAME", ACTIVE_CORE_MODEL)
            )
            from openai import OpenAI
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

        self._initialized = True

    def call(
        self,
        prompt: str,
        expect_json: bool = True,
        temperature: float = 0.2,
        thinking_budget: Optional[int] = None,
        response_schema=None,
    ) -> str:
        """
        Call the active AI API and return the response text.
        """
        if self.vendor == "gemini":
            # --- GEMINI BACKEND ---
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

            generation_config = {
                "temperature": temperature,
                "responseMimeType": "application/json" if (expect_json or response_schema) else "text/plain",
            }
            if thinking_budget is not None and thinking_budget > 0:
                generation_config["thinkingConfig"] = {
                    "thinkingBudget": thinking_budget
                }

            if response_schema:
                from pydantic import BaseModel
                # If response_schema is a Pydantic model class
                if isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
                    generation_config["responseJsonSchema"] = response_schema.model_json_schema()
                elif hasattr(response_schema, "model_json_schema"):
                    generation_config["responseJsonSchema"] = response_schema.model_json_schema()
                else:
                    generation_config["responseJsonSchema"] = response_schema

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config
            }

            print("--- AI PROMPT (Gemini) ---")
            print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
            print("-------------------")

            try:
                resp = self.session.post(url, json=payload, timeout=180)
                resp.raise_for_status()
                data = resp.json()
                print("--- AI RAW RESPONSE (Meta) ---")
                print(f"Response ID: {data.get('responseId')}")
                print("-----------------------")
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except requests.exceptions.RequestException as e:
                print(f"Gemini API call failed: {e}")
                raise

        else:
            # --- OPENAI/DEEPSEEK BACKEND ---
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

    def generate(
        self,
        contents: list,
        system_instruction: Optional[str] = None,
        tools: Optional[list] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        timeout: int = 90,
    ) -> dict:
        """
        Lower-level generateContent call exposing multi-turn `contents`, system_instruction,
        and tool/function-calling, supporting both Gemini and OpenAI backends.
        """
        active_model = model or self.model_name

        if self.vendor == "gemini":
            # --- GEMINI BACKEND ---
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_model}:generateContent?key={self.api_key}"

            payload = {"contents": contents}
            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            if tools:
                payload["tools"] = tools
            
            # Build generation config if needed
            generation_config = {}
            if temperature is not None:
                generation_config["temperature"] = temperature
            if generation_config:
                payload["generationConfig"] = generation_config

            resp = self.session.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()

        else:
            # --- OPENAI/DEEPSEEK BACKEND ---
            # Convert Gemini‑style tools to OpenAI format
            openai_tools = None
            if tools:
                openai_tools = []
                for tool in tools:
                    for decl in tool.get("functionDeclarations", []):
                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": decl["name"],
                                "description": decl.get("description", ""),
                                "parameters": decl.get("parameters", {}),
                            }
                        })

            messages = [{"role": "system", "content": system_instruction}] if system_instruction else []
            for item in contents:
                role = item.get("role", "user")
                # Handle both 'model' and 'assistant' roles
                if role == "model":
                    role = "assistant"
                parts = item.get("parts", [])
                text = "".join(p.get("text", "") for p in parts if "text" in p)
                messages.append({"role": role, "content": text})

            # Fire the request (may use tools)
            kwargs = {
                "model": active_model,
                "messages": messages,
                "tools": openai_tools,
                "tool_choice": "auto" if openai_tools else None,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = self.client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            msg = choice.message

            # Build Gemini‑like response structure
            parts = []
            if msg.content:
                parts.append({"text": msg.content})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments) if tc.function.arguments else {},
                        }
                    })

            return {
                "candidates": [
                    {"content": {"parts": parts}}
                ]
            }
