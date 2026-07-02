"""Routes for admin settings, destructive clears, and PWA assets."""
import logging

from flask import Blueprint, flash, make_response, redirect, request, send_from_directory, url_for

from mealie_planner.database import save_state_to_db as save_state
from mealie_planner.maintenance import wipe_mealie_data
from mealie_planner.utils import resolve_week
from mealie_planner.web import get_services

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/update-admin', methods=['POST'])
def update_admin():
    """Update general administration settings (emails toggle + per-recipient opt-outs)."""
    emails_enabled = request.form.get('emails_enabled') == '1'
    # The form submits enabled addresses as checkboxes, so any known address
    # absent from the form is considered disabled.
    all_known = [u.strip() for u in request.form.get('all_known_emails', '').split(',') if u.strip()]
    enabled_emails = set(request.form.getlist('enabled_recipients'))
    disabled_recipient_emails = [e for e in all_known if e not in enabled_emails]
    save_state({
        'emails_enabled': emails_enabled,
        'disabled_recipient_emails': disabled_recipient_emails,
    })
    flash(f"Admin settings updated! Emails {'enabled' if emails_enabled else 'disabled'}.", "success")
    return redirect(url_for('planning.index'))


@admin_bp.route('/clear', methods=['POST'])
def clear_plan_route():
    services = get_services()
    week = resolve_week(request.form.get('week', 'current')).week
    what = request.form.get('what', 'both')
    try:
        wipe_mealie_data(week=week, what=what, clear_past=True, client=services.mealie)
        if what in ('plan', 'both'):
            save_state({
                'low_staples': [],
                'freezer_items': "",
                'exclude_text': "",
                'special_requests': "",
            })
        if what == 'plan':
            flash(f"Successfully cleared the meal plan for the {week} week!", "success")
        elif what == 'shopping':
            flash(f"Successfully cleared the shopping list for the {week} week!", "success")
        else:
            flash(f"Successfully cleared meal plans for {week} week and reset state!", "success")
    except Exception as e:
        logger.error("Error clearing data: %s", e)
        flash(f"Error clearing data: {str(e)}", "danger")
    return redirect(url_for('planning.index', week=week))


@admin_bp.route('/manifest.json')
def serve_manifest():
    from flask import current_app
    return send_from_directory(current_app.static_folder, 'manifest.json')


@admin_bp.route('/sw.js')
def serve_sw():
    from flask import current_app
    response = make_response(send_from_directory(current_app.static_folder, 'sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response
