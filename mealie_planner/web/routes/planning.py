"""Routes for the dashboard/questionnaire, plan generation, and meal swaps."""
import json
import logging
import queue
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for

from mealie_planner.config import (
    FAMILY_NAMES,
    MEALIE_FRONTEND_URL,
    RDA,
    STAPLES_LIST_ID,
    SWAP_RECOMMENDATIONS_PROMPT_TEMPLATE,
    TIMEZONE,
)
from mealie_planner.database import load_state_from_db as load_state
from mealie_planner.database import save_state_to_db as save_state
from mealie_planner.utils import extract_ingredient_texts, resolve_week, sanitize_input
from mealie_planner.web import get_services

logger = logging.getLogger(__name__)

planning_bp = Blueprint('planning', __name__)


@planning_bp.route('/')
def index():
    services = get_services()
    mealie = services.mealie

    success_msg = request.args.get('success_msg')
    error_msg = request.args.get('error_msg')
    if success_msg:
        flash(success_msg, "success")
    if error_msg:
        flash(error_msg, "danger")

    state = load_state()
    week_ctx = resolve_week(request.args.get('week', 'current'), mode='active')
    planning_ctx = resolve_week(week_ctx.week, mode='planning')

    tz = ZoneInfo(TIMEZONE)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    # The four dashboard fetches are independent; run them concurrently.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            'mealie_users': executor.submit(mealie.get_users),
            'meal_plans': executor.submit(mealie.get_meal_plan, week_ctx.start_str, week_ctx.end_str),
            'staples': executor.submit(mealie.get_shopping_list_items_for_list, STAPLES_LIST_ID),
            'all_recipes': executor.submit(mealie.get_all_recipes),
        }
        results = {}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as e:
                logger.error("Error fetching %s: %s", name, e)
                results[name] = []

    mealie_users = results['mealie_users']
    meal_plans = results['meal_plans']
    staples = results['staples']
    all_recipes = results['all_recipes']

    is_submitted = bool(meal_plans)

    formatted_list_id = week_ctx.list_id
    if len(week_ctx.list_id) == 32:
        lid = week_ctx.list_id
        formatted_list_id = f"{lid[:8]}-{lid[8:12]}-{lid[12:16]}-{lid[16:20]}-{lid[20:]}"

    common_context = dict(
        staples=staples,
        low_staples=state.get('low_staples', []),
        today_str=today_str,
        emails_enabled=state.get('emails_enabled', True),
        mealie_users=mealie_users,
        disabled_recipient_emails=state.get('disabled_recipient_emails', []),
        family_names=FAMILY_NAMES,
        week=week_ctx.week,
    )

    if not is_submitted:
        # Questionnaire view: plan the remaining dates
        return render_template(
            'index.html',
            is_submitted=False,
            start_date=planning_ctx.start_str,
            end_date=planning_ctx.end_str,
            **common_context,
        )

    # Dashboard view: displays the FULL active week (preserved past + new)
    daily_nutrition, averages = services.nutrition.calculate_nutrition_for_range(
        week_ctx.start_str, week_ctx.end_str
    )

    _enrich_dinner_entries(services, meal_plans)
    shopping_groups = _load_shopping_groups(mealie, week_ctx.list_id)
    days = _build_week_days(meal_plans, week_ctx.start_str, today_str)

    recipe_map = {'🚫 Eating Out': 'SKIP'}
    for r in all_recipes:
        recipe_map[r['name']] = r['id']

    return render_template(
        'index.html',
        is_submitted=True,
        start_date=week_ctx.start_str,
        end_date=week_ctx.end_str,
        days=days,
        shopping_groups=shopping_groups,
        daily_nutrition=daily_nutrition,
        averages=averages,
        rda=RDA,
        all_recipes=all_recipes,
        recipe_map=recipe_map,
        mealie_url=MEALIE_FRONTEND_URL,
        active_list_id=formatted_list_id,
        **common_context,
    )


def _build_week_days(meal_plans, start_str, today_str):
    """Precompute the per-day view model shared by the menu, print, and prep views."""
    start_obj = datetime.strptime(start_str, "%Y-%m-%d")
    days = []
    for i in range(7):
        date_obj = start_obj + timedelta(days=i)
        d_str = date_obj.strftime("%Y-%m-%d")
        day = {
            "date": d_str,
            "day_name": date_obj.strftime("%A"),
            "is_past": d_str < today_str,
            "breakfast": "Skipped",
            "lunch": "Skipped",
            "dinner": None,
            "dinner_title": "Skipped",
            "prep_notes": [],
        }
        for item in meal_plans:
            if item['date'][:10] != d_str:
                continue
            entry_type = item.get('entryType')
            if entry_type == 'breakfast':
                day['breakfast'] = item.get('title') or 'Staples'
            elif entry_type == 'lunch':
                day['lunch'] = item.get('title') or 'Leftovers'
            elif entry_type == 'dinner':
                recipe = item.get('recipe') or {}
                if item.get('recipeId'):
                    title = recipe.get('name') or 'Recipe Missing'
                elif item.get('title'):
                    title = item['title']
                else:
                    title = 'Skipped'
                day['dinner_title'] = title
                day['dinner'] = {
                    "entry_id": item.get('id', ''),
                    "recipe_id": item.get('recipeId'),
                    "slug": recipe.get('slug'),
                    "is_blackstone": item.get('is_blackstone', False),
                    "nutrition_source": item.get('nutrition_source'),
                }
            if item.get('text'):
                day['prep_notes'].append({
                    "title": item.get('title') or 'Note',
                    "text": item['text'],
                })
        days.append(day)
    return days


def _enrich_dinner_entries(services, meal_plans):
    """Annotate dinner entries with griddle compatibility and nutrition source."""
    dinner_recipe_ids = list({
        p['recipeId'] for p in meal_plans
        if p.get('entryType') == 'dinner' and p.get('recipeId')
    })

    bulk_recipe_details = {}
    if dinner_recipe_ids:
        try:
            bulk_recipe_details = services.mealie.get_recipes_details_bulk(dinner_recipe_ids)
        except Exception as e:
            logger.error("Error fetching bulk recipe details: %s", e)

    for p in meal_plans:
        p['is_blackstone'] = False
        p['nutrition_source'] = None
        if p['entryType'] == 'dinner' and p.get('recipeId'):
            r_details = bulk_recipe_details.get(p['recipeId'])
            if not r_details:
                continue
            try:
                p['is_blackstone'] = services.crawler.check_blackstone_compatibility(r_details)
                extras = r_details.get('extras') or {}
                p['nutrition_source'] = extras.get('nutrition_source')
            except Exception as e:
                logger.warning("Error enriching dinner entry %s: %s", p.get('recipeId'), e)


def _load_shopping_groups(mealie, list_id):
    """Fetch the week's shopping list and return it grouped by category label."""
    try:
        shopping_list = mealie.get_shopping_list_items_for_list(list_id)
    except Exception as e:
        logger.error("Error reading active shopping list: %s", e)
        return []

    # Mealie sometimes returns items with an empty `note` and a null `label`
    # (e.g. items added via the recipe-to-shoppinglist API). Fall back to the
    # computed `display` text and resolve the label via labelId so these items
    # don't render as bare numbers under "General Items".
    try:
        labels_map = {label['id']: label.get('name') for label in mealie.get_labels()}
    except Exception as label_err:
        logger.error("Error reading shopping list labels: %s", label_err)
        labels_map = {}

    for item in shopping_list:
        if not (item.get('note') or '').strip():
            item['note'] = item.get('display') or ''
            item['quantity'] = 0
        if not item.get('label') and item.get('labelId') in labels_map:
            item['label'] = {'name': labels_map[item['labelId']]}

    def get_sort_key(item):
        label = item.get('label')
        name = label.get('name') if isinstance(label, dict) else 'Uncategorized'
        return (name if name != 'Uncategorized' else 'ZZZ', item.get('position', 0), item.get('note', ''))

    shopping_list.sort(key=get_sort_key)

    groups = []
    for item in shopping_list:
        label = item.get('label')
        name = label.get('name') if isinstance(label, dict) and label.get('name') else 'Uncategorized'
        display_name = 'General Items' if name == 'Uncategorized' else name
        if not groups or groups[-1]['name'] != display_name:
            groups.append({"name": display_name, "items": []})
        groups[-1]['items'].append(item)
    return groups


@planning_bp.route('/plan', methods=['POST'])
def plan():
    """Placeholder; actual generation is handled by the /plan-stream SSE endpoint."""
    return redirect(url_for('planning.index'))


@planning_bp.route('/plan-stream')
def plan_stream():
    """SSE endpoint for streaming plan generation progress."""
    services = get_services()
    exclude_text = sanitize_input(request.args.get('exclude_text', ''))
    freezer_items = sanitize_input(request.args.get('freezer_items', ''))
    special_requests = sanitize_input(request.args.get('special_requests', ''))
    week_ctx = resolve_week(request.args.get('week', 'current'))

    save_state({
        "exclude_text": exclude_text,
        "freezer_items": freezer_items,
        "special_requests": special_requests,
    })
    low_staples_ids = load_state().get('low_staples', [])

    def generate():
        lock = services.week_lock(week_ctx.week)
        if not lock.acquire(blocking=False):
            yield "data: " + json.dumps({
                'status': 'complete',
                'warning': '⚠️ A plan generation is already running for this week. Please wait for it to finish.',
            }) + "\n\n"
            return

        q = queue.Queue()

        def callback(msg, progress=None):
            q.put({"status": msg, "progress": progress})

        def run_generation():
            # The worker owns the lock: it is released when generation finishes,
            # even if the SSE client disconnects mid-run.
            try:
                services.plan_generator.generate_weekly_plan(
                    start_date_str=week_ctx.start_str,
                    end_date_str=week_ctx.end_str,
                    exclude_text=exclude_text,
                    freezer_items=freezer_items,
                    special_requests=special_requests,
                    low_staples_ids=low_staples_ids,
                    progress_callback=callback,
                    list_id=week_ctx.list_id,
                )
            finally:
                lock.release()

        thread = threading.Thread(target=run_generation)
        thread.start()

        last_status = None
        while thread.is_alive() or not q.empty():
            try:
                data = q.get(timeout=1)
                last_status = data.get("status")
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                # Keep-alive comment so proxies/tunnels don't time out the
                # connection during long AI calls with no progress updates.
                yield ": heartbeat\n\n"
                continue

        complete_event = {"status": "complete"}
        if last_status and last_status.startswith("⚠️"):
            complete_event["warning"] = last_status
        yield f"data: {json.dumps(complete_event)}\n\n"

    return Response(generate(), mimetype='text/event-stream')


@planning_bp.route('/change-meal', methods=['POST'])
def change_meal():
    services = get_services()
    week = resolve_week(request.form.get('week', 'current')).week
    try:
        date_str = request.form.get('date')
        entry_id = request.form.get('entry_id')
        recipe_id = request.form.get('recipe_id')

        if entry_id:
            services.mealie.delete_meal_plan_entry(entry_id)

        if recipe_id != "SKIP":
            services.mealie.schedule_meal(date_str, "dinner", recipe_id=recipe_id)

        # Auto-sync is intentionally skipped here to keep consecutive swaps fast;
        # the user re-syncs via "Refresh List" when done.
        flash(
            f"Successfully updated meal for {date_str}! "
            "(Remember to click 'Refresh List' in the sidebar to sync your groceries when done.)",
            "success",
        )
    except Exception as e:
        logger.error("Error updating meal: %s", e)
        flash(f"Error updating meal: {e}", "danger")

    return redirect(url_for('planning.index', week=week))


@planning_bp.route('/get-swap-recommendations')
def get_swap_recommendations():
    services = get_services()
    mealie = services.mealie
    date_str = request.args.get('date')
    if not date_str:
        return jsonify([])

    try:
        # 1. Fetch the target week's scheduled meals based on date_str
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_since_saturday = (target_date.weekday() - 5 + 7) % 7
        start_of_week = target_date - timedelta(days=days_since_saturday)
        end_of_week = start_of_week + timedelta(days=6)

        meal_plans = mealie.get_meal_plan(
            start_of_week.strftime("%Y-%m-%d"), end_of_week.strftime("%Y-%m-%d")
        )

        # Extract the other dinners planned this week (excluding the target date)
        other_dinners = []
        target_dinner_name = ""
        for p in meal_plans:
            if p['entryType'] == 'dinner' and p.get('recipe'):
                if p['date'][:10] == date_str:
                    target_dinner_name = p['recipe']['name']
                else:
                    other_dinners.append(p['recipe'])

        all_recipes = mealie.get_all_recipes()

        # Compile other dinner names/ingredients for context
        other_dinner_context = []
        try:
            other_dinner_ids = [r['id'] for r in other_dinners]
            details_map = mealie.get_recipes_details_bulk(other_dinner_ids) if other_dinner_ids else {}
        except Exception as bulk_err:
            logger.error("[Swap Recs] Error bulk loading context details: %s", bulk_err)
            details_map = {}

        for r in other_dinners:
            try:
                det = details_map.get(r['id']) or mealie.get_recipe_details(r['id'])
                other_dinner_context.append({
                    "name": r['name'],
                    "ingredients": extract_ingredient_texts(det),
                })
            except Exception as context_err:
                logger.error("[Swap Recs] Error loading context details for %s: %s", r['name'], context_err)
                other_dinner_context.append({"name": r['name'], "ingredients": []})

        # Candidate recipes, excluding those already planned
        planned_names = {r['name'].lower() for r in other_dinners}
        if target_dinner_name:
            planned_names.add(target_dinner_name.lower())

        candidates = [
            {
                "id": r['id'],
                "name": r['name'],
                "description": (r.get("description") or "")[:120],
                "tags": [t.get('name', t) if isinstance(t, dict) else t for t in r.get('tags', [])],
            }
            for r in all_recipes if r['name'].lower() not in planned_names
        ]

        # Limit to 35 candidates to stay within AI context constraints
        if len(candidates) > 35:
            candidates = random.sample(candidates, 35)

        prompt = SWAP_RECOMMENDATIONS_PROMPT_TEMPLATE.format(
            date_str=date_str,
            target_dinner_name=target_dinner_name or 'None',
            other_dinner_context=json.dumps(other_dinner_context, indent=2),
            candidates=json.dumps(candidates, indent=2),
        )

        raw = services.ai.call(prompt, expect_json=True)
        result = json.loads(raw)
        if not isinstance(result, list):
            raise ValueError("AI response is not a list")

        return jsonify(result[:3])
    except Exception as e:
        logger.error("Error getting swap recommendations: %s", e)
        # Fallback: random 3 recipes from the database
        try:
            all_recipes = mealie.get_all_recipes()
            fallback = [
                {"id": r["id"], "name": r["name"]}
                for r in random.sample(all_recipes, min(3, len(all_recipes)))
            ]
            return jsonify(fallback)
        except Exception as fallback_err:
            logger.error("Fallback recipe selection failed: %s", fallback_err)
            return jsonify([])
