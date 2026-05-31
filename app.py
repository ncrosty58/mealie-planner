import os
import sys
import queue
import threading
import json
from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_from_directory
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from meal_planner import (
    MealieClient,
    generate_weekly_plan,
    sync_shopping_list,
    calculate_nutrition_for_range,
    check_blackstone_compatibility,
    send_email,
    send_daily_reminder_email
)

from mealie_planner.config import ACTIVE_LIST_ID, STAPLES_LIST_ID, RDA, TIMEZONE, APP_URL, FAMILY_RECIPIENT_EMAILS, FAMILY_NAMES

MEALIE_API_URL = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
# Public-facing Mealie URL for UI links
MEALIE_FRONTEND_URL = os.getenv('MEALIE_FRONTEND_URL', 'https://mealie.cosmoslab.dev')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'mealie_companion_secret_9926')

# Helper to calculate the planning week range (starts Saturday, ends next Friday)
def get_planning_dates():
    today = datetime.now(pytz.timezone(TIMEZONE))
    days_to_saturday = (5 - today.weekday() + 7) % 7
    start_date = today + timedelta(days=days_to_saturday)
    end_date = start_date + timedelta(days=6)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")



@app.template_filter('select_day_name')
def select_day_name(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A")
    except Exception as e:
        print(f"Error parsing day name filter: {e}")
        return ""



# Shared variable to hold manually selected low staples IDs for the current week's sync
current_week_low_staples = []

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/')
def index():
    success_msg = request.args.get('success_msg')
    error_msg = request.args.get('error_msg')
    if success_msg:
        flash(success_msg, "success")
    if error_msg:
        flash(error_msg, "danger")
        
    try:
        client = MealieClient()
    except Exception as e:
        return f"<h1>Configuration Error</h1><p>{str(e)}</p>"

    # 1. Determine if a meal plan is already active for the upcoming/current week
    start_date_str, end_date_str = get_planning_dates()
    meal_plans = client.get_meal_plan(start_date_str, end_date_str)
    
    # Check if there are scheduled dinner recipes in the database
    dinners = [p for p in meal_plans if p['entryType'] == 'dinner' and (p.get('recipeId') or p.get('title') == 'Eating Out')]
    
    # 2. Get staples list items for the form (or dashboard)
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
        # PLAN IS ALREADY SUBMITTED & GENERATED FOR THIS WEEK!
        # Render the ACTIVE WEEK DASHBOARD
        daily_nutrition, averages = calculate_nutrition_for_range(start_date_str, end_date_str)
        
        # Enrich meal_plans with Blackstone compatibility
        for p in meal_plans:
            if p['entryType'] == 'dinner' and p.get('recipeId'):
                try:
                    r_details = client.get_recipe_details(p['recipeId'])
                    p['is_blackstone'] = check_blackstone_compatibility(r_details)
                except:
                    p['is_blackstone'] = False
            else:
                p['is_blackstone'] = False

        # Pull shopping list items
        shopping_list = []
        try:
            shopping_list = client.get_shopping_list_items(ACTIVE_LIST_ID)
            shopping_list.sort(key=lambda x: x.get('position', 0))
        except Exception as e:
            print(f"Error reading active shopping list: {e}")

        # Get dates for the 7-day planning week
        start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d")
        planning_dates = [(start_date_obj + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        # Format the active_list_id as a hyphenated UUID for the frontend link
        formatted_list_id = active_list_id
        if len(active_list_id) == 32:
            formatted_list_id = f"{active_list_id[:8]}-{active_list_id[8:12]}-{active_list_id[12:16]}-{active_list_id[16:20]}-{active_list_id[20:]}"

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
        # NO PLAN YET. Render the QUESTIONNAIRE FORM
        # Also format the active_list_id here just in case
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


@app.route('/plan-stream')
def plan_stream():
    exclude_text = request.args.get('exclude_text', '')
    freezer_items = request.args.get('freezer_items', '')
    special_requests = request.args.get('special_requests', '')
    low_staples_ids = request.args.getlist('low_staples')
    
    q = queue.Queue()
    start_date_str, end_date_str = get_planning_dates()
    
    global current_week_low_staples
    current_week_low_staples = low_staples_ids
    
    def worker():
        try:
            def callback(msg, pct):
                q.put({"type": "progress", "message": msg, "progress": pct})
                
            generate_weekly_plan(
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                exclude_text=exclude_text,
                freezer_items=freezer_items,
                special_requests=special_requests,
                low_staples_ids=low_staples_ids,
                progress_callback=callback
            )
            
            q.put({"type": "complete"})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
            
    threading.Thread(target=worker).start()
    
    def generate():
        while True:
            try:
                item = q.get(timeout=180) # 3 mins timeout
                if item["type"] == "complete":
                    yield f"data: {json.dumps({'status': 'complete', 'progress': 100})}\n\n"
                    break
                elif item["type"] == "error":
                    yield f"data: {json.dumps({'status': 'error', 'message': item['message']})}\n\n"
                    break
                elif item["type"] == "progress":
                    yield f"data: {json.dumps({'status': item['message'], 'progress': item['progress']})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Plan generation timed out.'})}\n\n"
                break
                
    return Response(generate(), mimetype='text/event-stream')


@app.route('/plan', methods=['POST'])
def plan():
    exclude_text = request.form.get('exclude_text', '')
    freezer_items = request.form.get('freezer_items', '')
    special_requests = request.form.get('special_requests', '')
    low_staples_ids = request.form.getlist('low_staples')
    
    global current_week_low_staples
    current_week_low_staples = low_staples_ids
    
    start_date_str, end_date_str = get_planning_dates()
    
    try:
        generate_weekly_plan(
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            exclude_text=exclude_text,
            freezer_items=freezer_items,
            special_requests=special_requests,
            low_staples_ids=low_staples_ids
        )
        
        flash("Successfully generated weekly plan and updated active shopping list!", "success")
    except Exception as e:
        flash(f"Error generating plan: {str(e)}", "danger")
        
    return redirect(url_for('index'))


@app.route('/sync', methods=['POST'])
def sync():
    start_date_str, end_date_str = get_planning_dates()
    global current_week_low_staples
    
    # Update low staples from POST form parameter if available
    low_staples_ids = request.form.getlist('low_staples')
    if low_staples_ids or request.form.get('staples_submitted') == '1':
        current_week_low_staples = low_staples_ids
        
    try:
        sync_shopping_list(start_date_str, end_date_str, current_week_low_staples)
        flash("Recalculated active shopping list successfully!", "success")
    except Exception as e:
        flash(f"Error syncing shopping list: {str(e)}", "danger")
        
    return redirect(url_for('index'))


@app.route('/clear', methods=['POST'])
def clear_plan_route():
    try:
        wipe_mealie_data()
        flash("Successfully cleared meal plans and active shopping list from Mealie!", "success")
    except Exception as e:
        flash(f"Error clearing Mealie data: {str(e)}", "danger")
    return redirect(url_for('index'))


@app.route('/change-meal', methods=['POST'])
def change_meal():
    date_str = request.form.get('date')
    recipe_id = request.form.get('recipe_id')
    meal_plan_entry_id = request.form.get('entry_id')
    
    client = MealieClient()
    start_date_str, end_date_str = get_planning_dates()
    global current_week_low_staples
    
    try:
        if meal_plan_entry_id:
            # Delete old entry
            client.delete_meal_plan_entry(meal_plan_entry_id)
            
        if recipe_id == "SKIP":
            # Schedule as 'Eating Out'
            client.schedule_meal(date_str, "dinner", title="Eating Out", recipe_id=None)
            flash("Dinner removed (set to Eating Out). Shopping list recalculated!", "success")
        elif recipe_id:
            # Schedule new recipe
            client.schedule_meal(date_str, "dinner", recipe_id=recipe_id)
            flash("Dinner recipe updated and shopping list recalculated!", "success")
        else:
            # If nothing selected, maybe it was a mistake or reset to 'Eating Out'
            client.schedule_meal(date_str, "dinner", title="Eating Out", recipe_id=None)
            flash("Dinner reset to Eating Out.", "info")
        
        # Trigger shopping list sync immediately
        sync_shopping_list(start_date_str, end_date_str, current_week_low_staples)
    except Exception as e:
        flash(f"Error changing meal: {str(e)}", "danger")
        
    return redirect(url_for('index'))


@app.route('/trigger-qa')
def trigger_qa():
    """Manual trigger endpoint for Saturday Q/A email."""
    if send_saturday_qa_email_job():
        return "Q/A Email sent successfully!"
    return "Failed to send Q/A email.", 500


@app.route('/trigger-daily')
def trigger_daily():
    """Manual trigger endpoint for daily reminder email."""
    if send_daily_reminder_job():
        return "Daily reminder sent successfully!"
    return "Failed to send daily reminder.", 500


# --- Background Job Implementations ---

def send_saturday_qa_email_job():
    """Job to email Saturday Questionnaire link to family."""
    app_url = APP_URL
    
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f7f9fc; padding: 20px; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; padding: 30px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #e1e8ed;">
          <h2 style="color: #E58325; margin-top: 0; text-align: center;">📋 Weekly Meal Planning Questionnaire</h2>
          <p style="font-size: 16px; line-height: 1.6;">Hi {FAMILY_NAMES},</p>
          <p style="font-size: 16px; line-height: 1.6;">It is Saturday, which means it is time to plan meals and shop for the upcoming week!</p>
          <p style="font-size: 16px; line-height: 1.6;">Please click the button below to fill out the questionnaire (choose eating-out days, freezer/pantry/refrigerator items, and check off running-low staples):</p>
          
          <div style="text-align: center; margin: 30px 0;">
            <a href="{app_url}" style="background-color: #E58325; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; display: inline-block;">Fill Out Questionnaire</a>
          </div>
          
          <p style="font-size: 14px; color: #888; text-align: center;">Note: Link redirects to your active dashboard once submitted to prevent double-entries.</p>
        </div>
      </body>
    </html>
    """
    return send_email("📋 Weekly Meal Planning Questionnaire", html)


def send_daily_reminder_job():
    """Job to email daily meal reminders to family at 7:00 AM."""
    return send_daily_reminder_email()



@app.route('/debug-recipes')
def debug_recipes_route():
    recipes = meal_planner.get_recipes_from_db()
    return str(recipes), 200

# --- Scheduler Setup ---

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))
    
    # 1. Daily reminders: Sunday to Friday at 7:00 AM (New York time)
    scheduler.add_job(
        send_daily_reminder_job,
        'cron',
        day_of_week='sun,mon,tue,wed,thu,fri',
        hour=7,
        minute=0,
        id='daily_reminder'
    )
    
    # 2. Saturday Q/A email: Saturdays at 8:00 AM
    scheduler.add_job(
        send_saturday_qa_email_job,
        'cron',
        day_of_week='sat',
        hour=8,
        minute=0,
        id='saturday_qa'
    )
    
    scheduler.start()
    print("Background scheduler started successfully.")


# Start scheduler when Flask context starts
start_scheduler()

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', '9926'))
    app.run(host='0.0.0.0', port=port)
