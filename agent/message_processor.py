"""
Message processing entry points for WhatsApp/chat and IDE channels.
These are the two main public functions consumed by router.py and sweeper.py.
"""
import logging
import time
import uuid

from google.genai import types

from agent.autonomous_loop import execute_autonomous_loop
from agent.prompt_builder import build_system_prompt, build_config_kwargs
from database import get_config, get_db
from tools import get_permitted_tools
from utils.message_utils import (
    truncate_message,
    process_tools_for_llm,
    resolve_worker_from_content,
    clean_mention,
)
from utils.session import current_session_id

logger = logging.getLogger(__name__)


def _detect_wa_channel_type(channel_id: str):
    """
    Determines if a channel is a WhatsApp group or private chat.

    Returns:
        tuple: (is_wa_group: bool, is_wa_private: bool)
    """
    is_wa_group = False
    is_wa_private = False
    if channel_id and (channel_id.startswith('wa_web:') or channel_id.startswith('whatsapp:')):
        clean_channel = channel_id.replace('wa_web:', '').replace('whatsapp:', '')
        if '-' in clean_channel or clean_channel.startswith('120363'):
            is_wa_group = True
        else:
            is_wa_private = True
    return is_wa_group, is_wa_private


def _build_history_from_db(cursor, session_id: str, exclude_message_id: str, is_wa_group: bool) -> list:
    """
    Fetches and builds the Gemini-format conversation history from the database.
    """
    cursor.execute('''
        SELECT 'user' as role, content, image_base64, file_mime_type, file_name, created_at, gemini_file_uri, sender_id, sender_id_alt, sender_name 
        FROM messages_in 
        WHERE session_id = ? AND id != ?
        
        UNION ALL
        
        SELECT 'model' as role, content, NULL as image_base64, NULL as file_mime_type, NULL as file_name, created_at, NULL as gemini_file_uri, NULL as sender_id, NULL as sender_id_alt, NULL as sender_name 
        FROM messages_out 
        WHERE session_id = ?
        
        ORDER BY created_at ASC
    ''', (session_id, exclude_message_id, session_id))

    rows = cursor.fetchall()
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        if role == 'user':
            if is_wa_group:
                msg_content = truncate_message(msg_content)
            if row['sender_id']:
                sender_label = row['sender_name'] or row['sender_id']
                ids = row['sender_id']
                if row['sender_id_alt']:
                    ids = f"{row['sender_id']} / {row['sender_id_alt']}"
                msg_content = f"[Message from: {sender_label} ({ids})]\n{msg_content}"
        parts = [types.Part.from_text(text=msg_content)]
        if row['image_base64']:
            from utils.image_utils import build_gemini_part
            mime_type = row['file_mime_type'] or "image/jpeg"
            part = build_gemini_part(row['image_base64'], mime_type, row['gemini_file_uri'])
            if part:
                parts.insert(0, part)
                if row['image_base64'].startswith('path:'):
                    parts.insert(1, types.Part.from_text(text=f"[Attached Document File Path: {row['image_base64'][5:]}]"))

        if history and history[-1].role == role:
            history[-1].parts.extend(parts)
        else:
            history.append(
                types.Content(role=role, parts=parts)
            )
    return history


def _check_is_admin(sender_id: str) -> bool:
    """
    Determines if the sender is the bot admin by querying the WhatsApp service.
    """
    if not sender_id:
        return False
    try:
        import requests
        res = requests.get('http://127.0.0.1:3000/me', timeout=2)
        if res.status_code == 200:
            data = res.json()
            bot_number = str(data.get('number', ''))
            lid_number = str(data.get('lid_number', ''))
            clean_sender = str(sender_id).split('@')[0]
            if (bot_number and clean_sender == bot_number) or (lid_number and clean_sender == lid_number):
                return True
    except Exception:
        pass
    return False


def _resolve_models(worker) -> list:
    """
    Determines the ordered list of models to try, based on worker config or global preferences.
    """
    if worker and worker.get('worker_model'):
        return [worker['worker_model']]

    preferences = [get_config(f"LLM_PREF_{i}") for i in range(1, 6)]
    models = [m for m in preferences if m and m.strip()]
    if not models:
        models = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]
    return models


def process_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent, providing it with tools and conversation history.
    Main entry point for WhatsApp and web-chat messages.
    """
    original_content = content

    # Fast-path for /stop command
    if original_content.strip().lower() == '/stop':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        
        stop_response = "🛑 Comando de parada recebido."
        message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
        try:
            cursor = get_db().cursor()
            cursor.execute('INSERT INTO messages_out (id, session_id, in_reply_to, content) VALUES (?, ?, ?, ?)',
                           (message_out_id, session_id, message_in_id, stop_response))
            cursor.connection.commit()
            cursor.connection.close()
        except Exception as e:
            logger.error(f"Failed to save stop response to DB: {e}")

        if on_complete:
            try:
                on_complete(stop_response)
            except Exception as e:
                logger.error(f"on_complete callback failed for stop command: {e}")
                
        return message_out_id, stop_response

    # Wait a bit to debounce multiple rapid messages (like multiple images from WhatsApp)
    time.sleep(2)

    conn = get_db()
    cursor = conn.cursor()

    # Check if a newer message arrived while we slept
    cursor.execute('SELECT id FROM messages_in WHERE session_id = ? AND rowid > (SELECT rowid FROM messages_in WHERE id = ?) LIMIT 1', (session_id, message_in_id))
    newer = cursor.fetchone()
    if newer:
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        return message_in_id, "Skipped to allow newer message to process batch."

    # Mark as processed
    cursor.execute('UPDATE messages_in SET processed = 1 WHERE id = ?', (message_in_id,))
    conn.commit()

    # Set the current session context for tools
    current_session_id.set(session_id)

    # Fetch session's channel_id to determine if it is a WhatsApp group
    cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    channel_id = session_row['channel_id'] if session_row else None
    is_wa_group, is_wa_private = _detect_wa_channel_type(channel_id)

    # Fetch history
    history = _build_history_from_db(cursor, session_id, message_in_id, is_wa_group)

    # Get current message info
    cursor.execute('SELECT image_base64, file_mime_type, file_name, gemini_file_uri, sender_id, sender_id_alt, sender_name FROM messages_in WHERE id = ?', (message_in_id,))
    current_msg = cursor.fetchone()
    current_image_base64 = current_msg['image_base64'] if current_msg else None
    current_gemini_uri = current_msg['gemini_file_uri'] if current_msg else None
    current_sender_id = current_msg['sender_id'] if current_msg else None
    current_sender_id_alt = current_msg['sender_id_alt'] if current_msg else None
    current_sender_name = current_msg['sender_name'] if current_msg else None

    # Ensure client is available for fallback handling
    client = None

    worker = resolve_worker_from_content(original_content)

    # Clean worker mention from content
    content = clean_mention(original_content)

    if is_wa_group:
        content = truncate_message(content)

    if current_sender_id:
        sender_label = current_sender_name or current_sender_id
        ids = current_sender_id
        if current_sender_id_alt:
            ids = f"{current_sender_id} / {current_sender_id_alt}"
        content = f"[Message from: {sender_label} ({ids})]\n{content}"
    send_content = [content]
    if current_image_base64:
        from utils.image_utils import upload_and_build_gemini_part
        mime_type = current_msg['file_mime_type'] or "image/jpeg"
        part, new_uri = upload_and_build_gemini_part(client, current_image_base64, mime_type, current_gemini_uri)
        if part:
            send_content.insert(0, part)
            if current_image_base64.startswith('path:'):
                send_content.insert(1, f"[Attached Document File Path: {current_image_base64[5:]}]")
        if new_uri:
            cursor.execute("UPDATE messages_in SET gemini_file_uri = ? WHERE id = ?", (new_uri, message_in_id))
            conn.commit()

    if history and history[-1].role == 'user':
        last_user = history.pop()
        send_content = last_user.parts + send_content

    models_to_try = _resolve_models(worker)

    try:
        tools_enabled = bool(worker.get('tools_enabled', 1)) if worker else True
        is_admin = _check_is_admin(current_sender_id)
        include_tool_rules = tools_enabled

        # Build system prompt
        worker_name = worker['worker_name'] if worker else None
        system_prompt = build_system_prompt(
            cursor=cursor,
            worker=worker,
            channel_id=channel_id,
            include_tool_rules=include_tool_rules,
            has_image=bool(current_image_base64),
            worker_name=worker_name,
        )

        # Build config kwargs
        tools = get_permitted_tools(is_admin=is_admin, is_group=is_wa_group, is_direct=is_wa_private) if tools_enabled else None
        thinking_enabled = bool(worker.get('thinking_enabled', 0)) if worker else False
        show_tools_results = bool(worker.get('show_tools_results', 1)) if worker else True

        config_kwargs = build_config_kwargs(
            system_prompt=system_prompt,
            tools=tools,
            thinking_enabled=thinking_enabled,
            show_tools_results=show_tools_results,
            temperature=worker.get('temperature') if worker else None,
        )

        mock_response = execute_autonomous_loop(history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=on_complete)

    except Exception as e:
        error_str = str(e)
        if "403" in error_str and "PERMISSION_DENIED" in error_str:
            try:
                cursor.execute('UPDATE messages_in SET gemini_file_uri = NULL WHERE session_id = ?', (session_id,))
                conn.commit()
            except Exception:
                pass
            mock_response = "⚠️ A permission error occurred with old history files (possible API Key change or expired file). The file cache for this session was cleared automatically to resolve the issue. Please resend your message to proceed!"
        else:
            mock_response = f"Error calling LLM API: {error_str}"

    # Write to messages_out safely
    message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    try:
        cursor.execute('''
            INSERT INTO messages_out (id, session_id, in_reply_to, content)
            VALUES (?, ?, ?, ?)
        ''', (message_out_id, session_id, message_in_id, mock_response))

        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save final response to DB: {e}")
    finally:
        try:
            conn.close()
        except:
            pass

    if on_complete:
        try:
            on_complete(mock_response)
        except Exception as e:
            logger.error(f"on_complete callback failed: {e}")

    return message_out_id, mock_response


def process_ide_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent for IDE messages, using ide_messages_in/out tables.
    """
    # Fast-path for /stop command
    if content.strip().lower() == '/stop':
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE ide_messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        
        stop_response = "🛑 Comando de parada recebido via IDE."
        message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
        try:
            cursor = get_db().cursor()
            cursor.execute('INSERT INTO ide_messages_out (id, session_id, in_reply_to, content) VALUES (?, ?, ?, ?)',
                           (message_out_id, session_id, message_in_id, stop_response))
            cursor.connection.commit()
            cursor.connection.close()
        except Exception as e:
            logger.error(f"Failed to save stop response to IDE DB: {e}")

        if on_complete:
            try:
                on_complete(stop_response)
            except Exception as e:
                logger.error(f"on_complete callback failed for stop command: {e}")
                
        return message_out_id, stop_response

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('UPDATE ide_messages_in SET processed = 1 WHERE id = ?', (message_in_id,))
    conn.commit()

    # Set the current session context for tools
    current_session_id.set(session_id)

    cursor.execute('''
        SELECT 'user' as role, content, created_at 
        FROM ide_messages_in 
        WHERE session_id = ? AND id != ?
        
        UNION ALL
        
        SELECT 'model' as role, content, created_at 
        FROM ide_messages_out 
        WHERE session_id = ?
        
        ORDER BY created_at ASC
    ''', (session_id, message_in_id, session_id))

    rows = cursor.fetchall()
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg_content)])
        )

    models_to_try = _resolve_models(worker=None)

    try:
        ide_prompt = get_config("IDE_PROMPT", "")
        thinking_enabled = get_config("THINKING_ENABLED", "false").lower() == "true"

        # Build system prompt
        system_prompt = build_system_prompt(
            cursor=cursor,
            ide_prompt=ide_prompt,
        )

        # Build config kwargs
        config_kwargs = build_config_kwargs(
            system_prompt=system_prompt,
            tools=get_permitted_tools(),
            thinking_enabled=thinking_enabled,
            show_tools_results=True,
        )

        mock_response = execute_autonomous_loop(history, config_kwargs, content, models_to_try, cursor, session_id, message_in_id, is_ide=True)

    except Exception as e:
        mock_response = f"Error calling LLM API: {str(e)}"

    message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    cursor.execute('''
        INSERT INTO ide_messages_out (id, session_id, in_reply_to, content)
        VALUES (?, ?, ?, ?)
    ''', (message_out_id, session_id, message_in_id, mock_response))

    cursor.execute('UPDATE ide_messages_in SET processed = 2 WHERE id = ?', (message_in_id,))

    conn.commit()
    conn.close()

    if on_complete:
        try:
            on_complete(mock_response)
        except Exception as e:
            logger.error(f"on_complete callback failed: {e}")

    return message_out_id, mock_response
