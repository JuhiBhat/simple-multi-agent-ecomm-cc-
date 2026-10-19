"""In-memory sessions so a follow-up message can complete a case that needed more information.

Example: "my thing came broken" -> NEEDS_INFO -> "it's ORD1001" -> the crew sees both messages.
Idle sessions are reset after 5 minutes.
"""
from datetime import datetime, timedelta

SESSION_TIMEOUT_MINUTES = 5
session_store = {}   # {session_id: {"pending_context": str | None, "last_activity": datetime}}


def get_session(session_id: str) -> dict:
    now = datetime.utcnow()
    session = session_store.setdefault(session_id, {"pending_context": None, "last_activity": now})
    if now - session["last_activity"] > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        session["pending_context"] = None
    session["last_activity"] = now
    return session


def build_customer_message(session: dict, message: str) -> str:
    """Join the earlier unresolved message (if any) with the new one."""
    if session["pending_context"]:
        return f"Earlier message: {session['pending_context']}\nLatest message: {message}"
    return message


def update_after_run(session: dict, combined_message: str, final_status: str) -> None:
    session["pending_context"] = combined_message if final_status == "NEEDS_INFO" else None


def clear_session(session_id: str) -> None:
    session_store.pop(session_id, None)
