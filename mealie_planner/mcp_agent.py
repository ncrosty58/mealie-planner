import asyncio
import os
import json
import requests
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
    load_skill_md
)

def get_system_prompt():
    tz = pytz.timezone(TIMEZONE)
    now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S (%A)')
    
    return f"""You are an expert culinary assistant and personal chef for Nathan & Kristin's Mealie companion app.
Your job is to help them manage their meal plan and shopping list, and to provide expert advice on ingredients, recipes, and nutrition.

{FAMILY_DIETARY_RULES_PROMPT}

Current Timezone: {TIMEZONE}
Current Family Names: {FAMILY_NAMES}
Current Date and Time: {now_str}

Guidelines:
1. Always respect the dietary constraints, forbidden meats, and organic target (append '(Buy Organic)' to the USDA Dirty Dozen).
2. The active planning week is Saturday-to-Friday. If scheduling meals, align them with this week.
3. If they ask to add/update items on the shopping list, use tools like `create_shopping_list_item` or `update_shopping_list_item`. Use the active shopping list UUID.
4. If they ask to update/change the plan, use tools like `create_mealplan` or `create_mealplan_bulk`. If you need to replace, swap, or change an existing meal, first query the current plan using `get_all_mealplans` for the specific date/range, retrieve the `id` of the entry you want to replace, call `delete_mealplan(entry_id=...)` to delete it, and then call `create_mealplan` to schedule the new meal. Whenever you modify the meal plan (by creating, deleting, or changing meals), you MUST immediately call the `sync_shopping_list` tool afterwards to automatically regenerate the active shopping list and ensure that the list, staples, and USDA Dirty Dozen organic tags are in sync.
5. If they want to import a recipe from a URL, use the `create_recipe_from_url` tool.
6. If they ask to parse ingredients or free-text items (freezer, pantry, or fridge lists), you MUST use the `parse_ingredients` tool. Do NOT attempt to parse them yourself. Present the parsed results to the user.
7. When answering questions about ingredients in the meal plan, you MUST use the `get_detailed_meal_plan` tool to see the actual ingredients within the scheduled recipes. Do not rely solely on `get_all_mealplans` as it only provides titles.
8. When answering other questions, retrieve the relevant information (e.g., `get_recipes`, `get_shopping_lists`, or `get_shopping_list_items`) to provide accurate answers.
9. You are encouraged to use your general knowledge to answer culinary and nutritional questions (e.g., "What does nutritional yeast do?", "How do I cook this?", "Which recipe uses these mushrooms?"). Help Nathan and Kristin understand and enjoy their food.
10. Be brief, friendly, and helpful. Always explain what updates you did.
11. If the user asks to add or schedule a specific meal by name (e.g., "add corn chowder"), you MUST first search their collection using the `get_recipes` tool with a search query. If a matching recipe is found, schedule it using its `recipe_id`. If no matching recipe is found in their collection, do NOT silently schedule it as a text placeholder; instead, tell them that the recipe was not found in their collection, and ask if they would like you to import one from a URL, or if they prefer to schedule it as a text placeholder first.
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
        model_name = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash')
        
    mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")
    server_params = StdioServerParameters(
        command="python3",
        args=[os.path.join(base_dir, "mealie_planner", "mcp_server.py")],
        env={
            "PYTHONPATH": f"{mcp_src_dir}:{base_dir}",
            "MEALIE_BASE_URL": os.getenv("MEALIE_API_URL", "http://mealie:9000"),
            "MEALIE_API_KEY": os.getenv("MEALIE_TOKEN"),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "GEMINI_MODEL": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
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
                
            # Loop for Gemini to call functions
            system_instruction = get_system_prompt()
            api_key = os.getenv('GOOGLE_API_KEY')
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            
            session_http = requests.Session()
            max_turns = 10
            for turn in range(max_turns):
                payload = {
                    "contents": contents,
                    "systemInstruction": {
                        "parts": [{"text": system_instruction}]
                    }
                }
                if gemini_tools:
                    payload["tools"] = gemini_tools
                    
                resp = session_http.post(url, json=payload, timeout=90)
                resp.raise_for_status()
                data = resp.json()
                
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
