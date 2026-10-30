"""
Message processing entry points for WhatsApp/chat and IDE channels.
These are the two main public functions consumed by router.py and sweeper.py.
"""
import logging
import re
import time
import uuid

from google.genai import types

from agent.autonomous_loop import execute_autonomous_loop
from agent.openai_tools import _is_provider_balance_error
from agent.prompt_builder import build_system_prompt, build_config_kwargs
from agent.stop_check import StopRequestedError
from database import get_config, get_db
from tools import get_permitted_tools
from utils.message_utils import (
    resolve_worker_from_content,
    clean_mention,
    apply_plan_before_execution,
)
from utils.session import current_session_id

logger = logging.getLogger(__name__)


def _friendly_llm_error(error_str: str) -> str:
    """Returns a short, human-friendly message for LLM API failures caused by
    per-minute rate limits / quota exhaustion (HTTP 429, RESOURCE_EXHAUSTED) or a
    false 402 from an upstream provider, instead of leaking the raw API error
    payload to the user. Any other error keeps the previous generic message
    unchanged."""
    lowered = error_str.lower()

    is_rate_limit = ("429" in error_str or "resource_exhausted" in lowered) and (
        "quota" in lowered
        or "rate limit" in lowered
        or "rate-limit" in lowered
        or "retry in" in lowered
    )
    if is_rate_limit:
        return (
            "⏳ The AI service temporarily exceeded its usage quota (429). "
            "I retried automatically several times but it is still rate-limited. "
            "Please resend your message in a few minutes."
        )

    # A false 402 (Provider returned error / Insufficient balance) from an
    # upstream provider hosting a free OpenRouter model. Retries already ran and
    # the provider is still unavailable; reassure the user instead of leaking the
    # raw metadata (provider_name, user_id, ...).
    proxy_error = _as_exception(error_str)
    if _is_provider_balance_error(proxy_error):
        return (
            "💳 The free model provider is temporarily unavailable (HTTP 402). "
            "I retried automatically several times without success. "
            "Please resend your message in a few minutes."
        )
    if "402" in error_str and "insufficient credits" in lowered:
        return (
            "💳 The AI service account has run out of credits in the gateway "
            "(HTTP 402 - Insufficient credits). Please top up the API balance "
            "and resend your message."
        )

    # An image-only model was called via chat/completions (the provider returns
    # a 404 telling us to use its images endpoint). This means the model was
    # registered without the "Image output" flag, so it took the text path.
    if (
        "is an image generation model" in lowered
        and "chat/completions endpoint" in lowered
    ):
        return (
            "🎨 This model only generates images and can't be used as a chat "
            "model. In the model settings, mark 'Image output' ✓ and leave "
            "'Text output' ✗ so NanoWorker routes it to the image endpoint."
        )

    return f"Error calling LLM API: {error_str}"


class _FakeError(Exception):
    """Adapter so the shared openai_tools detect helpers can inspect a raw string
    as if it were the exception raised by the API client."""

    def __init__(self, text: str, code=None):
        super().__init__(text)
        self.code = code


def _as_exception(text: str) -> _FakeError:
    """Wraps an error string so helper predicates that read ``str(exc)`` / ``exc.code``
    work on it (the string may include the ``Error code: 402`` prefix)."""
    code = None
    m = re.search(r"Error code[: ](\d+)", text)
    if m:
        try:
            code = int(m.group(1))
        except ValueError:
            code = None
    return _FakeError(text, code=code)


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
        # Canonical group JIDs carry the '@g.us' suffix. Keep a legacy best-effort
        # guess for channels stored before JIDs had a suffix (e.g. '120363...' without
        # '@g.us'), but always prefer the exact suffix match.
        if clean_channel.endswith('@g.us') or '-' in clean_channel or clean_channel.startswith('120363'):
            is_wa_group = True
        else:
            is_wa_private = True
    return is_wa_group, is_wa_private


def _build_history_from_db(cursor, session_id: str, exclude_message_id: str) -> list:
    """
    Fetches and builds the Gemini-format conversation history from the database
    (messages_in + messages_out), capped to the last MESSAGE_HISTORY_SIZE
    messages (message count, not tokens) — the history-size limit configured in
    the Agent Behavior settings.
    """
    from database import get_message_history_size
    limit = get_message_history_size()
    cursor.execute(f'''
        SELECT role, content, image_base64, file_mime_type, file_name, created_at, gemini_file_uri, sender_id, sender_id_alt, sender_name FROM (
            SELECT 'user' as role, content, image_base64, file_mime_type, file_name, created_at, gemini_file_uri, sender_id, sender_id_alt, sender_name 
            FROM messages_in 
            WHERE session_id = ? AND id != ?
            
            UNION ALL
            
            SELECT 'model' as role, content, NULL as image_base64, NULL as file_mime_type, NULL as file_name, created_at, NULL as gemini_file_uri, NULL as sender_id, NULL as sender_id_alt, NULL as sender_name 
            FROM messages_out 
            WHERE session_id = ?
        )
        ORDER BY created_at DESC
        LIMIT ?
    ''', (session_id, exclude_message_id, session_id, limit))

    rows = list(cursor.fetchall())
    rows.reverse()  # oldest first
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        if role == 'user' and row['sender_id']:
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


def _build_history_from_message_history(cursor, channel_id: str, exclude_client_message_id=None) -> list:
    """
    Builds the Gemini-format history for WhatsApp channels from the canonical
    message_history timeline: the last PROMPT_HISTORY_SIZE rows of the channel
    (mentioned or not — the continuity window reaches the model), oldest
    first. Rows written by the BOT (is_bot=1) become 'model' turns; everything
    else — including messages typed by the human owner on their own phone
    (from_me=1, is_bot=0) — stays a 'user' turn with the "[Message from: ...]"
    label.
    """
    from database import get_recent_message_history
    rows = get_recent_message_history(
        cursor, channel_id, exclude_message_id=exclude_client_message_id
    )
    history = []
    for row in rows:
        msg_content = row['content'] or ''
        if row['is_bot']:
            role = 'model'
        else:
            role = 'user'
            if row['sender_id']:
                sender_label = row['sender_name'] or row['sender_id']
                ids = row['sender_id']
                if row['sender_id_alt']:
                    ids = f"{row['sender_id']} / {row['sender_id_alt']}"
                msg_content = f"[Message from: {sender_label} ({ids})]\n{msg_content}"
        parts = [types.Part.from_text(text=msg_content)]
        if history and history[-1].role == role:
            history[-1].parts.extend(parts)
        else:
            history.append(types.Content(role=role, parts=parts))
    return history


def _attach_history_rag(cursor, channel_id: str, rag_query: str, content: str,
                        current_client_message_id=None) -> str:
    """
    Retrieves the most relevant vectorized history of the WhatsApp channel and
    appends the context block to ``content`` (the labeled user prompt).

    ``rag_query`` must be the mention-cleaned, label-free text so the query
    embedding matches the vectorized corpus (stored as plain message text).
    Fail-open: any failure returns ``content`` unchanged.
    """
    try:
        from agent.lc.history_rag import (
            CONTEXT_FOOTER,
            CONTEXT_HEADER,
            format_history_context,
            get_settings as history_rag_settings,
            retrieve_relevant_history,
        )
        from database import get_history_window_cutoff

        rag = history_rag_settings()
        if not rag.enabled:
            return content

        current_row_id = None
        if current_client_message_id:
            cursor.execute('SELECT id FROM message_history WHERE message_id = ?', (current_client_message_id,))
            row = cursor.fetchone()
            current_row_id = row['id'] if row else None
        cutoff_ts = get_history_window_cutoff(cursor, channel_id)
        retrieved = retrieve_relevant_history(
            rag_query,
            channel_id,
            exclude_id=current_row_id,
            cutoff_ts=cutoff_ts,
            settings=rag,
        )
        if retrieved:
            logger.info("History RAG: attached %d relevant messages to the prompt", len(retrieved))
            return (
                f"{content}\n\n{CONTEXT_HEADER}\n"
                f"{format_history_context(retrieved)}\n{CONTEXT_FOOTER}"
            )
        return content
    except Exception as exc:
        logger.warning("History RAG retrieval failed (%s); continuing without context", exc)
        return content


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


def _resolve_cron_worker_preferences():
    """
    Resolves the chain of workers and models from CRON_WORKER_PREF_1..5.
    Returns (primary_worker, models_to_try).
    If no preference is configured or matching, returns (None, []).
    """
    pref_names = [get_config(f"CRON_WORKER_PREF_{i}", "") for i in range(1, 6)]
    pref_names = [p.strip() for p in pref_names if p and p.strip()]
    if not pref_names:
        return None, []

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, worker_name, worker_model, worker_instructions, is_default, thinking_enabled, tools_enabled, show_tools_results, temperature FROM workers_config')
    workers = [dict(w) for w in cursor.fetchall()]
    conn.close()

    workers_by_name = { (w['worker_name'] or '').strip().lower(): w for w in workers }

    matched_workers = []
    models_to_try = []
    for name in pref_names:
        w = workers_by_name.get(name.lower())
        if w:
            matched_workers.append(w)
            model = (w.get('worker_model') or '').strip()
            if model and model not in models_to_try:
                models_to_try.append(model)

    primary_worker = matched_workers[0] if matched_workers else None
    return primary_worker, models_to_try


def _resolve_models(worker) -> list:
    """
    Determines the ordered list of models to try, based on worker config or fallback preferences.
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

    # Get current message info
    cursor.execute('SELECT image_base64, file_mime_type, file_name, gemini_file_uri, sender_id, sender_id_alt, sender_name, client_message_id FROM messages_in WHERE id = ?', (message_in_id,))
    current_msg = cursor.fetchone()
    current_image_base64 = current_msg['image_base64'] if current_msg else None
    current_gemini_uri = current_msg['gemini_file_uri'] if current_msg else None
    current_sender_id = current_msg['sender_id'] if current_msg else None
    current_sender_id_alt = current_msg['sender_id_alt'] if current_msg else None
    current_sender_name = current_msg['sender_name'] if current_msg else None
    current_client_message_id = current_msg['client_message_id'] if current_msg else None

    # Ensure client is available for fallback handling
    client = None

    # Fetch history. WhatsApp channels rebuild it from the message_history
    # timeline (last PROMPT_HISTORY_SIZE rows of the channel, including group
    # messages that never mentioned the worker). Other channels keep the
    # messages_in/messages_out rebuild, capped by message count.
    if channel_id and (channel_id.startswith('wa_web:') or channel_id.startswith('whatsapp:')):
        history = _build_history_from_message_history(cursor, channel_id, current_client_message_id)
    else:
        history = _build_history_from_db(cursor, session_id, message_in_id)

    worker = resolve_worker_from_content(original_content)

    # For scheduled jobs without explicit worker mention, honor cron worker preferences chain
    cron_models = []
    if current_sender_id == 'scheduler':
        from utils.message_utils import _find_worker_mention
        from database import get_config
        require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"
        # Check if the content explicitly mentioned a worker
        conn_chk = get_db()
        cur_chk = conn_chk.cursor()
        cur_chk.execute('SELECT worker_name FROM workers_config')
        all_worker_names = [r['worker_name'] for r in cur_chk.fetchall()]
        conn_chk.close()
        
        has_explicit_mention = _find_worker_mention(original_content, all_worker_names, require_at=require_at)
        if not has_explicit_mention:
            cron_worker, pref_models = _resolve_cron_worker_preferences()
            if cron_worker:
                worker = cron_worker
            if pref_models:
                cron_models = pref_models

    # Clean worker mention from content
    content = clean_mention(original_content)

    # History RAG search query: mention-cleaned and WITHOUT the
    # "[Message from: ...]" label, so the query embedding matches the
    # vectorized corpus (stored as plain message text).
    rag_query = content

    if current_sender_id:
        sender_label = current_sender_name or current_sender_id
        ids = current_sender_id
        if current_sender_id_alt:
            ids = f"{current_sender_id} / {current_sender_id_alt}"
        content = f"[Message from: {sender_label} ({ids})]\n{content}"

    # History RAG (WhatsApp channels): retrieve the most relevant vectorized
    # history of this channel and APPEND it to the user's prompt before the
    # LLM call. Parameters come from the Agent Behavior page; any failure is
    # fail-open (the reply is produced without the extra context).
    if channel_id and channel_id.startswith(("wa_web:", "whatsapp:")):
        content = _attach_history_rag(cursor, channel_id, rag_query, content, current_client_message_id)

    content = apply_plan_before_execution(content)

    # The context size is bounded by message count (MESSAGE_HISTORY_SIZE) —
    # token-based slicing was removed. The last N timeline messages are the
    # only history limit.
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

    if cron_models:
        models_to_try = cron_models
    else:
        models_to_try = _resolve_models(worker)

    try:
        tools_enabled = bool(worker.get('tools_enabled', 1)) if worker else True
        is_admin = _check_is_admin(current_sender_id)
        include_tool_rules = tools_enabled

        # Build system prompt
        worker_name = worker['worker_name'] if worker else None
        # Fase 1: decide whether the first model enforces the JSON contract
        # natively (structured output) so the builder can omit the prose block.
        from agent.lc import outputs as lc_outputs
        _provider0 = lc_outputs.resolve_provider_for_model(models_to_try[0]) if models_to_try else None
        native_structured = lc_outputs.structured_output_enabled(
            _provider0, models_to_try[0] if models_to_try else "", has_tools=tools_enabled
        )
        system_prompt = build_system_prompt(
            cursor=cursor,
            worker=worker,
            channel_id=channel_id,
            include_tool_rules=include_tool_rules,
            has_image=bool(current_image_base64),
            worker_name=worker_name,
            native_structured=native_structured,
            models_to_try=models_to_try,
            message_query=content,
        )

        # Build config kwargs
        tools = get_permitted_tools(is_admin=is_admin, is_group=is_wa_group, is_direct=is_wa_private) if tools_enabled else None
        if tools:
            # Opt-in (TOOL_RELEVANCE_FILTER): one lightweight LLM call narrows
            # the tool set to the user's message; fail-open to the full set.
            from agent.lc.tools_lc import filter_tools_by_relevance

            tools = filter_tools_by_relevance(
                tools, content, model_name=(models_to_try[0] if models_to_try else None)
            )
        thinking_enabled = bool(worker.get('thinking_enabled', 0)) if worker else False
        show_tools_results = bool(worker.get('show_tools_results', 1)) if worker else True

        config_kwargs = build_config_kwargs(
            system_prompt=system_prompt,
            tools=tools,
            thinking_enabled=thinking_enabled,
            show_tools_results=show_tools_results,
            temperature=worker.get('temperature') if worker else None,
        )

        mock_response = execute_autonomous_loop(history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=on_complete, show_plan_in_chat=show_tools_results)

    except StopRequestedError:
        mock_response = "🛑 Processamento interrompido pelo usuário (/stop)."
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
            mock_response = _friendly_llm_error(error_str)

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
        WHERE session_id = ? AND in_reply_to != 'summarize-0'
        
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
        # Fase 1: decide native-vs-prompt structured output from the first model.
        from agent.lc import outputs as lc_outputs
        _provider0 = lc_outputs.resolve_provider_for_model(models_to_try[0]) if models_to_try else None
        native_structured = lc_outputs.structured_output_enabled(
            _provider0, models_to_try[0] if models_to_try else "", has_tools=True
        )
        system_prompt = build_system_prompt(
            cursor=cursor,
            ide_prompt=ide_prompt,
            native_structured=native_structured,
            models_to_try=models_to_try,
            message_query=content,
        )

        # Build config kwargs
        ide_tools = get_permitted_tools()
        if ide_tools:
            # Opt-in (TOOL_RELEVANCE_FILTER): one lightweight LLM call narrows
            # the tool set to the user's message; fail-open to the full set.
            from agent.lc.tools_lc import filter_tools_by_relevance

            ide_tools = filter_tools_by_relevance(
                ide_tools, content, model_name=(models_to_try[0] if models_to_try else None)
            )
        config_kwargs = build_config_kwargs(
            system_prompt=system_prompt,
            tools=ide_tools,
            thinking_enabled=thinking_enabled,
            show_tools_results=True,
        )

        mock_response = execute_autonomous_loop(history, config_kwargs, apply_plan_before_execution(content), models_to_try, cursor, session_id, message_in_id, is_ide=True, show_plan_in_chat=True)

    except StopRequestedError:
        mock_response = "🛑 Processamento interrompido pelo usuário (/stop)."
    except Exception as e:
        mock_response = _friendly_llm_error(str(e))

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
