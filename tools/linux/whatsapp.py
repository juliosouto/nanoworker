import logging

import requests

logger = logging.getLogger(__name__)

BAILEYS_URL = "http://127.0.0.1:3000/send"


def _jid_number(phone_number) -> str:
    """Returns only the numeric part of a JID/phone number, stripping suffix and device parts."""
    if not phone_number:
        return ""
    value = str(phone_number).strip()
    # Strip transport prefixes (e.g. 'wa_web:120363...@g.us' -> '120363...@g.us')
    # BEFORE splitting, otherwise the prefix ('wa_web') would be mistaken for the
    # numeric part and the allow-list lookup would never match.
    for prefix in ("wa_web:", "whatsapp:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    return (
        value
        .split("@")[0]
        .split(":")[0]
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )



def _session_jid_for_number(number):
    """Look up the canonical JID stored for a bare number in the most recent
    session ('...@lid', '...@s.whatsapp.net' or group '@g.us'). Preferring the
    session JID avoids guessing '@s.whatsapp.net' for contacts that are only
    addressable via their LID."""
    strip = str(number).replace("+", "").replace(" ", "")
    try:
        from database import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT channel_id FROM sessions
            WHERE channel_id IN (?, ?, ?, ?, ?, ?, ?, ?)
            ORDER BY rowid DESC LIMIT 1
            """,
            (
                f"wa_web:{strip}@lid", f"whatsapp:{strip}@lid",
                f"wa_web:{strip}@s.whatsapp.net", f"whatsapp:{strip}@s.whatsapp.net",
                f"wa_web:{strip}@g.us", f"whatsapp:{strip}@g.us",
                f"wa_web:{strip}", f"whatsapp:{strip}",
            ),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            value = dict(row).get("channel_id")
            if value and ":" in value:
                value = value.split(":", 1)[1]
            return value
    except Exception:
        pass
    return None


def _format_jid(phone_number):
    """
    Converts a phone number / channel id into a full WhatsApp JID.

    Accepts:
      - 'self' or empty -> returns None (Baileys falls back to the own number / note-to-self).
      - a full JID that already contains '@' (e.g. '5511...@lid', '1203...@g.us',
        '5511...@s.whatsapp.net', possibly prefixed with 'wa_web:') -> preserved as-is.
      - a bare number without '@' -> best-effort guess (group -> @g.us, else @s.whatsapp.net).
    """
    if not phone_number:
        return None
    phone_number = str(phone_number).strip()
    if phone_number.lower() == "self":
        return None
    jid = phone_number.replace("wa_web:", "").strip()
    if "@" in jid:
        return jid.replace("+", "").replace(" ", "")
    parts = jid.split("-")
    if jid.startswith("120363") or (len(parts) == 2 and parts[1].isdigit() and len(parts[1]) >= 8):
        return jid.replace("+", "").replace(" ", "") + "@g.us"
    # Prefer the canonical JID stored for this number in an existing session
    # (e.g. '...@lid' for LID-mode private chats) before guessing '@s.whatsapp.net'.
    session_jid = _session_jid_for_number(jid)
    if session_jid:
        return session_jid
    return jid.replace("+", "").replace(" ", "").replace("-", "") + "@s.whatsapp.net"


def _guess_image_mimetype(file_path: str):
    """Infers an image mimetype from the file extension, or None if it's not an image."""
    if not file_path:
        return None
    ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
    mapping = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
        "avif": "image/avif",
    }
    return mapping.get(ext)


def _is_allowed_to(phone_number: str, allow_mentions_override: bool = False) -> bool:
    phone_number = str(phone_number)
    if not phone_number or phone_number.lower() == "self":
        return True

    import requests
    from database import get_db

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM whatsapp_config WHERE id = 1')
        config = cursor.fetchone()

        if not config:
            # Missing whatsapp_config row -> keep the previous permissive behaviour.
            return True

        if allow_mentions_override:
            # Sending a requested file/image is allowed when the user enables either
            # the dedicated "outgoing" flag or the classic "allow mentions" flag.
            # IMPORTANT: both must be accepted because allow_outgoing_mentions is not
            # writable from any UI, so relying on it alone breaks sending when that
            # column defaults to 0. allow_mentions is the legacy (and only writable) gate.
            outgoing_allowed = False
            if 'allow_outgoing_mentions' in config.keys():
                outgoing_allowed = bool(config['allow_outgoing_mentions'])
            mentions_allowed = bool(config['allow_mentions'])
            if outgoing_allowed or mentions_allowed:
                return True

        allowed_to = config['allowed_to']

        clean_target = _jid_number(phone_number)

        # Sending to your own number (note-to-self / direct chat) is always allowed.
        try:
            resp = requests.get('http://127.0.0.1:3000/me', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                own_number = data.get('number')
                lid_number = data.get('lid_number')
                if (own_number and clean_target == str(own_number)) or \
                   (lid_number and clean_target == str(lid_number)):
                    return True
        except Exception:
            pass

        if not allowed_to or not allowed_to.strip():
            return False

        allowed_list = [num.strip() for num in allowed_to.split(',') if num.strip()]
        sanitized_allowed_list = [_jid_number(num) for num in allowed_list]

        if clean_target in sanitized_allowed_list:
            return True

        # Target not listed directly. For group JIDs the value in "Allowed To" is the
        # requesting member, so resolve the sender of the most recent inbound message
        # from this channel (joining through sessions to get the channel) and check
        # THAT member against the allow-list. messages_in has no channel_id column, so
        # we must go through sessions.channel_id.
        try:
            # Sessions are stored with the full JID suffix ('@g.us', '@lid',
            # '@s.whatsapp.net'), plus the legacy suffix-less form for sessions created
            # before JIDs carried a suffix. Match all of them so a bare target still
            # resolves to its canonical chat.
            candidate_channels = [
                f"wa_web:{clean_target}@g.us", f"whatsapp:{clean_target}@g.us",
                f"wa_web:{clean_target}@lid", f"whatsapp:{clean_target}@lid",
                f"wa_web:{clean_target}@s.whatsapp.net", f"whatsapp:{clean_target}@s.whatsapp.net",
                f"wa_web:{clean_target}", f"whatsapp:{clean_target}",
            ]
            placeholders = ",".join("?" for _ in candidate_channels)
            cursor.execute(
                f"""
                SELECT m.sender_id AS sender_id, m.sender_id_alt AS sender_id_alt
                FROM messages_in m
                JOIN sessions s ON s.id = m.session_id
                WHERE s.channel_id IN ({placeholders})
                  AND (m.sender_id IS NOT NULL OR m.sender_id_alt IS NOT NULL)
                ORDER BY m.id DESC
                LIMIT 1
                """,
                candidate_channels,
            )
            row = cursor.fetchone()
            if row:
                row_dict = dict(row)
                # Check both the primary sender and the alt id (LID<->PN mapping), so a
                # member listed by their PN is still recognized when they arrived via LID.
                for candidate in (row_dict.get('sender_id'), row_dict.get('sender_id_alt')):
                    if candidate:
                        candidate_clean = _jid_number(candidate)
                        if candidate_clean in sanitized_allowed_list:
                            return True
        except Exception as e:
            logger.error(f"Error resolving LID to sender_id: {e}")

        return False
    except Exception as e:
        logger.error(f"Error checking allowed_to: {e}")
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass



def send_whatsapp_message(phone_number: str, message: str) -> str:
    """
    Sends a text message to a phone number via WhatsApp.
    DO NOT use this tool to reply to the current active conversation. Your text responses are automatically sent back to the current chat!
    ONLY use this tool if you explicitly need to initiate a new message to a DIFFERENT phone number.

    Args:
        phone_number: The recipient's phone number, JID, or chat address.
                      Use the EXACT phone_number given in your system prompt / channel context —
                      it already contains the correct suffix for the originating chat
                      (e.g. '5511999998888@lid' for a private LID chat, '120363...@g.us' for a group).
                      You may also pass a bare number ('5511999998888'), a group ID
                      ('120363123456789-123@g.us'), or 'self' for the connected account's own number.
        message: The text message to send.

    Returns:
        A confirmation string indicating success or an error message.
    """
    phone_number = str(phone_number)
    from utils.audio_utils import extract_and_generate_audio
    text_to_send, audio_path = extract_and_generate_audio(message)
    
    if not _is_allowed_to(phone_number):
        return (f"Error: Access Denied. Sending messages to {phone_number} is blocked. "
                f"You MUST reply to the user EXACTLY with this English sentence: "
                f"'You must add the number {phone_number} to the Allowed To list in the WhatsApp Settings page before I can send messages to it.'")
    
    try:
        if text_to_send:
            payload = {"text": text_to_send}

            jid = _format_jid(phone_number)
            if jid:
                payload["jid"] = jid
    
            response = requests.post(BAILEYS_URL, json=payload, timeout=15)
    
            if response.status_code == 503:
                return "Error: WhatsApp client is not connected. Please check the connection in Settings."
            elif response.status_code != 200:
                return f"Error sending WhatsApp message: HTTP {response.status_code} - {response.text}"
                
        if audio_path:
            audio_payload = {"file_path": audio_path}
            jid = _format_jid(phone_number)
            if jid:
                audio_payload["jid"] = jid
                
            audio_url = BAILEYS_URL.replace("/send", "/send_audio")
            audio_response = requests.post(audio_url, json=audio_payload, timeout=30)
            
            if audio_response.status_code == 503:
                return "Error: WhatsApp client is not connected."
            elif audio_response.status_code != 200:
                return f"Error sending audio message: HTTP {audio_response.status_code}"
                
        return "Message sent successfully."

    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to WhatsApp service. Make sure the WhatsApp worker is running."
    except requests.exceptions.Timeout:
        return "Error: WhatsApp service timed out. Please try again."
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return f"Error sending WhatsApp message: {str(e)}"

def send_whatsapp_file(phone_number: str, file_path: str, caption: str = "") -> str:
    """
    Sends a local file to a phone number via WhatsApp.
    Use this tool whenever you need to send a requested file or document to someone on WhatsApp.

    Args:
        phone_number: The recipient's phone number, JID, or chat address.
                      Use the EXACT phone_number given in your system prompt / channel context —
                      it already contains the correct suffix for the originating chat
                      (e.g. '5511999998888@lid' for a private LID chat, '120363...@g.us' for a group).
                      If the request came from a group, you MUST send to the group id; if from a
                      private chat, send to that user's number. You may also pass a bare number
                      ('5511999998888') or 'self' for the connected account's own number.
        file_path: The absolute path to the local file to be sent. Use the EXACT path returned
                   by the download/save tool.
        caption: Optional text caption to accompany the file.

    Returns:
        A confirmation string indicating success or an error message.
    """
    phone_number = str(phone_number)
    import os
    import shutil
    import uuid
    import mimetypes

    if not _is_allowed_to(phone_number, allow_mentions_override=True):
        return (f"Error: Access Denied. Sending files to {phone_number} is blocked. "
                f"You MUST reply to the user EXACTLY with this English sentence: "
                f"'You must add the number {phone_number} to the Allowed To list in the WhatsApp Settings page before I can send files to it.'")

    # Allow passing a direct URL: download it first, then send the local copy.
    if str(file_path).lower().lstrip().startswith(("http://", "https://")):
        import importlib
        import platform as _platform
        _folder = "windows" if _platform.system() == "Windows" else ("linux" if _platform.system() == "Linux" else "macos")
        _dl_mod = importlib.import_module(f"tools.{_folder}.download_file_from_url")
        _src_url = str(file_path)
        _name = os.path.basename(_src_url.split("?", 1)[0]) or "download"
        _saved = _dl_mod.download_file_from_url(_src_url, _name, "temp")
        if isinstance(_saved, str) and _saved.lower().startswith(("error", "network error")):
            return _saved
        file_path = _saved

    if not os.path.isfile(file_path):
        return f"Error: File not found at {file_path}"

    from utils.file_utils import create_temp_copy
    
    file_name = os.path.basename(file_path)
    try:
        temp_file_path = create_temp_copy(file_path)
    except Exception as e:
        logger.error(f"Failed to copy file to temp: {e}")
        return f"Error copying file to temporary directory: {str(e)}"

    try:
        mimetype, _ = mimetypes.guess_type(temp_file_path)
        if not mimetype:
            # Fallback: guess an image mimetype from the file extension, otherwise
            # default to a generic document so images are not sent as unknown files.
            mimetype = _guess_image_mimetype(temp_file_path) or "application/octet-stream"
        
        payload = {
            "file_path": temp_file_path,
            "mimetype": mimetype,
            "file_name": file_name,
            "caption": caption
        }

        jid = _format_jid(phone_number)
        if jid:
            payload["jid"] = jid

        # Assuming Baileys is listening on the same host but endpoint is /send_file
        send_file_url = BAILEYS_URL.replace("/send", "/send_file")
        response = requests.post(send_file_url, json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            target = data.get("target", phone_number)
            message_id = data.get("message_id")
            if not message_id:
                # HTTP 200 but no message_id -> Baileys did NOT actually deliver the
                # file. Report a failure instead of a false positive so the agent never
                # claims it sent something that the user did not receive.
                logger.error(f"send_whatsapp_file: HTTP 200 but no message_id for {target} (not delivered)")
                return (f"Error sending WhatsApp file: Baileys returned success but no message_id - "
                        f"the file was NOT delivered to {target}.")
            return f"File '{file_name}' sent successfully to {target}."
        elif response.status_code == 503:
            return "Error: WhatsApp client is not connected. Please check the connection in Settings."
        else:
            return f"Error sending WhatsApp file: HTTP {response.status_code} - {response.text}"

    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to WhatsApp service. Make sure the WhatsApp worker is running."
    except requests.exceptions.Timeout:
        return "Error: WhatsApp service timed out while sending file. Please try again."
    except Exception as e:
        logger.error(f"Failed to send WhatsApp file: {e}")
        return f"Error sending WhatsApp file: {str(e)}"
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.error(f"Failed to delete temp file {temp_file_path}: {e}")
