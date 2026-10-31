"""
Reads the last messages of the current chat (group or private) so the agent
can summarize them, list them point by point, find who said what, etc.

Loaded on every OS (root tools/ directory). The source is message_history,
which also records group messages that never mention the worker. Only the
chat the agent is answering right now can be read: a request in one group
never exposes another chat's messages.
"""

import logging

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 50
_MAX_COUNT = 500
_MAX_CHARS_PER_MESSAGE = 1000


def _current_channel():
    """(channel_id, id of the message being answered) for the current session."""
    from utils.session import current_session_id

    session_id = current_session_id.get()
    if not session_id:
        return None, None
    from database import get_db

    conn = get_db()
    try:
        session = conn.execute("SELECT channel_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        last = conn.execute(
            "SELECT client_message_id FROM messages_in WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    channel = session["channel_id"] if session else None
    return channel, (last["client_message_id"] if last else None)


def _sender(row) -> str:
    if row["is_bot"] or row["from_me"]:
        return "Agente" if row["is_bot"] else "Eu"
    return (row["sender_name"] or "").strip() or (row["sender_id"] or "?").split("@")[0]


def _when(row) -> str:
    if row["msg_date"] and row["msg_hour"] is not None:
        return f"{row['msg_date']} {row['msg_hour']:02d}:{row['msg_minute'] or 0:02d}"
    return str(row["created_at"] or "")[:16]


def read_chat_messages(count: int = _DEFAULT_COUNT) -> str:
    """Reads the last messages exchanged in the current WhatsApp chat (group or private), oldest first, so you can summarize them, list them point by point, answer who said what, etc. Includes group messages that did not mention you. Text only (media is not stored).

    Args:
        count (int): How many of the latest messages to read (default 50, max 500). The request being answered now is not included.

    Returns:
        str: One line per message ('[date hh:mm] Sender: text'), or an error message.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return f"Error: count must be a number between 1 and {_MAX_COUNT}."
    if not 1 <= count <= _MAX_COUNT:
        return f"Error: count must be between 1 and {_MAX_COUNT}."

    try:
        channel, current_message = _current_channel()
        if not channel:
            return "Error: no current chat; this tool only works while answering a chat message."
        from database import get_db, get_recent_message_history

        conn = get_db()
        try:
            rows = get_recent_message_history(conn.cursor(), channel, count, exclude_message_id=current_message)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Could not read chat messages: {e}")
        return f"Error reading the chat messages: {e}"

    if not rows:
        return "No messages recorded for this chat yet."
    lines = [f"Last {len(rows)} message(s) of this chat, oldest first:"]
    for row in rows:
        text = " ".join((row["content"] or "").split())
        if len(text) > _MAX_CHARS_PER_MESSAGE:
            text = text[:_MAX_CHARS_PER_MESSAGE] + "…"
        lines.append(f"[{_when(row)}] {_sender(row)}: {text}")
    return "\n".join(lines)
