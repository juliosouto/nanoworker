"""
Group actions on the current WhatsApp chat: rename the group and delete
specific messages. Both go through the Baileys worker and only act on the
chat the agent is answering right now.
"""

import logging

import requests

logger = logging.getLogger(__name__)

BAILEYS_BASE_URL = "http://127.0.0.1:3000"


def _current_jid():
    """WhatsApp JID of the current chat ('wa_web:' prefix stripped), or None."""
    from tools.chat_history import _current_channel

    channel, _ = _current_channel()
    if not channel:
        return None
    channel = str(channel)
    if channel.lower().startswith("wa_web:"):
        channel = channel[len("wa_web:"):]
    return channel


def _post(path, payload):
    """POST to the Baileys worker; returns (ok, error message)."""
    try:
        response = requests.post(f"{BAILEYS_BASE_URL}{path}", json=payload, timeout=15)
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to WhatsApp service. Make sure the WhatsApp worker is running."
    except requests.exceptions.Timeout:
        return False, "WhatsApp service timed out."
    if response.status_code == 503:
        return False, "WhatsApp client is not connected."
    if response.status_code != 200:
        try:
            details = response.json().get("details") or response.text
        except ValueError:
            details = response.text
        return False, f"HTTP {response.status_code} - {details}"
    return True, ""


def rename_whatsapp_group(new_name: str) -> str:
    """Changes the name (subject) of the current WhatsApp group. Only works in a group chat and when the connected account is a group admin (or the group lets members edit its info).

    Args:
        new_name (str): The new group name (max 100 characters).

    Returns:
        str: A confirmation or an error message.
    """
    new_name = " ".join(str(new_name or "").split())
    if not new_name:
        return "Error: new_name is empty."
    if len(new_name) > 100:
        return "Error: new_name must have at most 100 characters."
    try:
        jid = _current_jid()
    except Exception as e:
        logger.warning(f"Could not resolve the current chat: {e}")
        return f"Error resolving the current chat: {e}"
    if not jid:
        return "Error: no current chat; this tool only works while answering a chat message."
    if not jid.endswith("@g.us"):
        return "Error: the current chat is not a group."

    ok, error = _post("/group_subject", {"jid": jid, "subject": new_name})
    if not ok:
        return f"Error renaming the group: {error}"
    return f"Group renamed to '{new_name}'."


def delete_whatsapp_messages(message_ids: list[int]) -> str:
    """Deletes specific messages of the current WhatsApp chat for everyone. Get the message ids (the #number before each message) from search_chat_history. Your own messages can always be deleted; other people's messages only in a group where the connected account is admin.

    Args:
        message_ids (list[int]): Ids of the messages to delete (max 20), as shown by search_chat_history (e.g. 1234 for '#1234').

    Returns:
        str: One line per message saying whether it was deleted, or an error message.
    """
    if not isinstance(message_ids, (list, tuple)):
        message_ids = [message_ids]
    try:
        ids = [int(str(m).strip().lstrip("#")) for m in message_ids if str(m).strip()]
    except ValueError:
        return "Error: message_ids must be numbers, as shown by search_chat_history (e.g. 1234 for '#1234')."
    if not ids:
        return "Error: message_ids is empty."
    if len(ids) > 20:
        return "Error: at most 20 messages per call."

    try:
        from tools.chat_history import _current_channel
        from database import get_db

        channel, _ = _current_channel()
        if not channel:
            return "Error: no current chat; this tool only works while answering a chat message."
        jid = _current_jid()
        conn = get_db()
        try:
            placeholders = ",".join("?" * len(ids))
            rows = {
                row["id"]: row for row in conn.execute(
                    f"SELECT id, message_id, sender_id, from_me, is_bot FROM message_history "
                    f"WHERE channel_id = ? AND id IN ({placeholders})",
                    [channel] + ids,
                )
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Could not look up the messages to delete: {e}")
        return f"Error looking up the messages: {e}"

    lines = []
    for row_id in ids:
        row = rows.get(row_id)
        if row is None or not row["message_id"]:
            lines.append(f"#{row_id}: not found in this chat.")
            continue
        from_me = bool(row["from_me"] or row["is_bot"])
        payload = {"jid": jid, "message_id": row["message_id"], "from_me": from_me}
        if not from_me and jid.endswith("@g.us") and row["sender_id"]:
            payload["participant"] = row["sender_id"]
        ok, error = _post("/delete", payload)
        lines.append(f"#{row_id}: deleted." if ok else f"#{row_id}: error - {error}")
    return "\n".join(lines)
