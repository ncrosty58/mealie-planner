import asyncio
import os
import json
from datetime import datetime
import pytz
from dotenv import load_dotenv

# Load env variables relative to project root
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, '.env'))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mealie_planner.config import (
    TIMEZONE,
    FAMILY_DIETARY_RULES_PROMPT,
    FAMILY_NAMES,
    CHATBOT_GUIDELINES_PROMPT,
    load_skill_md,
    ACTIVE_CHAT_MODEL
)
from mealie_planner.ai_client import AIClient

def get_system_prompt():
    tz = pytz.timezone(TIMEZONE)
    now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S (%A)')
    
    return f"""You are an expert culinary assistant and personal chef for Nathan & Kristin's Mealie companion app.
Your job is to help them manage their meal plan and shopping list, and to provide expert advice on ingredients, recipes, and nutrition.

{FAMILY_DIETARY_RULES_PROMPT}

Current Timezone: {TIMEZONE}
Current Family Names: {FAMILY_NAMES}
Current Date and Time: {now_str}

=== CHATBOT GUIDELINES ===
{CHATBOT_GUIDELINES_PROMPT}
"""

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

async def run_mcp_chat(history, user_message, model_name=None):
    """
    history is a list of dicts: [{"role": "user"|"model", "content": "..."}]
    user_message is the new message string.
    Returns: (reply_text, updated_history)
    """
    plan_changed = False
    if model_name is None:
        model_name = ACTIVE_CHAT_MODEL
        
    mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
    server_params = StdioServerParameters(
        command="python3",
        args=[os.path.join(base_dir, "mealie_planner", "mcp_server.py")],
        env={
            "PYTHONPATH": f"{mcp_src_dir}:{base_dir}",
            "MEALIE_BASE_URL": os.getenv("MEALIE_API_URL", "http://mealie:9000"),
            "MEALIE_API_KEY": os.getenv("MEALIE_TOKEN"),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "GEMINI_MODEL": ACTIVE_CHAT_MODEL,
            "PATH": os.environ.get("PATH", "")
        }
    )
    
    # 1. Convert history to Gemini API format
    contents = []
    for h in history:
        role = h["role"]
        contents.append({
            "role": role,
            "parts": [{"text": h["content"]}]
        })
        
    # Append the new user message
    contents.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })
    
    # 2. Start MCP session and run loop
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # Fetch tools from MCP server
            tools_resp = await session.list_tools()
            gemini_tools = []
            
            if tools_resp.tools:
                declarations = []
                for tool in tools_resp.tools:
                    param_schema = clean_schema(tool.inputSchema) if tool.inputSchema else {"type": "OBJECT", "properties": {}}
                    declarations.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": param_schema
                    })
                gemini_tools = [{"functionDeclarations": declarations}]
                
            # Loop for AI to call functions
            system_instruction = get_system_prompt()
            ai = AIClient()

            max_turns = 20
            for turn in range(max_turns):
                data = ai.generate(
                    contents,
                    system_instruction=system_instruction,
                    tools=gemini_tools or None,
                    model=model_name,
                )

                candidate = data["candidates"][0]
                message = candidate["content"]
                parts = message.get("parts", [])
                
                # Check for function calls
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
                        print(f"[Agent] Executing tool: {func_name} with args: {func_args}")
                        tool_result = await session.call_tool(func_name, func_args)
                        res_text = ""
                        if tool_result.content:
                            res_text = "\n".join([c.text for c in tool_result.content if getattr(c, 'type', None) == 'text' or hasattr(c, 'text')])
                        result_payload = {"output": res_text}
                        if func_name.startswith(("create_", "update_", "delete_", "add_", "remove_")):
                            plan_changed = True
                    except Exception as ex:
                        print(f"[Agent] Error running tool {func_name}: {ex}")
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
