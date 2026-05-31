import os
import sys
import logging
import traceback
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# Add mealie-mcp-server/src to the python path to import vendored tools and client
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp_src_dir = os.path.join(base_dir, "mealie-mcp-server", "src")

# Critical: Ensure mcp_src_dir is at the VERY FRONT to avoid shadowing 'utils' or 'mealie'
# Also remove the script's own directory from sys.path to prevent 'from .config import TIMEZONE' errors
# in files that are improperly imported as top-level modules.
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
if mcp_src_dir not in sys.path:
    sys.path.insert(0, mcp_src_dir)
if base_dir not in sys.path:
    sys.path.append(base_dir)

from tools import register_all_tools
from mealie_planner.unified_client import UnifiedMealieClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mealie-planner-mcp")

# Initialize the Unified Client
try:
    mealie = UnifiedMealieClient()
except Exception as e:
    logger.error(f"Failed to initialize UnifiedMealieClient: {e}")
    raise

# Initialize FastMCP
mcp = FastMCP("mealie-planner")

# 1. Register all tools from the vendored mealie-mcp-server
register_all_tools(mcp, mealie)

# 2. Register Custom/Overlay Tools that override or extend the base tools

@mcp.tool()
def get_detailed_meal_plan(
    start_date: str,
    end_date: str
) -> List[Dict[str, Any]]:
    """Get meal plans enriched with full recipe details (ingredients, etc.).
    Use this to see exactly what is in the scheduled meals.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        List[Dict[str, Any]]: List of meal plan entries with nested recipe details.
    """
    try:
        return mealie.get_detailed_meal_plan(start_date, end_date)
    except Exception as e:
        raise ToolError(f"Error fetching detailed meal plan: {str(e)}")

@mcp.tool()
def create_recipe_from_url(url: str) -> Dict[str, Any]:
    """Create a new recipe by scraping/importing from a URL with automatic ingredient parsing.

    Args:
        url: The URL of the recipe to import.

    Returns:
        Dict[str, Any]: Details of the created recipe.
    """
    try:
        logger.info(f"Creating recipe from URL: {url}")
        res = mealie.create_recipe_from_url(url)
        
        # Determine the recipe slug from the response
        if isinstance(res, str):
            slug = res
        elif isinstance(res, dict) and "slug" in res:
            slug = res["slug"]
        else:
            return res
            
        # Post-processing: Parse the ingredients using Mealie's NLP parser
        try:
            recipe_json = mealie.get_recipe(slug)
            raw_ingredients = []
            for ing in recipe_json.get("recipeIngredient", []):
                text = ing.get("note") or ing.get("display")
                if text:
                    raw_ingredients.append(text)
            
            if raw_ingredients:
                parsed = mealie.parse_raw_ingredients(raw_ingredients)
                recipe_json["recipeIngredient"] = parsed
                mealie.update_recipe(slug, recipe_json)
                res = mealie.get_recipe(slug)
        except Exception as parse_err:
            logger.warning(f"Failed to post-parse recipe ingredients for {slug}: {parse_err}")
            
        return res
    except Exception as e:
        raise ToolError(f"Error creating recipe from URL '{url}': {str(e)}")

@mcp.tool()
def parse_ingredients(raw_text: str) -> List[Dict[str, Any]]:
    """Parse free-text ingredients (like freezer/pantry items) into structured data.

    Args:
        raw_text: Comma-separated list of ingredients to parse.

    Returns:
        List[Dict[str, Any]]: Structured ingredient objects.
    """
    try:
        return mealie.parse_ingredients_with_ai(raw_text)
    except Exception as e:
        raise ToolError(f"Error parsing ingredients: {str(e)}")

@mcp.tool()
def create_recipe(
    name: str, ingredients: List[str], instructions: List[str]
) -> Dict[str, Any]:
    """Create a new recipe with automatic ingredient parsing.

    Args:
        name: The name of the new recipe.
        ingredients: A list of ingredients.
        instructions: A list of instructions.

    Returns:
        Dict[str, Any]: The created recipe details.
    """
    try:
        slug = mealie.create_recipe(name)
        recipe_json = mealie.get_recipe(slug)
        
        parsed = mealie.parse_raw_ingredients(ingredients)
        recipe_json["recipeIngredient"] = parsed
        recipe_json["recipeInstructions"] = [{"text": i} for i in instructions]
        return mealie.update_recipe(slug, recipe_json)
    except Exception as e:
        raise ToolError(f"Error creating recipe '{name}': {str(e)}")

@mcp.tool()
def update_recipe(
    slug: str,
    ingredients: List[str],
    instructions: List[str],
) -> Dict[str, Any]:
    """Replaces the ingredients and instructions of an existing recipe with automatic parsing.

    Args:
        slug: The unique text identifier for the recipe.
        ingredients: A list of ingredients.
        instructions: A list of instructions.

    Returns:
        Dict[str, Any]: The updated recipe details.
    """
    try:
        recipe_json = mealie.get_recipe(slug)
        parsed = mealie.parse_raw_ingredients(ingredients)
        recipe_json["recipeIngredient"] = parsed
        recipe_json["recipeInstructions"] = [{"text": i} for i in instructions]
        return mealie.update_recipe(slug, recipe_json)
    except Exception as e:
        raise ToolError(f"Error updating recipe '{slug}': {str(e)}")

if __name__ == "__main__":
    mcp.run()
