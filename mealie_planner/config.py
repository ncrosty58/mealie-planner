import os

# Mealie API List IDs
ACTIVE_LIST_ID = os.getenv('MEALIE_ACTIVE_LIST_ID', '9a1e2d1e33f24f27a01fef55c89a92de')
STAPLES_LIST_ID = os.getenv('MEALIE_STAPLES_LIST_ID', '1196f23a527b42a9a75b1c3850251948')

# Skill parsing logic
def load_skill_md(skill_name, skill_path="SKILL.md", strip_front=True):
    """Load the content of a SKILL.md file."""
    # Find the parent of mealie_planner dir
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base_dir, '.agents', 'skills', skill_name, skill_path)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if strip_front and content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
    return ""

def extract_section(content, section_name):
    """Extract a specific section from markdown content."""
    lines = content.split('\n')
    start_line = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(f'## {section_name}'):
            start_line = i + 1
            break
    
    if start_line == -1:
        return ""
    
    section_lines = []
    for line in lines[start_line:]:
        if line.strip().startswith('## '):
            break
        section_lines.append(line)
    
    return '\n'.join(section_lines).strip()

def parse_frontmatter(content):
    """Parse YAML-like frontmatter from markdown content."""
    if not content.startswith('---'):
        return {}
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}
    yaml_text = parts[1]
    metadata = {}
    for line in yaml_text.split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            metadata[key.strip()] = val.strip()
    return metadata

# Read config dynamically from SKILL.md
_SKILL_MD_CONTENT = load_skill_md('meal-planner', strip_front=False)
_METADATA = parse_frontmatter(_SKILL_MD_CONTENT)

FAMILY_NAMES = _METADATA.get('family_names', 'Nathan & Kristin')
TIMEZONE = os.getenv('APP_TIMEZONE', _METADATA.get('timezone', 'America/New_York'))
APP_URL = os.getenv('MEALIE_PLANNER_APP_URL', _METADATA.get('app_url', 'https://mealie-planner.cosmoslab.dev'))

raw_emails = os.getenv('FAMILY_RECIPIENT_EMAILS', _METADATA.get('recipient_emails', 'nathan@example.com,kristin@example.com'))
FAMILY_RECIPIENT_EMAILS = [email.strip() for email in raw_emails.split(',')]

FAMILY_DIETARY_RULES_PROMPT = f"""
=== FAMILY DIETARY RULES ===
{extract_section(_SKILL_MD_CONTENT, 'Household & Dietary Constraints')}
"""

# Skill definitions (exposed for compatibility with test scripts)
_RECIPE_FINDER_SKILL_DEFINITION = load_skill_md('recipe-finder')
_MEAL_EXCLUSION_PARSING_SKILL_DEFINITION = load_skill_md('meal-exclusion-parsing')
_WEEKLY_MEAL_SELECTION_SKILL_DEFINITION = load_skill_md('weekly-meal-selection')
_SHOPPING_LIST_SYNC_SKILL_DEFINITION = load_skill_md('shopping-list-sync')
_RECIPE_NUTRITION_IMPUTATION_SKILL_DEFINITION = load_skill_md('recipe-nutrition-imputation')
_BANNED_RECIPES_SKILL_DEFINITION = load_skill_md('banned-recipes')
_INGREDIENT_PARSING_SKILL_DEFINITION = load_skill_md('ingredient-parsing')
_BLACKSTONE_COMPATIBILITY_SKILL_DEFINITION = load_skill_md('blackstone-compatibility')
_INGREDIENT_STANDARDIZATION_SKILL_DEFINITION = load_skill_md('ingredient-standardization')
_DAILY_BRIEFING_GENERATION_SKILL_DEFINITION = load_skill_md('daily-briefing-generation')
_WEEKLY_THEMES_SYNOPSIS_SKILL_DEFINITION = load_skill_md('weekly-themes-synopsis')

# Breakfast Nutrition Profiles
BREAKFAST_PROFILES = {
    "English Muffins with Jam": {
        "calories": 220, "protein": 5, "carbs": 40, "fat": 2, "fiber": 2, "sodium": 320, "sugar": 10, "cholesterol": 0
    },
    "Toast with Jam": {
        "calories": 200, "protein": 4, "carbs": 35, "fat": 2, "fiber": 2, "sodium": 300, "sugar": 10, "cholesterol": 0
    },
    "Bagels & Cream Cheese": {
        "calories": 380, "protein": 11, "carbs": 55, "fat": 12, "fiber": 2, "sodium": 500, "sugar": 6, "cholesterol": 30
    },
    "Yogurt with Granola": {
        "calories": 250, "protein": 12, "carbs": 35, "fat": 5, "fiber": 3, "sodium": 100, "sugar": 15, "cholesterol": 15
    },
    "Cereal & Milk": {
        "calories": 300, "protein": 8, "carbs": 50, "fat": 6, "fiber": 3, "sodium": 200, "sugar": 12, "cholesterol": 15
    },
    "Oats": {
        "calories": 280, "protein": 10, "carbs": 48, "fat": 5, "fiber": 8, "sodium": 115, "sugar": 12, "cholesterol": 0
    }
}

# Lunch Nutrition Profiles
LUNCH_LEFTOVER_PROFILE = {
    "calories": 500, "protein": 22, "carbs": 55, "fat": 15, "fiber": 5, "sodium": 600, "sugar": 5, "cholesterol": 40
}

LUNCH_SANDWICH_PROFILE = {
    "calories": 450, "protein": 18, "carbs": 45, "fat": 14, "fiber": 4, "sodium": 800, "sugar": 6, "cholesterol": 35
}

# Recommended Daily Allowances (Individual Baseline Reference)
RDA = {
    "calories": 2000,
    "protein": 50,
    "carbs": 275,
    "fat": 70,
    "fiber": 28,  # Target high fiber
    "sodium": 2300,
    "sugar": 50,
    "cholesterol": 300
}

def get_banned_recipes():
    """Load the list of banned recipes from the banned-recipes skill."""
    content = load_skill_md('banned-recipes')
    if not content:
        return []
    section = extract_section(content, 'Banned Recipes List')
    banned = []
    for line in section.split('\n'):
        line = line.strip()
        if line.startswith('- ') or line.startswith('* '):
            # Extract recipe name up to the colon (if present) or just the whole line
            name = line[2:].split(':', 1)[0].strip()
            # Strip markdown formatting asterisks
            name = name.replace('**', '').replace('*', '').strip()
            if name:
                banned.append(name)
    return banned
