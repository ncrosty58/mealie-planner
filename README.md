# Mealie AI Companion Planner 🍽️

An intelligent, Gemini-powered weekly menu planner, automated shopping list syncer, and email notifier companion for **Mealie**.

This companion app interfaces with your Mealie instance to automate weekly menu curation, sequence meals based on ingredient perishability, run Blackstone griddle compatibility checks, sync shopping lists, and send automated kitchen briefings.

---

## 🌟 Key Features

### 1. Intelligent Weekly Planning
* **Saturday-to-Friday Range:** Anchored on the standard weekly schedule.
* **Perishability Sequencing:** Automatically sequences meals so that fresh/perishable ingredients (like fish or soft greens) are eaten early in the week (Sat-Tue), while frozen or pantry items are scheduled later (Wed-Fri).
* **Inventory Priority:** Prioritizes using up freezer, pantry, and fridge items.
* **Exclusions & Dietary Rules:** Strictly respects day-level exclusions and dietary rules (e.g. pescatarian limits, pork boundaries).

### 2. Semantic Blackstone Griddle Compatibility
* Uses Gemini AI to analyze recipe names and instruction sets for outdoor flat top griddle compatibility (stir-fries, smash burgers, fajitas, hibachi).
* Adds a `Griddle` badge to matching dinners on the dashboard and injects batch-cooking prep suggestions.

### 3. Active Shopping List Syncer
* Offloads raw ingredients from scheduled recipes, cleans names, filters out staples, and writes them to your Mealie active shopping list.
* **Hallucination Protection:** Employs integer-indexed map tracking to ensure Mealie database UUIDs are never lost or typoed by the LLM, preserving checkmarks and item states on updates.

### 4. Interactive AI Swap Recommendations
* Click **Swap Dinner** on any upcoming day on the dashboard UI to asynchronously fetch 3 alternative suggestions from your recipe database.
* The AI dynamically selects alternatives that reuse overlapping fresh ingredients already required by the other dinners of the week to **minimize grocery waste**.

### 5. Automated Email Briefings
* **Saturday Report:** Sent immediately upon menu generation, summarizing the week's layout, griddle tips, shopping list additions, and nutritional averages.
* **Daily Briefing:** Sent Sunday through Friday at 7:00 AM (New York time) containing today's menu, tomorrow's prep reminders, and a daily nutrition compared to standard RDA references.

---

## 🛠️ Architecture & Tech Stack

* **Backend:** Python 3.12, Flask, APScheduler
* **Frontend:** Vanilla JS, CSS (Clean design tokens, responsive grid systems, safe-area mobile safe paddings)
* **LLM Engine:** Google Gemini (model configurable via `GEMINI_MODEL`, default `gemini-3.5-flash`; uses structured JSON schemas and zero-shot prompt flows)
* **Real-time Updates:** HTML5 Server-Sent Events (SSE) progress streams

---

## ⚙️ Setup & Installation

### 1. Configuration
Create a `.env` file in the root directory (refer to `.env.example` as a template):

```env
# --- Flask ---
SECRET_KEY=your_flask_secret_key

# --- Mealie Configuration ---
MEALIE_API_URL=http://mealie:9000
MEALIE_FRONTEND_URL=https://your-mealie-domain.com
MEALIE_TOKEN=your_mealie_api_token
MEALIE_ACTIVE_LIST_ID=your_active_shopping_list_id
MEALIE_STAPLES_LIST_ID=your_staples_list_id

# --- AI Vendor & Model Configuration ---
# Active AI Vendor: "gemini" or "openai" or "deepseek" (defaults to "gemini")
AI_VENDOR=gemini

# --- Google Gemini Settings (for AI_VENDOR=gemini) ---
GOOGLE_API_KEY=your_google_ai_studio_api_key
GEMINI_CORE_MODEL=gemini-3.5-flash
GEMINI_CHAT_MODEL=gemini-3.5-flash
# Legacy override fallback
GEMINI_MODEL=gemini-3.5-flash

# --- OpenAI / DeepSeek Settings (for AI_VENDOR=openai or deepseek) ---
AI_API_KEY=your_api_key
AI_BASE_URL=https://api.deepseek.com
OPENAI_CORE_MODEL=gpt-4o-mini
OPENAI_CHAT_MODEL=gpt-4o

# --- SMTP configuration for reports ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_specific_password
SMTP_FROM_EMAIL=your_email@gmail.com
SMTP_FROM_NAME=Mealie Companion

# --- General Preferences ---
MEALIE_PLANNER_APP_URL=https://mealie-planner.example
FAMILY_RECIPIENT_EMAILS=person_a@example.com,person_b@example.com
APP_TIMEZONE=America/New_York
```

### 2. Vendored MCP server (submodule)
The Mealie MCP client/tools live in `mealie-mcp-server/`, tracked as a git submodule.
When cloning, pull it too:

```bash
git clone --recurse-submodules <this-repo>
# or, if already cloned:
git submodule update --init
```

The app imports from this directory at startup, so the submodule must be populated.

### 3. Run with Docker Compose
Build and run the stack:

```bash
docker compose up -d --build
```

The planner will be accessible locally at `http://localhost:9926`.

---

## 📂 Project Structure

* `/mealie_planner/`: Core Python modules (clients, generators, parsers, syncers).
* `/templates/`: Jinja2 dashboard template.
* `/static/`: Web app assets (manifest, sw.js, favicon).
* `/scripts/`: CLI tools for wipe/reset operations and debugging.
* `.agents/skills/`: Markdown definitions of agentic rules, scoring metrics, and exclusions.
