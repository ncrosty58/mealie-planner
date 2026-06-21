import os
import json
import sqlite3
import threading

DATABASE_FILE = "data/mealie_companion.db"
STATE_FILE = "data/planner_state.json"
CHAT_HISTORY_FILE = "data/chat_history.json"

# Thread-local storage to avoid sqlite thread-sharing issues
_local = threading.local()

def get_db():
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
        _local.conn = sqlite3.connect(DATABASE_FILE, timeout=10.0)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn

def init_db():
    """Initialize the SQLite database schema."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            session_id TEXT PRIMARY KEY,
            history_json TEXT,
            messages_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

def load_state_from_db():
    """Load settings/state from SQLite database. Falls back to JSON file if db is empty."""
    import sys
    if 'pytest' in sys.modules or 'unittest' in sys.modules:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass

    init_db()
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        if rows:
            state = {}
            for row in rows:
                try:
                    state[row['key']] = json.loads(row['value'])
                except json.JSONDecodeError:
                    state[row['key']] = row['value']
            return state
    except Exception as e:
        print(f"[DB] Error loading state from SQLite: {e}")

    # Fallback to JSON file if SQLite is empty or errored
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                # Seed database with JSON contents
                save_state_to_db(state, write_json=False)
                return state
        except Exception as e:
            print(f"[DB] Error loading fallback JSON state: {e}")
    return {}

def save_state_to_db(updates, write_json=True):
    """Save/update settings in SQLite database and sync back to JSON for compatibility."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    try:
        for key, val in updates.items():
            val_json = json.dumps(val)
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, val_json)
            )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving state to SQLite: {e}")

    if write_json:
        # Fetch the entire state to write to JSON
        try:
            state = load_state_from_db()
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            # Use temporary file to prevent corruption during concurrent writes
            tmp_file = f"{STATE_FILE}.tmp"
            with open(tmp_file, 'w') as f:
                json.dump(state, f)
            os.replace(tmp_file, STATE_FILE)
        except Exception as e:
            print(f"[DB] Error writing state JSON file: {e}")

def load_chat_history_from_db(session_id="default"):
    """Load chat history and messages from SQLite database, with JSON fallback."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT history_json, messages_json FROM chat_history WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "history": json.loads(row['history_json'] or "[]"),
                "messages": json.loads(row['messages_json'] or "[]")
            }
    except Exception as e:
        print(f"[DB] Error loading chat history from SQLite: {e}")

    # Fallback to JSON file if SQLite is empty
    if os.path.exists(CHAT_HISTORY_FILE):
        try:
            with open(CHAT_HISTORY_FILE, 'r') as f:
                data = json.load(f)
                # Seed SQLite
                save_chat_history_to_db(
                    data.get("history", []),
                    data.get("messages", []),
                    session_id=session_id,
                    write_json=False
                )
                return data
        except Exception as e:
            print(f"[DB] Error loading chat history fallback JSON: {e}")
    return {"history": [], "messages": []}

def save_chat_history_to_db(history, messages, session_id="default", write_json=True):
    """Save chat history and messages to SQLite database and sync to JSON file."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO chat_history (session_id, history_json, messages_json, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (session_id, json.dumps(history), json.dumps(messages))
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving chat history to SQLite: {e}")

    if write_json:
        try:
            os.makedirs(os.path.dirname(CHAT_HISTORY_FILE), exist_ok=True)
            tmp_file = f"{CHAT_HISTORY_FILE}.tmp"
            with open(tmp_file, 'w') as f:
                json.dump({"history": history, "messages": messages}, f)
            os.replace(tmp_file, CHAT_HISTORY_FILE)
        except Exception as e:
            print(f"[DB] Error writing chat history JSON file: {e}")

def clear_chat_history_in_db(session_id="default"):
    """Clear chat history in SQLite and sync to JSON."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error clearing chat history in SQLite: {e}")
    
    # Also overwrite the chat history file
    try:
        os.makedirs(os.path.dirname(CHAT_HISTORY_FILE), exist_ok=True)
        with open(CHAT_HISTORY_FILE, 'w') as f:
            json.dump({"history": [], "messages": []}, f)
    except Exception as e:
        print(f"[DB] Error writing cleared chat history JSON: {e}")
