import os
import json
import threading
import queue
import time
from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_from_directory, make_response
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.ai_client import AIClient
from mealie_planner.plan_generator import PlanGenerator
from mealie_planner.shopping_sync import ShoppingListSync
from mealie_planner.recipe_nutrition import RecipeNutrition
from mealie_planner.recipe_crawler import RecipeCrawler
from mealie_planner.email_notifier import EmailNotifier, setup_scheduler
from mealie_planner.config import ACTIVE_LIST_ID, STAPLES_LIST_ID, RDA, TIMEZONE, APP_URL, FAMILY_RECIPIENT_EMAILS, FAMILY_NAMES, SWAP_RECOMMENDATIONS_PROMPT_TEMPLATE
from mealie_planner.utils import get_active_week_strings, get_planning_week_strings, get_planning_week_range, sanitize_input, extract_ingredient_texts
from scripts.clear_mealie import wipe_mealie_data

# Mealie configuration
MEALIE_API_URL = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
MEALIE_FRONTEND_URL = os.getenv('MEALIE_FRONTEND_URL', 'https://your-mealie-domain.example')
STATE_FILE = "data/planner_state.json"
CHAT_HISTORY_FILE = "data/chat_history.json"

app = Flask(__name__)

def load_chat_history():
    """Load persisted chat history."""
    if os.path.exists(CHAT_HISTORY_FILE):
        try:
            with open(CHAT_HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"history": [], "messages": []}
    return {"history": [], "messages": []}

def save_chat_history(history, messages):
    """Save persisted chat history."""
    os.makedirs(os.path.dirname(CHAT_HISTORY_FILE), exist_ok=True)
    with open(CHAT_HISTORY_FILE, 'w') as f:
        json.dump({"history": history, "messages": messages}, f)
app.secret_key = os.getenv('SECRET_KEY', 'mealie_companion_secret_9926')

# ---------- Composition Root (DI wiring) ----------
mealie_client = UnifiedMealieClient()
ai_client = AIClient()
crawler = RecipeCrawler(mealie_client, ai_client)
shopping = ShoppingListSync(mealie_client, ai_client, crawler)
notifier = EmailNotifier(mealie_client, ai_client)
nutrition = RecipeNutrition(mealie_client, ai_client)
plan_generator = PlanGenerator(mealie_client, ai_client, crawler, shopping, notifier)
# ----------------------------------------------------

def load_state():
    """Load persisted application state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(updates):
    """Save/update application state."""
    state = load_state()
    state.update(updates)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# Template filters
@app.template_filter('select_day_name')
def select_day_name(date_str):
    """Convert YYYY-MM-DD to full day name."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')
    except:
        return date_str

@app.route('/')
def index():
    success_msg = request.args.get('success_msg')
    error_msg = request.args.get('error_msg')
    
    if success_msg:
        flash(success_msg, "success")
    if error_msg:
        flash(error_msg, "danger")
        
    state = load_state()
    current_week_low_staples = state.get('low_staples', [])
    emails_enabled = state.get('emails_enabled', True)
    disabled_recipient_emails = state.get('disabled_recipient_emails', [])

    # Fetch Mealie users for the recipient management UI
    mealie_users = []
    try:
        mealie_users = mealie_client.get_users()
    except Exception as e:
        print(f"Error fetching Mealie users: {e}")

    # Get active week selection
    week = request.args.get('week', 'current')
    if week not in ('current', 'next'):
        week = 'current'

    # Get active week range (for Dashboard display)
    if week == 'next':
        from mealie_planner.utils import get_next_week_range
        planning_start, planning_end = get_next_week_range()
        active_start_str = planning_start.strftime("%Y-%m-%d")
        active_end_str = planning_end.strftime("%Y-%m-%d")
        planning_start_str = active_start_str
        planning_end_str = active_end_str
    else:
        active_start_str, active_end_str = get_active_week_strings()
        
        # Get planning week range (for Questionnaire and planning check)
        planning_start, planning_end = get_planning_week_range()
        planning_start_str = planning_start.strftime("%Y-%m-%d")
        planning_end_str = planning_end.strftime("%Y-%m-%d")
    
    # Current date for graying out past days in UI
    tz = pytz.timezone(TIMEZONE)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    # Fetch meal plans for active week
    meal_plans = []
    try:
        meal_plans = mealie_client.get_meal_plan(active_start_str, active_end_str)
    except Exception as e:
        print(f"Error fetching meal plan: {e}")

    # Check if there are scheduled dinner entries in the active week
    dinners_scheduled = [
        p for p in meal_plans 
        if p['entryType'] == 'dinner' 
        and p['date'][:10] >= active_start_str 
        and p['date'][:10] <= active_end_str 
        and (p.get('recipeId') or p.get('title') or p.get('text'))
    ]
    
    is_submitted = bool(meal_plans)

    # Get data for UI
    staples = []
    try:
        staples = mealie_client.get_shopping_list_items(STAPLES_LIST_ID)
    except Exception as e:
        print(f"Error reading staples list: {e}")

    # All recipes for UI swap options
    all_recipes = []
    try:
        all_recipes = mealie_client.get_all_recipes()
    except Exception as e:
        print(f"Error reading recipes: {e}")

    formatted_list_id = ACTIVE_LIST_ID
    if len(ACTIVE_LIST_ID) == 32:
        formatted_list_id = f"{ACTIVE_LIST_ID[:8]}-{ACTIVE_LIST_ID[8:12]}-{ACTIVE_LIST_ID[12:16]}-{ACTIVE_LIST_ID[16:20]}-{ACTIVE_LIST_ID[20:]}"

    if is_submitted:
        # Dashboard View - Displays the FULL active week (preserved past + new)
        daily_nutrition, averages = nutrition.calculate_nutrition_for_range(active_start_str, active_end_str)
        
        for p in meal_plans:
            if p['entryType'] == 'dinner' and p.get('recipeId'):
                try:
                    r_details = mealie_client.get_recipe_details(p['recipeId'])
                    p['is_blackstone'] = crawler.check_blackstone_compatibility(r_details)
                except:
                    p['is_blackstone'] = False
            else:
                p['is_blackstone'] = False

        shopping_list = []
        try:
            shopping_list = mealie_client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
            # Sort by label name first (to group them for the UI), then by position
            def get_sort_key(item):
                label = item.get('label')
                name = label.get('name') if isinstance(label, dict) else 'Uncategorized'
                return (name if name != 'Uncategorized' else 'ZZZ', item.get('position', 0), item.get('note', ''))
            
            shopping_list.sort(key=get_sort_key)
        except Exception as e:
            print(f"Error reading active shopping list: {e}")

        active_start_obj = datetime.strptime(active_start_str, "%Y-%m-%d")
        planning_dates = [(active_start_obj + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        return render_template(
            'index.html',
            is_submitted=True,
            start_date=active_start_str,
            end_date=active_end_str,
            planning_dates=planning_dates,
            meal_plans=meal_plans,
            shopping_list=shopping_list,
            daily_nutrition=daily_nutrition,
            averages=averages,
            rda=RDA,
            all_recipes=all_recipes,
            staples=staples,
            low_staples=current_week_low_staples,
            mealie_url=MEALIE_FRONTEND_URL,
            active_list_id=formatted_list_id,
            week_view='current',
            today_str=today_str,
            emails_enabled=emails_enabled,
            mealie_users=mealie_users,
            disabled_recipient_emails=disabled_recipient_emails,
            family_names=FAMILY_NAMES,
            week=week,
        )
    else:
        # Questionnaire View - Displays and plans for the REMAINING dates
        return render_template(
            'index.html',
            is_submitted=False,
            start_date=planning_start_str,
            end_date=planning_end_str,
            staples=staples,
            low_staples=current_week_low_staples,
            today_str=today_str,
            emails_enabled=emails_enabled,
            mealie_users=mealie_users,
            disabled_recipient_emails=disabled_recipient_emails,
            family_names=FAMILY_NAMES,
            week=week,
        )

@app.route('/plan', methods=['POST'])
def plan():
    """
    Placeholder for the plan submission. 
    The actual generation is handled by the plan-stream SSE endpoint via JavaScript.
    """
    return redirect(url_for('index'))

@app.route('/plan-stream')
def plan_stream():
    """SSE endpoint for streaming plan generation progress."""
    exclude_text = sanitize_input(request.args.get('exclude_text', ''))
    freezer_items = sanitize_input(request.args.get('freezer_items', ''))
    special_requests = sanitize_input(request.args.get('special_requests', ''))
    week = request.args.get('week', 'current')
    
    save_state({
        "exclude_text": exclude_text,
        "freezer_items": freezer_items,
        "special_requests": special_requests
    })
    
    state = load_state()
    low_staples_ids = state.get('low_staples', [])

    def generate():
        # Use the pre-wired global instances
        q = queue.Queue()
        def callback(msg, progress=None):
            q.put({"status": msg, "progress": progress})

        if week == 'next':
            from mealie_planner.utils import get_next_week_range
            start_date, end_date = get_next_week_range()
            start_date_str = start_date.strftime("%Y-%m-%d")
            end_date_str = end_date.strftime("%Y-%m-%d")
        else:
            start_date_str, end_date_str = get_planning_week_strings()

        thread = threading.Thread(target=plan_generator.generate_weekly_plan, kwargs={
            "start_date_str": start_date_str,
            "end_date_str": end_date_str,
            "exclude_text": exclude_text,
            "freezer_items": freezer_items,
            "special_requests": special_requests,
            "low_staples_ids": low_staples_ids,
            "progress_callback": callback
        })
        thread.start()

        while thread.is_alive() or not q.empty():
            try:
                data = q.get(timeout=1)
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                continue

        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/update-staples', methods=['POST'])
def update_staples():
    """Fast endpoint specifically for the staples modal."""
    if request.form.get('staples_submitted'):
        low_staples = request.form.getlist('low_staples')
        save_state({'low_staples': low_staples})
        
        try:
            shopping.sync_staples_only(low_staples)
            flash("Staples updated successfully!", "success")
        except Exception as e:
            flash(f"Error updating staples: {str(e)}", "danger")

    return redirect(url_for('index'))

@app.route('/sync', methods=['POST'])
def sync():
    """Manual trigger to re-sync the shopping list based on current plans."""
    week = request.form.get('week', 'current')
    if week == 'next':
        from mealie_planner.utils import get_next_week_range
        next_start, next_end = get_next_week_range()
        start_date_str = next_start.strftime("%Y-%m-%d")
        end_date_str = next_end.strftime("%Y-%m-%d")
    else:
        start_date_str, end_date_str = get_active_week_strings()

    state = load_state()
    low_staples = state.get('low_staples', [])

    # If the request comes from the staples modal, update the state
    if request.form.get('staples_submitted'):
        low_staples = request.form.getlist('low_staples')
        save_state({'low_staples': low_staples})

    try:
        shopping.sync_shopping_list(start_date_str, end_date_str, low_staples_ids=low_staples)
        flash("Recalculated active shopping list successfully!", "success")
    except Exception as e:
        flash(f"Error syncing shopping list: {str(e)}", "danger")

    return redirect(url_for('index', week=week))

@app.route('/update-admin', methods=['POST'])
def update_admin():
    """Update general administration settings (emails toggle + per-recipient opt-outs)."""
    emails_enabled = request.form.get('emails_enabled') == '1'
    # Collect unchecked emails — the form submits enabled addresses as checkboxes,
    # so any known address absent from the form is considered disabled.
    all_known = [u.strip() for u in request.form.get('all_known_emails', '').split(',') if u.strip()]
    enabled_emails = set(request.form.getlist('enabled_recipients'))
    disabled_recipient_emails = [e for e in all_known if e not in enabled_emails]
    save_state({
        'emails_enabled': emails_enabled,
        'disabled_recipient_emails': disabled_recipient_emails,
    })
    flash(f"Admin settings updated! Emails {'enabled' if emails_enabled else 'disabled'}.", "success")
    return redirect(url_for('index'))

@app.route('/clear', methods=['POST'])
def clear_plan_route():
    week = request.form.get('week', 'current')
    try:
        wipe_mealie_data(week=week)
        save_state({
            'low_staples': [],
            'freezer_items': "",
            'exclude_text': "",
            'special_requests': ""
        })
        flash(f"Successfully cleared meal plans for {week} week and reset state!", "success")
    except Exception as e:
        flash(f"Error clearing data: {str(e)}", "danger")
    return redirect(url_for('index', week=week))

@app.route('/add-shopping-item', methods=['POST'])
def add_shopping_item():
    """Add a single manual item to the active shopping list."""
    try:
        data = request.get_json()
        note = sanitize_input(data.get('note', ''))
        if not note:
            return json.dumps({"success": False, "error": "Item name is required"}), 400

        mealie_client.add_shopping_list_item(ACTIVE_LIST_ID, note)
        return json.dumps({"success": True})
    except Exception as e:
        print(f"Error adding shopping item: {e}")
        return json.dumps({"success": False, "error": str(e)}), 500

@app.route('/toggle-shopping-item', methods=['POST'])
def toggle_shopping_item():
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        is_checked = data.get('checked')

        items = mealie_client.get_shopping_list_items(ACTIVE_LIST_ID)
        target_item = next((item for item in items if item['id'] == item_id), None)

        if not target_item:
            return json.dumps({"success": False, "error": "Item not found"}), 404

        target_item['checked'] = is_checked
        mealie_client.update_shopping_list_item(item_id, target_item)

        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}), 500

@app.route('/check-all-items', methods=['POST'])
def check_all_items():
    """Mark all items in the active shopping list as checked."""
    try:
        items = mealie_client.get_shopping_list_items_for_list(ACTIVE_LIST_ID)
        
        # Build bulk update payload
        bulk_items = []
        for item in items:
            if not item.get('checked'):
                item['checked'] = True
                bulk_items.append(item)
        
        if bulk_items:
            mealie_client.update_shopping_list_items_bulk(bulk_items)
            
        return json.dumps({"success": True, "count": len(bulk_items)})
    except Exception as e:
        print(f"Error checking all items: {e}")
        return json.dumps({"success": False, "error": str(e)}), 500

@app.route('/change-meal', methods=['POST'])
def change_meal():
    try:
        date_str = request.form.get('date')
        entry_id = request.form.get('entry_id')
        recipe_id = request.form.get('recipe_id')
        week = request.form.get('week', 'current')
        
        if entry_id:
            mealie_client.delete_meal_plan_entry(entry_id)
            
        if recipe_id != "SKIP":
            mealie_client.schedule_meal(date_str, "dinner", recipe_id=recipe_id)
            
        # Auto-sync is intentionally disabled here to prevent slow page reloads during consecutive swaps.
        # The user can manually click the "Refresh List" button once they've finished making changes.
        pass
        
        flash(f"Successfully updated meal for {date_str}! (Remember to click 'Refresh List' in the sidebar to sync your groceries when done.)", "success")
    except Exception as e:
        flash(f"Error updating meal: {e}", "danger")
        
    return redirect(url_for('index', week=week))

@app.route('/get-swap-recommendations')
def get_swap_recommendations():
    date_str = request.args.get('date')
    if not date_str:
        return Response(json.dumps([]), mimetype='application/json')
        
    try:
        # 1. Fetch target week's scheduled meals and recipes dynamically based on date_str
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_since_saturday = (target_date.weekday() - 5 + 7) % 7
        start_of_week = target_date - timedelta(days=days_since_saturday)
        end_of_week = start_of_week + timedelta(days=6)
        active_start_str = start_of_week.strftime("%Y-%m-%d")
        active_end_str = end_of_week.strftime("%Y-%m-%d")
        
        meal_plans = mealie_client.get_meal_plan(active_start_str, active_end_str)
        
        # Extract the other dinners planned this week (excluding the target date we are swapping)
        other_dinners = []
        target_dinner_name = ""
        for p in meal_plans:
            if p['entryType'] == 'dinner':
                if p['date'][:10] == date_str:
                    if p.get('recipe'):
                        target_dinner_name = p['recipe']['name']
                else:
                    if p.get('recipe'):
                        other_dinners.append(p['recipe'])
                        
        # 2. Get all recipes from the database
        all_recipes = mealie_client.get_all_recipes()
        
        # Compile list of other dinner names/ingredients for context
        other_dinner_context = []
        for r in other_dinners:
            # Fetch details to get ingredients
            try:
                det = mealie_client.get_recipe_details(r['id'])
                ingredients = extract_ingredient_texts(det)
                other_dinner_context.append({
                    "name": r['name'],
                    "ingredients": ingredients
                })
            except Exception as context_err:
                print(f"[Swap Recs] Error loading context details for {r['name']}: {context_err}")
                other_dinner_context.append({"name": r['name'], "ingredients": []})
                
        # Compile candidate recipes (excluding the ones already planned and the target one)
        planned_names = {r['name'].lower() for r in other_dinners}
        if target_dinner_name:
            planned_names.add(target_dinner_name.lower())
            
        candidates = []
        for r in all_recipes:
            if r['name'].lower() not in planned_names:
                candidates.append({
                    "id": r['id'],
                    "name": r['name'],
                    "description": (r.get("description") or "")[:120],
                    "tags": [t.get('name', t) if isinstance(t, dict) else t for t in r.get('tags', [])]
                })
                
        # Limit to 35 candidates to avoid exceeding AI context constraints
        import random
        if len(candidates) > 35:
            candidates = random.sample(candidates, 35)
                
        prompt = SWAP_RECOMMENDATIONS_PROMPT_TEMPLATE.format(
            date_str=date_str,
            target_dinner_name=target_dinner_name or 'None',
            other_dinner_context=json.dumps(other_dinner_context, indent=2),
            candidates=json.dumps(candidates, indent=2)
        )

        raw = ai_client.call(prompt, expect_json=True)
        result = json.loads(raw)
        
        # Verify result is a list
        if not isinstance(result, list):
            raise ValueError("AI response is not a list")
            
        return Response(json.dumps(result[:3]), mimetype='application/json')
    except Exception as e:
        print(f"Error getting swap recommendations: {e}")
        # Fallback to random 3 recipes from database
        import random
        try:
            all_recipes = mealie_client.get_all_recipes()
            fallback = [{"id": r["id"], "name": r["name"]} for r in random.sample(all_recipes, min(3, len(all_recipes)))]
            return Response(json.dumps(fallback), mimetype='application/json')
        except Exception as fallback_err:
            print(f"Fallback recipe selection failed: {fallback_err}")
            return Response(json.dumps([]), mimetype='application/json')

@app.route('/chat-history', methods=['GET'])
def get_chat_history():
    """Endpoint to fetch the server-side chat history."""
    return json.dumps(load_chat_history())

@app.route('/chat-clear', methods=['POST'])
def clear_chat_history():
    """Endpoint to clear the server-side chat history."""
    save_chat_history([], [])
    return json.dumps({"success": True})

@app.route('/chat', methods=['POST'])
def chat():
    from mealie_planner.mcp_agent import run_mcp_chat
    import asyncio
    try:
        data = request.get_json()
        message = data.get('message', '')
        week = data.get('week', 'current')
        
        # Load existing chat history from the server
        chat_data = load_chat_history()
        history = chat_data.get("history", [])
        messages = chat_data.get("messages", [])
        
        # Append user message immediately and save
        messages.append({"s": "user", "t": message})
        save_chat_history(history, messages)
        
        if week == 'next':
            from mealie_planner.utils import get_next_week_range
            next_start, next_end = get_next_week_range()
            week_start_str = next_start.strftime("%Y-%m-%d")
            week_end_str = next_end.strftime("%Y-%m-%d")
        else:
            week_start_str, week_end_str = get_active_week_strings()
        
        # Run chat with persistent history
        reply, new_history, plan_changed = asyncio.run(run_mcp_chat(
            history, message, week_start_str=week_start_str, week_end_str=week_end_str
        ))
        
        # Append bot reply and save updated history
        messages.append({"s": "bot", "t": reply})
        save_chat_history(new_history, messages)
        
        if plan_changed:
            try:
                state = load_state()
                low_staples = state.get('low_staples', [])
                shopping.sync_shopping_list(week_start_str, week_end_str, low_staples_ids=low_staples)
            except Exception as sync_err:
                print(f"[Chat Auto-Sync] Error during auto-sync: {sync_err}")
        
        return json.dumps({
            "success": True,
            "reply": reply,
            "history": new_history,
            "plan_changed": plan_changed
        })
    except Exception as e:
        print(f"Chat error: {e}")
        # Save a friendly error message to the history so it doesn't leave the UI in an inconsistent state
        chat_data = load_chat_history()
        history = chat_data.get("history", [])
        messages = chat_data.get("messages", [])
        messages.append({"s": "bot", "t": "Chef is having some technical difficulties. Please try again."})
        save_chat_history(history, messages)
        return json.dumps({"success": False, "error": str(e)}), 500

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    response = make_response(send_from_directory('static', 'sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

if __name__ == '__main__':
    # Start background scheduler if not in debug mode to avoid duplicate jobs
    setup_scheduler(mealie_client, ai_client)
    print("Background scheduler started successfully.")
    
    app.run(host='0.0.0.0', port=9926, debug=False)
