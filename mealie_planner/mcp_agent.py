import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load env variables relative to project root
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, '.env'))

import logging

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mealie_planner.ai_client import AIClient
from mealie_planner.config import (
    ACTIVE_CHAT_MODEL,
    CHATBOT_GUIDELINES_PROMPT,
    CHATBOT_SYSTEM_PROMPT_TEMPLATE,
    FAMILY_DIETARY_RULES_PROMPT,
    FAMILY_NAMES,
    TIMEZONE,
)

logger = logging.getLogger(__name__)

def get_system_prompt(week_start_str=None, week_end_str=None):
    tz = ZoneInfo(TIMEZONE)
    now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S (%A)')
    if week_start_str and week_end_str:
        now_str += f"\nThe user is currently viewing/managing the week from {week_start_str} to {week_end_str}."
    
    return CHATBOT_SYSTEM_PROMPT_TEMPLATE.format(
        FAMILY_DIETARY_RULES_PROMPT=FAMILY_DIETARY_RULES_PROMPT,
        TIMEZONE=TIMEZONE,
        FAMILY_NAMES=FAMILY_NAMES,
        now_str=now_str,
        CHATBOT_GUIDELINES_PROMPT=CHATBOT_GUIDELINES_PROMPT
    )

def clean_schema(schema: dict) -> dict:
    """Prepare FastMCP schema for Gemini by capitalizing type names and stripping unsupported keys."""
    if not isinstance(schema, dict):
        return schema
    
    clean = {}
    for k, v in schema.items():
        if k == 'type' and isinstance(v, str):
            clean[k] = v.upper()
        elif k == 'properties' and isinstance(v, dict):
            clean[k] = {prop_name: clean_schema(prop_val) for prop_name, prop_val in v.items()}
        elif k == 'items' and isinstance(v, dict):
            clean[k] = clean_schema(v)
        elif k in ('required', 'description'):
            clean[k] = v
            
    return clean

def get_server_params():
    """Build the stdio parameters used to launch the MCP tool server subprocess."""
    mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": f"{mcp_src_dir}:{base_dir}",
        "MEALIE_BASE_URL": os.getenv("MEALIE_API_URL", "http://mealie:9000"),
        "MEALIE_API_KEY": os.getenv("MEALIE_TOKEN"),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
        "GEMINI_MODEL": ACTIVE_CHAT_MODEL,
    })
    return StdioServerParameters(
        command="python3",
        args=[os.path.join(base_dir, "mealie_planner", "mcp_server.py")],
        env=env
    )


def build_gemini_tools(tools_resp):
    """Convert an MCP list_tools response into Gemini functionDeclarations."""
    if not tools_resp.tools:
        return []
    declarations = []
    for tool in tools_resp.tools:
        param_schema = clean_schema(tool.inputSchema) if tool.inputSchema else {"type": "OBJECT", "properties": {}}
        declarations.append({
            "name": tool.name,
            "description": tool.description or "",
            "parameters": param_schema
        })
    return [{"functionDeclarations": declarations}]


async def run_chat_turn(session, gemini_tools, history, user_message, model_name=None, week_start_str=None, week_end_str=None):
    """Run one user turn of the tool-calling chat loop against an active MCP session.

    Returns: (reply_text, updated_history, plan_changed)
    """
    plan_changed = False
    if model_name is None:
        model_name = ACTIVE_CHAT_MODEL

    # Convert history to Gemini API format and append the new user message
    contents = [{"role": h["role"], "parts": [{"text": h["content"]}]} for h in history]
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    system_instruction = get_system_prompt(week_start_str, week_end_str)
    ai = AIClient()

    max_turns = 20
    for _turn in range(max_turns):
        data = ai.generate(
            contents,
            system_instruction=system_instruction,
            tools=gemini_tools or None,
            model=model_name,
        )

        candidate = data["candidates"][0]
        message = candidate["content"]
        parts = message.get("parts", [])

        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not function_calls:
            text_parts = [p["text"] for p in parts if "text" in p]
            reply_text = "".join(text_parts) if text_parts else ""

            new_history = list(history)
            new_history.append({"role": "user", "content": user_message})
            new_history.append({"role": "model", "content": reply_text})
            return reply_text, new_history, plan_changed

        # Append model message to history context
        contents.append(message)

        # Execute each function call
        response_parts = []
        for call in function_calls:
            func_name = call["name"]
            func_args = call.get("args", {})

            try:
                logger.info(f"[Agent] Executing tool: {func_name} with args: {func_args}")
                tool_result = await session.call_tool(func_name, func_args)
                res_text = ""
                if tool_result.content:
                    res_text = "\n".join([c.text for c in tool_result.content if getattr(c, 'type', None) == 'text' or hasattr(c, 'text')])
                result_payload = {"output": res_text}
                if func_name.startswith(("create_", "update_", "delete_", "add_", "remove_")):
                    plan_changed = True
            except Exception as ex:
                logger.error(f"[Agent] Error running tool {func_name}: {ex}")
                result_payload = {"error": str(ex)}

            response_parts.append({
                "functionResponse": {
                    "name": func_name,
                    "response": result_payload
                }
            })

        contents.append({
            "role": "tool",
            "parts": response_parts
        })

    return "I apologize, but I hit a loop limit trying to answer your request. Please try again.", history, plan_changed


async def run_mcp_chat(history, user_message, model_name=None, week_start_str=None, week_end_str=None):
    """One-shot variant: spawns a fresh MCP session for a single chat turn.

    The web app uses the persistent session in chat_session.py instead; this
    remains for scripts and ad-hoc use.
    """
    async with stdio_client(get_server_params()) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            gemini_tools = build_gemini_tools(await session.list_tools())
            return await run_chat_turn(
                session, gemini_tools, history, user_message,
                model_name=model_name, week_start_str=week_start_str, week_end_str=week_end_str,
            )
