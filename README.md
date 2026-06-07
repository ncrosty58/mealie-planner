# Mealie AI Companion Planner 🍽️

An intelligent, AI-powered weekly menu planner, shopping list syncer, and email briefing companion for **[Mealie](https://mealie.io)**.

This companion app interfaces with your Mealie instance to automate weekly menu curation, sequence meals by ingredient perishability, run Blackstone griddle compatibility checks, sync shopping lists, and send automated kitchen briefings. It also ships an interactive AI chatbot for on-the-fly plan adjustments.

---

## 🌟 Key Features

### 1. Intelligent Weekly Planning
- **Saturday-to-Friday week:** Each plan is anchored on a Saturday start date and runs through the following Friday.
- **Perishability sequencing:** Fresh/perishable ingredients (fish, soft greens) are scheduled early in the week (Sat–Tue); frozen and pantry items land later (Wed–Fri).
- **Inventory priority:** Prioritizes using up freezer, pantry, and fridge items you already have.
- **Exclusions & dietary rules:** Strictly respects day-level exclusions and household dietary constraints.

### 2. Semantic Blackstone Griddle Compatibility
- Uses AI to analyze recipe names and instruction sets for outdoor flat-top griddle suitability (stir-fries, smash burgers, fajitas, hibachi).
- Adds a `Griddle` badge to matching dinners on the dashboard and injects batch-cooking prep suggestions.

### 3. Active Shopping List Syncer
- Offloads raw ingredients from scheduled recipes, cleans names, filters out staples, and writes them to your Mealie active shopping list.
- **Hallucination protection:** Uses integer-indexed map tracking so Mealie database UUIDs are never lost or typoed by the LLM — preserving checkmarks and item states across syncs.

### 4. Interactive AI Chatbot
- A built-in chat panel lets you ask questions about the plan ("what ingredients does Tuesday's dinner need?") or issue direct commands ("swap Thursday's dinner with something that uses the ground beef").
- The chatbot calls Mealie's API via the [MCP server](#vendored-mcp-server) and automatically re-syncs the shopping list whenever the plan changes.

### 5. Swap Recommendations
- Click **Swap Dinner** on any upcoming day to fetch three alternative recipe suggestions from your collection.
- The AI selects alternatives that reuse overlapping fresh ingredients already needed by the week's other dinners to minimize grocery waste.

### 6. Automated Email Briefings
- **Saturday report:** Sent immediately on plan generation — summarizes the week's layout, griddle tips, shopping list additions, and nutritional averages.
- **Daily briefing:** Sent Sunday through Friday at 7:00 AM (configurable timezone) with today's menu, tomorrow's prep reminders, and a daily nutrition summary vs. standard RDA references.

### 7. Progressive Web App (PWA)
- Installable from the browser on iOS and Android via a web app manifest and service worker.

---

## 🛠️ Architecture & Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask, APScheduler |
| Frontend | Vanilla JS, CSS (design tokens, responsive grid, mobile safe-area) |
| AI Engine | Google Gemini or OpenAI-compatible APIs (model configurable per area) |
| Real-time | HTML5 Server-Sent Events (SSE) for live plan-generation progress |
| MCP Integration | [mealie-mcp-server](https://github.com/rldiao/mealie-mcp-server) (git submodule) |

---

## ⚙️ Setup & Installation

### Prerequisites
- **Docker & Docker Compose** installed on the host.
- A running **Mealie** instance (`v1.x` or later) reachable by the container.
- An AI API key — Google AI Studio (Gemini) or an OpenAI-compatible provider.

> [!TIP]
> **Docker Networking:** Out of the box, the app runs on its own default bridge network and communicates with Mealie using Mealie's public URL/IP.
>
> If you run this app on the same host as your Mealie containers and prefer internal container-to-container routing (e.g. `MEALIE_API_URL=http://mealie:9000`), you can uncomment the custom network configuration block at the bottom of `docker-compose.yml` to have this container join your Mealie Docker network (usually named `mealie_default`).

---

### 1. Clone the repository

```bash
git clone --recurse-submodules https://github.com/<your-username>/mealie-planner.git
cd mealie-planner
```

If you already cloned without `--recurse-submodules`, initialize the submodule manually:

```bash
git submodule update --init
```

---

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
# --- Flask ---
SECRET_KEY=your_flask_secret_key          # any random string

# --- Mealie ---
MEALIE_API_URL=http://mealie:9000         # internal Docker hostname
MEALIE_FRONTEND_URL=https://mealie.example.com
MEALIE_TOKEN=your_mealie_api_token
MEALIE_ACTIVE_LIST_ID=your_active_shopping_list_uuid
MEALIE_STAPLES_LIST_ID=your_staples_list_uuid

# --- AI Vendor ---
# Options: "gemini" | "openai" | "deepseek"  (defaults to "gemini")
AI_VENDOR=gemini

# --- Google Gemini (for AI_VENDOR=gemini) ---
GOOGLE_API_KEY=your_google_ai_studio_api_key
GEMINI_CORE_MODEL=gemini-2.0-flash        # model used for planning & syncing
GEMINI_CHAT_MODEL=gemini-2.0-flash        # model used for the chatbot
# GEMINI_MODEL=gemini-2.0-flash           # legacy fallback if above are unset

# --- OpenAI / DeepSeek (for AI_VENDOR=openai or deepseek) ---
AI_API_KEY=your_api_key
AI_BASE_URL=https://api.openai.com/v1     # or https://api.deepseek.com
OPENAI_CORE_MODEL=gpt-4o-mini
OPENAI_CHAT_MODEL=gpt-4o

# --- SMTP (email briefings) ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_specific_password
SMTP_FROM_EMAIL=your_email@gmail.com
SMTP_FROM_NAME=Mealie Companion

# --- App / household ---
MEALIE_PLANNER_APP_URL=https://mealie-planner.example.com
FAMILY_NAMES="Nathan & Kristin"                        # Used for the dashboard branding and email headers
FAMILY_MEMBERS="Nathan, Kristin, Charlotte (11), Leah (6)" # Details of household members (optional, helps AI context)
FAMILY_RECIPIENT_EMAILS=person_a@example.com,person_b@example.com
APP_TIMEZONE=America/New_York

# --- Optional ---
# RECIPE_CACHE_TTL=600    # seconds to cache recipe details in-process (default: 600)
```

> [!TIP]
> **Finding your Mealie list UUIDs:** In Mealie, open your shopping list and look at the URL — it ends in the list's UUID (e.g. `.../shopping-lists/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). Alternatively, call `GET /api/groups/shopping/lists` with your token to list all shopping lists and their IDs.

> [!NOTE]
> **Gemini model names:** Valid Gemini model strings are of the form `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-1.5-pro`, etc. Check [Google AI Studio](https://aistudio.google.com) for the current model list. The hardcoded default `gemini-3.5-flash` in the source is a placeholder — **always set `GEMINI_CORE_MODEL` and `GEMINI_CHAT_MODEL` explicitly in your `.env`.**

---

### 3. Customize Household Preferences (Optional & Gitignored)

To avoid committing personal family details (like names, specific medical/dietary rules, or banned recipes) to git, the app loads these dynamically from local files inside the `data/` directory. If these files do not exist, the app falls back to the generic prompts defined under `.agents/skills/`.

#### A. Custom Dietary Rules
Create a file at `data/dietary_rules.txt` and fill it with your family-specific planning rules, preferences, and dietary targets (names and ages should go in `FAMILY_MEMBERS` in the `.env` file instead):

```text
- **Diet**: Omnivore. Prioritize high-protein recipes.
- **Dietary Restrictions**: Strict peanut allergy (NEVER purchase or schedule recipes with peanuts).
- **Organic Target**: Automatically append `(Buy Organic)` to USDA Dirty Dozen fruits/veg.
```

#### B. Banned Recipes List
Create a file at `data/banned_recipes.txt` and list any specific recipe titles (one per line) that the menu generator should never schedule:

```text
# Banned recipes (lines starting with # are ignored)
Cream of Cilantro Soup
Coriander Soup
Bacon Avocado Salad
```

---

### 4. Run with Docker Compose

```bash
docker compose up -d --build
```

The planner will be accessible at `http://localhost:9926`.

---

## 📂 Project Structure

```
mealie-planner/
├── app.py                   # Flask application, routes, APScheduler setup
├── mealie_planner/          # Core Python modules
│   ├── ai_client.py         # Vendor-agnostic AI client factory
│   ├── config.py            # Environment variable resolution
│   ├── email_notifier.py    # Saturday report & daily briefing emails
│   ├── mcp_agent.py         # Chatbot agent (calls Mealie via MCP)
│   ├── mcp_server.py        # MCP tool definitions for Mealie API
│   ├── plan_generator.py    # Core weekly meal planning logic
│   ├── recipe_crawler.py    # Recipe import & validation
│   ├── recipe_nutrition.py  # Nutritional data imputation
│   ├── shopping_sync.py     # Shopping list sync logic
│   └── unified_client.py   # Mealie API client with in-process caching
├── mealie-mcp-server/       # Git submodule — MCP server for Mealie API
├── templates/               # Jinja2 dashboard template
├── static/                  # PWA assets (manifest.json, sw.js, favicon)
├── scripts/                 # CLI utilities (see scripts/README.md)
├── tests/                   # Core unit tests
├── data/                    # Persistent app state (planner_state.json)
├── .agents/skills/          # AI agent skill definitions (see below)
├── docker-compose.yml
├── Dockerfile
├── pytest.ini               # Pytest configuration
└── .env.example
```

### `data/` directory
Contains `planner_state.json`, which persists runtime state such as the current low-staples list and per-recipient email toggle settings. This directory is bind-mounted by the compose file and survives container restarts.

### `.agents/skills/`
Markdown-based skill definitions consumed by AI coding assistants (e.g. Antigravity, Claude) when working on this codebase. They encode household dietary rules, scoring criteria, and agentic workflows. They are **not** loaded by the Flask app at runtime.

---

## 🔧 Vendored MCP Server

The MCP (Model Context Protocol) client lives in `mealie-mcp-server/`, tracked as a git submodule pointing to [github.com/rldiao/mealie-mcp-server](https://github.com/rldiao/mealie-mcp-server). The app imports from this directory at startup — **the submodule must be populated** or the app will fail to start.

---

## 📜 Scripts

See [`scripts/README.md`](scripts/README.md) for a full list of CLI utilities. Common ones:

| Script | Purpose |
|---|---|
| `scripts/clear_mealie.py` | Wipe current + next week meal plans and the active shopping list (**also imported by the app**) |
| `scripts/list_plans.py` | Print scheduled meal plans for inspection |
| `scripts/check_current_ingredients.py` | Print the ingredients currently driving the shopping list |
| `scripts/full_wipe_mealie.py` | ⚠️ Destructive — wipe a broader set of Mealie data |

Run from the project root:

```bash
python -m scripts.list_plans
```

---

## 🧪 Running Tests

To run the unit tests, install development/test dependencies and execute `pytest` from the project root:

```bash
pip install -r requirements.txt
pytest
```

> [!NOTE]
> Debug and profiling scripts in the `scripts/` folder (such as `scripts/test_breakfasts.py`) require a live Mealie instance, but the core unit tests in `tests/` are fully mocked and run offline.

---

## 📄 License

MIT

