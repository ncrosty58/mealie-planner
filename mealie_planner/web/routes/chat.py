"""Routes for the AI kitchen-assistant chat."""
import logging

from flask import Blueprint, jsonify, request

from mealie_planner.database import (
    clear_chat_history_in_db,
)
from mealie_planner.database import (
    load_chat_history_from_db as load_chat_history,
)
from mealie_planner.database import load_state_from_db as load_state
from mealie_planner.database import (
    save_chat_history_to_db as save_chat_history,
)
from mealie_planner.utils import resolve_week
from mealie_planner.web import get_services

logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/chat-history', methods=['GET'])
def get_chat_history():
    """Fetch the server-side chat history."""
    return jsonify(load_chat_history())


@chat_bp.route('/chat-clear', methods=['POST'])
def clear_chat_history():
    """Clear the server-side chat history."""
    clear_chat_history_in_db()
    return jsonify(success=True)


@chat_bp.route('/chat', methods=['POST'])
def chat():
    services = get_services()
    try:
        data = request.get_json()
        message = data.get('message', '')
        week_ctx = resolve_week(data.get('week', 'current'))

        # Load existing chat history from the server
        chat_data = load_chat_history()
        history = chat_data.get("history", [])
        messages = chat_data.get("messages", [])

        # Append user message immediately and save
        messages.append({"s": "user", "t": message})
        save_chat_history(history, messages)

        # Run chat with persistent history
        from mealie_planner.chat_session import run_chat
        reply, new_history, plan_changed = run_chat(
            history, message,
            week_start_str=week_ctx.start_str, week_end_str=week_ctx.end_str,
        )

        # Append bot reply and save updated history
        messages.append({"s": "bot", "t": reply})
        save_chat_history(new_history, messages)

        if plan_changed:
            try:
                low_staples = load_state().get('low_staples', [])
                services.shopping.sync_shopping_list(
                    week_ctx.start_str, week_ctx.end_str,
                    low_staples_ids=low_staples, list_id=week_ctx.list_id,
                )
            except Exception as sync_err:
                logger.error("[Chat Auto-Sync] Error during auto-sync: %s", sync_err)

        return jsonify(
            success=True,
            reply=reply,
            history=new_history,
            plan_changed=plan_changed,
        )
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        # Save a friendly error message so the UI isn't left inconsistent
        chat_data = load_chat_history()
        history = chat_data.get("history", [])
        messages = chat_data.get("messages", [])
        messages.append({"s": "bot", "t": "Chef is having some technical difficulties. Please try again."})
        save_chat_history(history, messages)
        return jsonify(success=False, error=str(e)), 500
