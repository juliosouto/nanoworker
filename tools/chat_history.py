"""
Reads the last messages of the current chat (group or private) so the agent
can summarize them, list them point by point, find who said what, etc.

Loaded on every OS (root tools/ directory). The source is message_history,
which also records group messages that never mention the worker. Only the
chat the agent is answering right now can be read: a request in one group
never exposes another chat's messages. The one exception is the voice agent
API (the owner's phone app, /api/voice/agent): there the chat tools work on
the chat picked with select_whatsapp_chat.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 50
_MAX_COUNT = 500
_MAX_CHARS_PER_MESSAGE = 1000

# Voice agent API (/api/voice/agent): the owner talks from the phone app, not
# from a chat, so the chat tools work on a chat picked with
# select_whatsapp_chat (kept per session, in memory, until another pick).
# Same value as agent.message_processor.VOICE_AGENT_CHANNEL_PREFIX.
VOICE_AGENT_CHANNEL_PREFIX = 'voiceagent-'
# Tools offered only on the voice agent channel.
VOICE_AGENT_ONLY_TOOLS = ('list_whatsapp_chats', 'select_whatsapp_chat')
_WA_PREFIXES = ('wa_web:', 'whatsapp:')
_selected_chats = {}
_selected_lock = threading.Lock()


def _session_channel():
    """(session_id, channel_id) of the current session, or (None, None)."""
    from utils.session import current_session_id

    session_id = current_session_id.get()
    if not session_id:
        return None, None
    from database import get_db

    conn = get_db()
    try:
        session = conn.execute("SELECT channel_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return session_id, (session["channel_id"] if session else None)


def _is_voice_agent(channel) -> bool:
    return str(channel or '').startswith(VOICE_AGENT_CHANNEL_PREFIX)


def _current_channel():
    """(channel_id, id of the message being answered) for the current session.

    On the voice agent channel it is the chat picked with select_whatsapp_chat
    (no message is being answered there), or (None, None) before a pick.
    """
    session_id, channel = _session_channel()
    if not session_id:
        return None, None
    if _is_voice_agent(channel):
        with _selected_lock:
            return _selected_chats.get(session_id), None
    from database import get_db

    conn = get_db()
    try:
        last = conn.execute(
            "SELECT client_message_id FROM messages_in WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return channel, (last["client_message_id"] if last else None)


def _group_subjects() -> dict:
    """{group jid: subject} from the WhatsApp worker; {} when unavailable."""
    try:
        import requests

        res = requests.get('http://127.0.0.1:3000/groups', timeout=5)
        if res.status_code == 200:
            return {g.get('jid'): g.get('subject') or '' for g in res.json().get('groups', []) if g.get('jid')}
    except Exception as e:
        logger.warning(f"Could not list WhatsApp groups: {e}")
    return {}


def _jid(channel) -> str:
    for prefix in _WA_PREFIXES:
        if channel.startswith(prefix):
            return channel[len(prefix):]
    return channel


def _known_chats():
    """Every WhatsApp chat with stored messages, newest activity first:
    [{'channel', 'jid', 'is_group', 'name', 'messages', 'last'}]."""
    from database import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT channel_id, MAX(is_group) AS is_group, COUNT(*) AS messages, "
            "MAX(msg_timestamp) AS last_ts, MAX(msg_date) AS last_date, "
            "(SELECT h2.sender_name FROM message_history h2 WHERE h2.channel_id = h.channel_id "
            " AND h2.from_me = 0 AND h2.is_bot = 0 AND COALESCE(h2.sender_name, '') != '' "
            " ORDER BY h2.id DESC LIMIT 1) AS contact "
            "FROM message_history h WHERE channel_id LIKE 'wa_web:%' OR channel_id LIKE 'whatsapp:%' "
            "GROUP BY channel_id ORDER BY last_ts DESC"
        ).fetchall()
    finally:
        conn.close()
    subjects = _group_subjects() if any(r["is_group"] for r in rows) else {}
    chats = []
    for r in rows:
        jid = _jid(r["channel_id"])
        is_group = bool(r["is_group"]) or jid.endswith('@g.us')
        name = subjects.get(jid) if is_group else r["contact"]
        chats.append({
            'channel': r["channel_id"], 'jid': jid, 'is_group': is_group,
            'name': (name or '').strip(), 'messages': r["messages"], 'last': r["last_date"] or '',
        })
    return chats


def _voice_agent_only_error() -> str:
    return "Error: this tool only works on the voice agent channel (/api/voice/agent)."


def list_whatsapp_chats(name: str = "") -> str:
    """Lists the WhatsApp chats (groups and private chats) that have stored messages, so you can pick one with select_whatsapp_chat. Only on the voice agent channel.

    Args:
        name (str): Optional part of the group or contact name to filter by (case-insensitive).

    Returns:
        str: One line per chat ('group|private · name · jid · N messages · last date'), or an error message.
    """
    _, channel = _session_channel()
    if not _is_voice_agent(channel):
        return _voice_agent_only_error()
    try:
        chats = _known_chats()
    except Exception as e:
        logger.warning(f"Could not list chats: {e}")
        return f"Error listing the chats: {e}"
    needle = (name or "").strip().lower()
    if needle:
        chats = [c for c in chats if needle in c['name'].lower() or needle in c['jid'].lower()]
    if not chats:
        return "No WhatsApp chats found" + (f" matching '{name}'." if needle else ".")
    lines = [f"{len(chats)} chat(s), most recent activity first:"]
    for c in chats:
        kind = "group" if c['is_group'] else "private"
        lines.append(f"{kind} · {c['name'] or '(no name)'} · {c['jid']} · {c['messages']} messages · last {c['last']}")
    return "\n".join(lines)


def select_whatsapp_chat(chat: str) -> str:
    """Picks the WhatsApp chat (group or private) that the chat tools (search_chat_history, read_chat_messages, rename_whatsapp_group, delete_whatsapp_messages) work on from now on in this conversation. Call it before those tools on the voice agent channel; call it again to switch chats. Only on the voice agent channel.

    Args:
        chat (str): The group or contact name (or part of it), or the JID/number shown by list_whatsapp_chats.

    Returns:
        str: The selected chat, or an error message (e.g. when the name matches several chats).
    """
    session_id, channel = _session_channel()
    if not _is_voice_agent(channel):
        return _voice_agent_only_error()
    needle = (chat or "").strip().lower()
    if not needle:
        return "Error: chat is empty."
    try:
        chats = _known_chats()
    except Exception as e:
        logger.warning(f"Could not list chats: {e}")
        return f"Error listing the chats: {e}"
    exact = [c for c in chats if needle in (c['jid'].lower(), c['channel'].lower(), c['name'].lower())]
    matches = exact or [c for c in chats if needle in c['name'].lower() or needle in c['jid'].lower()]
    if not matches:
        return f"Error: no chat matches '{chat}'. Use list_whatsapp_chats to see the chats."
    if len(matches) > 1:
        options = "; ".join(f"{c['name'] or '(no name)'} ({c['jid']})" for c in matches[:10])
        return f"Error: '{chat}' matches {len(matches)} chats: {options}. Call again with the JID."
    target = matches[0]
    with _selected_lock:
        _selected_chats[session_id] = target['channel']
    kind = "group" if target['is_group'] else "private chat"
    return f"Selected {kind} '{target['name'] or target['jid']}' ({target['jid']}). The chat tools now work on it."


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
