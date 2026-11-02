"""
Searches the stored messages of the current chat (group or private) so the
agent can find what was said long ago: by subject, by who said it, by date.

Complements read_chat_messages (tools/chat_history.py), which only reads the
latest messages. Only the chat the agent is answering right now is searched:
a request in one group never exposes another chat's messages.
"""

import logging
import re

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50
_MAX_CHARS_PER_MESSAGE = 1000
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _current_message_row_id(current_message):
    """message_history.id of the message being answered (excluded from results)."""
    if not current_message:
        return None
    from database import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM message_history WHERE message_id = ?", (current_message,)
        ).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


def _format(result) -> str:
    payload = result.get("payload") or {}
    when = " ".join(p for p in (payload.get("msg_date"), (payload.get("msg_time") or "")[:5]) if p)
    if payload.get("is_bot"):
        who = "Agente"
    else:
        who = (payload.get("sender_name") or "").strip() or (payload.get("sender_id") or "?").split("@")[0]
    text = " ".join(str(payload.get("content") or "").split())
    if len(text) > _MAX_CHARS_PER_MESSAGE:
        text = text[:_MAX_CHARS_PER_MESSAGE] + "…"
    return f"#{result.get('id')} [{when}] {who}: {text}"


def search_chat_history(query: str = "", sender: str = "", since: str = "", until: str = "",
                        limit: int = _DEFAULT_LIMIT) -> str:
    """Searches all stored messages of the current WhatsApp chat (group or private), not just the latest ones, to find what was said about a subject, by someone, or on given dates. Use it when the answer depends on older messages; for a summary of the recent conversation use read_chat_messages instead. Text only (media is not stored).

    Args:
        query (str): What to look for (subject or words), e.g. "orçamento da viagem". Leave empty to list the newest messages matching the other filters.
        sender (str): Only messages from this person (part of the name or phone number). Optional.
        since (str): Only messages on or after this date, as YYYY-MM-DD. Optional.
        until (str): Only messages on or before this date, as YYYY-MM-DD. Optional.
        limit (int): How many messages to return (default 10, max 50).

    Returns:
        str: One line per message ('#id [date hh:mm] Sender: text'; the #id is what delete_whatsapp_messages takes), best match first (newest first without a query), or an error message.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return f"Error: limit must be a number between 1 and {_MAX_LIMIT}."
    if not 1 <= limit <= _MAX_LIMIT:
        return f"Error: limit must be between 1 and {_MAX_LIMIT}."
    query, sender = (query or "").strip(), (sender or "").strip()
    since, until = (since or "").strip(), (until or "").strip()
    for name, value in (("since", since), ("until", until)):
        if value and not _DATE.match(value):
            return f"Error: {name} must be a date as YYYY-MM-DD."
    if not (query or sender or since or until):
        return "Error: give a query or at least one filter (sender, since, until)."

    try:
        from tools.chat_history import _current_channel

        channel, current_message = _current_channel()
        if not channel:
            return "Error: no current chat; this tool only works while answering a chat message."
        from agent.lc.history_rag import HistoryFilters, search_history

        results = search_history(
            query, channel,
            filters=HistoryFilters(sender=sender or None, since=since or None, until=until or None),
            limit=limit,
            exclude_id=_current_message_row_id(current_message),
        )
    except Exception as e:
        logger.warning(f"Could not search chat messages: {e}")
        return f"Error searching the chat messages: {e}"

    if not results:
        return "No matching messages found in this chat."
    order = "best match first" if query else "newest first"
    lines = [f"{len(results)} message(s) found in this chat, {order}:"]
    lines += [_format(r) for r in results]
    return "\n".join(lines)
