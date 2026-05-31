import os
import sys
import queue
import threading
import json
from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_from_directory, make_response
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from mealie_planner.mealie_client import MealieClient
from mealie_planner.gemini_client import GeminiClient
from mealie_planner.plan_generator import PlanGenerator
from mealie_planner.shopping_sync import sync_shopping_list
from mealie_planner.recipe_nutrition import calculate_nutrition_for_range
from mealie_planner.recipe_crawler import check_blackstone_compatibility
from mealie_planner.email_notifier import EmailNotifier, send_email, send_daily_reminder_email
from mealie_planner.config import ACTIVE_LIST_ID, STAPLES_LIST_ID, RDA, TIMEZONE, APP_URL, FAMILY_RECIPIENT_EMAILS, FAMILY_NAMES
from mealie_planner.utils import get_active_week_strings, sanitize_input
from scripts.clear_mealie import wipe_mealie_data

MEALIE_API_URL = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
MEALIE_FRONTEND_URL = os.getenv('MEALIE_FRONTEND_URL', 'https://mealie.cosmoslab.dev')
STATE_FILE = "data/planner_state.json"

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'mealie_companion_secret_9926')

@app.template_filter('select_day_name')
def select_day_name(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%A")
    except Exception as e:
        print(f"Error parsing day name filter: {e}")
        return ""

def load_state():
    """Load persisted application state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    """Persist application state."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Error saving state: {e}")

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/')
def index():
    success_msg = request.args.get('success_msg')
    error_msg = request.args.get('error_msg')
    if success_msg:
        flash(success_msg, "success")
    if error_msg:
        flash(error_msg, "danger")
        
    client = MealieClient()
    state = load_state()
    current_week_low_staples = state.get('low_staples', [])

    # 1. Determine active week
    start_date_str, end_date_str = get_active_week_strings()
    meal_plans = client.get_meal_plan(start_date_str, end_date_str)
    
    # Check if there are scheduled dinner entries
    dinners = [p for p in meal_plans if p['entryType'] == 'dinner' and (p.get('recipeId') or p.get('title') or p.get('text'))]
    
    # 2. Get data for UI
    staples = []
    try:
        staples = client.get_shopping_list_items(STAPLES_LIST_ID)
    except Exception as e:
        print(f"Error reading staples list: {e}")

    all_recipes = []
    try:
        all_recipes = client.get_all_recipes()
    except Exception as e:
        print(f"Error reading recipes: {e}")

    if dinners:
        # Dashboard View
        daily_nutrition, averages = calculate_nutrition_for_range(start_date_str, end_date_str)
        
        for p in meal_plans:
            if p['entryType'] == 'dinner' and p.get('recipeId'):
                try:
                    r_details = client.get_recipe_details(p['recipeId'])
                    p['is_blackstone'] = check_blackstone_compatibility(r_details)
                except:
                    p['is_blackstone'] = False
            else:
                p['is_blackstone'] = False

        shopping_list = []
        try:
            shopping_list = client.get_shopping_list_items(ACTIVE_LIST_ID)
            shopping_list.sort(key=lambda x: x.get('position', 0))
        except Exception as e:
            print(f"Error reading active shopping list: {e}")

        start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d")
        planning_dates = [(start_date_obj + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        formatted_list_id = ACTIVE_LIST_ID
        if len(ACTIVE_LIST_ID) == 32:
            formatted_list_id = f"{ACTIVE_LIST_ID[:8]}-{ACTIVE_LIST_ID[8:12]}-{ACTIVE_LIST_ID[12:16]}-{ACTIVE_LIST_ID[16:20]}-{ACTIVE_LIST_ID[20:]}"

        return render_template(
            'index.html',
            is_submitted=True,
            start_date=start_date_str,
            end_date=end_date_str,
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
            active_list_id=formatted_list_id
        )
    else:
        # Questionnaire View
        formatted_list_id = ACTIVE_LIST_ID
        if len(ACTIVE_LIST_ID) == 32:
            formatted_list_id = f"{ACTIVE_LIST_ID[:8]}-{ACTIVE_LIST_ID[8:12]}-{ACTIVE_LIST_ID[12:16]}-{ACTIVE_LIST_ID[16:20]}-{ACTIVE_LIST_ID[20:]}"

        return render_template(
            'index.html',
            is_submitted=False,
            start_date=start_date_str,
            end_date=end_date_str,
            staples=staples,
            low_staples=current_week_low_staples,
            mealie_url=MEALIE_FRONTEND_URL,
            active_list_id=formatted_list_id
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
    """Server-Sent Events endpoint for real-time plan generation progress."""
    exclude_text = sanitize_input(request.args.get('exclude_text', ''))
    freezer_items = sanitize_input(request.args.get('freezer_items', ''))
    special_requests = sanitize_input(request.args.get('special_requests', ''))
    low_staples_ids = request.args.getlist('low_staples')
    
    # Persist the selected low staples
    save_state({'low_staples': low_staples_ids})

    def generate():
        client = MealieClient()
        gemini = GeminiClient()
        generator = PlanGenerator(client, gemini)
        
        q = queue.Queue()
        def callback(msg, progress=None):
            q.put({"status": msg, "progress": progress})

        start_date_str, end_date_str = get_active_week_strings()
        
        thread = threading.Thread(target=generator.generate_weekly_plan, kwargs={
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

@app.route('/sync', methods=['POST'])
def sync():
    """Manual trigger to re-sync the shopping list based on current plans."""
    start_date_str, end_date_str = get_active_week_strings()
    state = load_state()
    low_staples = state.get('low_staples', [])
    
    # If the request comes from the staples modal, update the state
    if request.form.get('staples_submitted'):
        low_staples = request.form.getlist('low_staples')
        save_state({'low_staples': low_staples})

    try:
        sync_shopping_list(start_date_str, end_date_str, low_staples)
        flash("Recalculated active shopping list successfully!", "success")
    except Exception as e:
        flash(f"Error syncing shopping list: {str(e)}", "danger")
        
    return redirect(url_for('index'))

@app.route('/clear', methods=['POST'])
def clear_plan_route():
    try:
        wipe_mealie_data()
        save_state({'low_staples': []})
        flash("Successfully cleared meal plans and reset state!", "success")
    except Exception as e:
        flash(f"Error clearing data: {str(e)}", "danger")
    return redirect(url_for('index'))

@app.route('/add-shopping-item', methods=['POST'])
def add_shopping_item():
    """Add a single manual item to the active shopping list."""
    try:
        data = request.get_json()
        note = sanitize_input(data.get('note', ''))
        if not note:
            return json.dumps({"success": False, "error": "Item name is required"}), 400
            
        client = MealieClient()
        client.add_shopping_list_item(ACTIVE_LIST_ID, note)
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
        
        client = MealieClient()
        items = client.get_shopping_list_items(ACTIVE_LIST_ID)
        target_item = next((item for item in items if item['id'] == item_id), None)
        
        if not target_item:
            return json.dumps({"success": False, "error": "Item not found"}), 404
            
        target_item['checked'] = is_checked
        client.update_shopping_list_item(item_id, target_item)
        
        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}), 500

@app.route('/change-meal', methods=['POST'])
def change_meal():
    try:
        date_str = request.form.get('date')
        recipe_id = request.form.get('recipe_id')
        entry_id = request.form.get('entry_id')
        
        client = MealieClient()
        if entry_id:
            client.delete_meal_plan_entry(entry_id)
            
        if recipe_id != "SKIP":
            client.schedule_meal(date_str, "dinner", recipe_id=recipe_id)
        else:
            client.schedule_meal(date_str, "dinner", title="Eating Out")
            
        flash("Meal changed successfully!", "success")
    except Exception as e:
        flash(f"Error changing meal: {str(e)}", "danger")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9926)
