"""
Message processing entry points for WhatsApp/chat and IDE channels.
These are the two main public functions consumed by router.py and sweeper.py.
"""
import json
import logging
import re
import time
import uuid

from google.genai import types

from agent.autonomous_loop import execute_autonomous_loop
from agent.openai_tools import _is_provider_balance_error, _is_service_unavailable_error
from agent.prompt_builder import build_system_prompt, build_config_kwargs
from agent.stop_check import StopRequestedError
from database import get_config, get_db
from tools import get_permitted_tools
from utils.message_utils import (
    newer_stop_requested,
    resolve_worker_from_content,
    stop_command_worker,
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
    # 503 "model overloaded": the back-off retries ran out (the fallback chain
    # too, when the worker has other models).
    if _is_service_unavailable_error(proxy_error):
        return (
            "⏳ The AI model is overloaded right now (503, high demand). "
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


# The message the model must answer is delimited explicitly: simpler models
# answered an earlier message of the history (or of the group messages merged
# into the same turn) instead of the latest one.
EARLIER_MESSAGES_HEADER = (
    "[Earlier messages in this chat, for context only: do not answer them "
    "unless the current message asks you to]"
)
CURRENT_MESSAGE_END = "=== END OF CURRENT MESSAGE ==="

# Direct replies (decision model) have no tools. When the request does need
# them the model answers only this marker and the full agent runs instead.
NEEDS_AGENT_MARKER = "[[NEEDS_AGENT]]"
DIRECT_REPLY_RULE = (
    "# No tools in this reply\n"
    "You have no tools right now: you cannot search the internet, check facts, open links, read "
    "files or chats, or take any action. If a correct answer needs any of that (current or "
    "recent information, prices, news, weather, specific facts about people, companies, products, "
    "events, dates or numbers you are not certain of, or an action), do not guess and do not "
    f"answer: reply with exactly {NEEDS_AGENT_MARKER} and nothing else. Otherwise answer normally."
)


def _needs_agent(response) -> bool:
    """True when a direct reply asked to be handed to the full agent."""
    return NEEDS_AGENT_MARKER in str(response or "")


def mark_current_message(content: str, sender_label=None) -> str:
    """Wrap the message being answered between explicit start/end lines."""
    reply_to = f" from {sender_label}: reply to {sender_label}," if sender_label else ":"
    return (
        f"=== CURRENT MESSAGE{reply_to} answer this message only ===\n"
        f"{content}\n{CURRENT_MESSAGE_END}"
    )


def history_in_system_prompt() -> bool:
    """HISTORY_IN_SYSTEM_PROMPT: the user turn carries only the message being
    answered (plus its quoted message and media); the history and the
    retrieved messages go at the end of the system prompt."""
    from database import get_config

    return get_config("HISTORY_IN_SYSTEM_PROMPT", "false").lower() == "true"


def history_transcript(history: list) -> str:
    """The history turns as a plain transcript, oldest first."""
    entries = []
    for turn in history:
        texts = [p.text for p in turn.parts if getattr(p, "text", None)]
        media = sum(1 for p in turn.parts if not getattr(p, "text", None))
        if media:
            texts.append(f"[{media} attachment(s) not shown]")
        text = "\n".join(t.strip() for t in texts if t.strip())
        if not text:
            continue
        if turn.role == "model":
            entries.append(f"[You]\n{text}")
        elif text.startswith("[Message from:"):
            entries.append(text)
        else:
            entries.append(f"[User]\n{text}")
    return "\n\n".join(entries)


def context_for_system_prompt(history: list, rag_block: str = "") -> str:
    """The section appended to the system prompt. It goes last so the fixed
    part before it stays the same between requests (provider prompt cache)."""
    sections = []
    transcript = history_transcript(history)
    if transcript:
        sections.append(
            "# Conversation so far\n"
            "Messages of this chat before the user's current message, oldest first. "
            "They are context only: do not answer them; answer only the user's message. "
            "[You] marks your own earlier replies.\n\n" + transcript
        )
    if rag_block:
        sections.append("# Older messages related to the request\n" + rag_block)
    return "\n\n".join(sections)


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


# A message this short ("sim", "pode mandar") says little about the tool it
# needs; the tool filter also reads the bot's last reply in that case.
_SHORT_TOOL_QUERY_WORDS = 6


def _is_whatsapp_tool(func) -> bool:
    """True for the WhatsApp channel tools (send message/file, poll, ...)."""
    return getattr(func, "__module__", "").endswith(".whatsapp")


def _is_always_kept_tool(func) -> bool:
    """WhatsApp tools plus the scheduling ones: "cron job" or "monitor every 5
    min" rarely embeds close to "schedule a task", and without them the agent
    believes it needs SSH to a server crontab."""
    module = getattr(func, "__module__", "")
    return module.endswith(".whatsapp") or module.endswith(".scheduling")


def _is_chat_tool(func) -> bool:
    """Chat tools (pick, read and search a WhatsApp chat): always kept on the
    voice agent channel, where picking the chat comes before searching it."""
    module = getattr(func, "__module__", "")
    return module.endswith((".chat_history", ".chat_search", ".whatsapp_group"))


def _tool_query(history: list, message: str) -> str:
    """Text the tool relevance filter matches tools against.

    Normally the plain user message. When it is short, the bot's last reply
    is prepended, so a confirmation like "sim" after "Quer que eu envie por
    e-mail?" still selects the e-mail tool.
    """
    if len((message or "").split()) > _SHORT_TOOL_QUERY_WORDS:
        return message
    for turn in reversed(history or []):
        if getattr(turn, "role", None) == "model":
            text = " ".join(p.text for p in turn.parts if getattr(p, "text", None))
            if text.strip():
                return f"{text[-500:]}\n{message}"
            break
    return message


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
            block = f"{CONTEXT_HEADER}\n{format_history_context(retrieved)}\n{CONTEXT_FOOTER}"
            return f"{content}\n\n{block}" if content else block
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
    cursor.execute('SELECT id, worker_name, worker_model, worker_instructions, is_default, thinking_enabled, thinking_level, quantizations, tools_enabled, show_tools_results, temperature FROM workers_config')
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


# Seconds process_message waits before answering, so rapid messages from one
# user (e.g. several images) are answered together by the last one.
_DEBOUNCE_SECONDS = 2

# Channel prefix of the voice API (routes/api_voice.py). Each voice request is
# one synchronous HTTP call waiting for its own answer, so the debounce above
# (made for WhatsApp bursts) does not apply: it only added latency, and a
# newer request must never cancel an older one that is still waiting.
VOICE_CHANNEL_PREFIX = 'voice-'
# Channel prefix of the voice agent API (/api/voice/agent): the worker runs
# with its full pipeline (system prompt, memory, tools, history); only the
# debounce/batching is skipped, as above. Must not start with 'voice-'.
VOICE_AGENT_CHANNEL_PREFIX = 'voiceagent-'


def _deliver_final(on_complete, text):
    """Final reply of process_message. A callback with an ``on_final`` hook
    (the voice agent API) gets the final reply there, apart from the
    intermediate feedback (tool results, plans) sent to the callback itself."""
    on_final = getattr(on_complete, 'on_final', None)
    target = on_final if callable(on_final) else on_complete
    if target:
        try:
            target(text)
        except Exception as e:
            logger.error(f"on_complete callback failed: {e}")


_WEEKDAYS_PT = ('segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
                'sexta-feira', 'sábado', 'domingo')


def _voice_context() -> str:
    """Current date, time and user location for the voice channel prompt
    (the same sources the full prompt uses)."""
    import datetime

    import standard_prompts

    now = datetime.datetime.now()
    try:
        location = standard_prompts._get_user_location()
    except Exception:
        location = "Unknown"
    return (f"Data e hora atuais: {_WEEKDAYS_PT[now.weekday()]}, "
            f"{now.strftime('%Y-%m-%d %H:%M')}. Local do usuário: {location}.")


def _session_channel(session_id) -> str:
    """channel_id of the session ('' when unknown)."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
        row = cursor.fetchone()
    finally:
        conn.close()
    return str(row['channel_id'] or '') if row else ''


def _decide_direct_reply(worker, is_voice, sender_id, message, history, cursor, session_id,
                         message_in_id, is_wa_group, is_wa_private, has_image=False) -> bool:
    """True when the decision model says this message gets a direct reply
    (no tools, no plan, one model call). False when the feature is off, the
    worker has no tools anyway, the message is a voice or scheduled one, or
    anything fails: the full agent runs, as before."""
    try:
        from agent.decision_model import ROUTE_DIRECT, decide_route, decision_settings

        enabled, model = decision_settings()
        if not enabled or not model or is_voice or sender_id == 'scheduler':
            return False
        if worker and not bool(worker.get('tools_enabled', 1)):
            return False  # no tools: the agent already answers directly
        tools = get_permitted_tools(
            is_admin=_check_is_admin(sender_id), is_group=is_wa_group, is_direct=is_wa_private,
        ) or []
        # name -> what it does, so the decision model sees e.g. that a web
        # search tool exists for factual or current questions.
        from agent.lc.tools_lc import first_line_description
        tool_names = {
            t.__name__: first_line_description(t)[:120]
            for t in tools if getattr(t, '__name__', '')
        }
        last_reply = ""
        for turn in reversed(history or []):
            if getattr(turn, "role", None) == "model":
                last_reply = " ".join(p.text for p in turn.parts if getattr(p, "text", None))
                break
        route = decide_route(
            message, cursor, session_id, message_in_id, tool_names=tool_names,
            last_reply=last_reply, images=1 if has_image else 0,
        )
        return route == ROUTE_DIRECT
    except Exception as e:
        # Includes a /stop during the call: the agent loop sees it next.
        logger.warning(f"Decision model skipped for {message_in_id}: {e}")
        return False


def _extra_image_parts(client, cursor, message_in_id, has_main_image) -> list:
    """Parts for the other images sent together with this message (several
    WhatsApp photos under one caption, stored in messages_in.extra_attachments),
    each followed by its file path, plus a note that the caption applies to
    all of them. Fail-open: any problem returns [] and the message is answered
    with its main image only."""
    try:
        cursor.execute('SELECT extra_attachments FROM messages_in WHERE id = ?', (message_in_id,))
        row = cursor.fetchone()
        raw = row['extra_attachments'] if row else None
        if not isinstance(raw, str) or not raw:
            return []
        extras = json.loads(raw)
        if not isinstance(extras, list):
            return []
        from utils.image_utils import upload_and_build_gemini_part
        parts = []
        for item in extras:
            path = item.get('path') if isinstance(item, dict) else None
            if not path:
                continue
            part, _ = upload_and_build_gemini_part(client, path, item.get('mime_type') or 'image/jpeg')
            if not part:
                continue
            parts.append(part)
            if path.startswith('path:'):
                parts.append(f"[Attached Document File Path: {path[5:]}]")
        if not parts:
            return []
        total = sum(1 for p in parts if not isinstance(p, str)) + (1 if has_main_image else 0)
        parts.append(
            f"[{total} images were sent together in this message: its text/caption "
            "applies to all of them, so consider every image when answering]"
        )
        return parts
    except Exception as e:
        logger.error(f"Failed to load the extra images of {message_in_id}: {e}")
        return []


def _superseded_by_newer_message(cursor, session_id, message_in_id, content) -> bool:
    """True when a newer message makes this one redundant.

    Only a newer message from the SAME sender to the SAME worker counts: it
    answers this one too (this message is in its history). In a group the
    session is shared by everyone, so a message from another person, or to
    another worker, must never cancel this one.
    """
    cursor.execute('SELECT sender_id FROM messages_in WHERE id = ?', (message_in_id,))
    row = cursor.fetchone()
    sender_id = row['sender_id'] if row else None
    cursor.execute(
        'SELECT content, sender_id FROM messages_in WHERE session_id = ? '
        'AND rowid > (SELECT rowid FROM messages_in WHERE id = ?)',
        (session_id, message_in_id),
    )
    newer = [r for r in cursor.fetchall() if r['sender_id'] == sender_id]
    if not newer:
        return False
    worker = (resolve_worker_from_content(content) or {}).get('worker_name')
    return any(
        (resolve_worker_from_content(r['content']) or {}).get('worker_name') == worker
        for r in newer
    )


def process_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent, providing it with tools and conversation history.
    Main entry point for WhatsApp and web-chat messages.
    """
    original_content = content

    # Fast-path for /stop and "<worker> /stop": never reaches the LLM.
    stop_target = stop_command_worker(original_content)
    if stop_target is not None:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        
        stop_response = f"🛑 {stop_target} parado." if stop_target else "🛑 Comando de parada recebido."
        message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
        try:
            cursor = get_db().cursor()
            cursor.execute('INSERT INTO messages_out (id, session_id, in_reply_to, content) VALUES (?, ?, ?, ?)',
                           (message_out_id, session_id, message_in_id, stop_response))
            cursor.connection.commit()
            cursor.connection.close()
        except Exception as e:
            logger.error(f"Failed to save stop response to DB: {e}")

        _deliver_final(on_complete, stop_response)
        return message_out_id, stop_response

    # Wait a bit to debounce multiple rapid messages (like multiple images from
    # WhatsApp). The voice API channels skip the wait and the batching.
    session_channel = _session_channel(session_id)
    is_voice = session_channel.startswith(VOICE_CHANNEL_PREFIX)
    is_sync_api = is_voice or session_channel.startswith(VOICE_AGENT_CHANNEL_PREFIX)
    if not is_sync_api:
        time.sleep(_DEBOUNCE_SECONDS)

    conn = get_db()
    cursor = conn.cursor()

    # Check if a newer message of the same batch arrived while we slept
    if not is_sync_api and _superseded_by_newer_message(cursor, session_id, message_in_id, original_content):
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
    # The voice API channel gets no server-side history: the app sends, in the
    # request text, whatever context it wants the model to see.
    if is_voice:
        history = []
    elif channel_id and (channel_id.startswith('wa_web:') or channel_id.startswith('whatsapp:')):
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

    worker_name = worker['worker_name'] if worker else None

    # A stop for this worker that arrived while this message waited: skip it.
    if newer_stop_requested(cursor, 'messages_in', session_id, message_in_id, worker_name):
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        return message_in_id, "Skipped: worker stopped by /stop."

    # Clean worker mention from content
    content = clean_mention(original_content)

    # History RAG search query: mention-cleaned and WITHOUT the
    # "[Message from: ...]" label, so the query embedding matches the
    # vectorized corpus (stored as plain message text).
    rag_query = content

    sender_label = None
    if current_sender_id and not is_voice:
        sender_label = current_sender_name or current_sender_id
        ids = current_sender_id
        if current_sender_id_alt:
            ids = f"{current_sender_id} / {current_sender_id_alt}"
        content = f"[Message from: {sender_label} ({ids})]\n{content}"
    # Voice: the text goes to the model as sent, with no labels or markers.
    separate_context = False if is_voice else history_in_system_prompt()
    if not separate_context and not is_voice:
        content = mark_current_message(content, sender_label)

    # History RAG (WhatsApp channels): retrieve the most relevant vectorized
    # history of this channel and APPEND it to the user's prompt before the
    # LLM call (or to the system prompt with HISTORY_IN_SYSTEM_PROMPT).
    # Parameters come from the Agent Behavior page; any failure is
    # fail-open (the reply is produced without the extra context).
    rag_block = ""
    if channel_id and channel_id.startswith(("wa_web:", "whatsapp:")):
        if separate_context:
            rag_block = _attach_history_rag(cursor, channel_id, rag_query, "", current_client_message_id)
        else:
            content = _attach_history_rag(cursor, channel_id, rag_query, content, current_client_message_id)

    # Decision model (Agent Behavior > Use Decision Model): a quick call decides
    # whether this message needs the full agent or a direct reply without
    # tools, plan or extra rounds. Off, or any failure, keeps the full agent.
    direct_reply = _decide_direct_reply(
        worker, is_voice, current_sender_id, rag_query, history, cursor, session_id,
        message_in_id, is_wa_group, is_wa_private, has_image=bool(current_image_base64),
    )

    if not is_voice and not direct_reply:
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

    # Other images sent together with this one (several WhatsApp photos under
    # one caption): they go right before the text, so the caption covers all.
    extra_parts = _extra_image_parts(client, cursor, message_in_id, bool(current_image_base64))
    if extra_parts:
        send_content[-1:-1] = extra_parts

    if history and history[-1].role == 'user' and not separate_context:
        # Group messages sent since the last reply: they go in the same user
        # turn, labeled as context so the model does not answer them instead.
        last_user = history.pop()
        send_content = [types.Part.from_text(text=EARLIER_MESSAGES_HEADER)] + last_user.parts + send_content

    if cron_models:
        models_to_try = cron_models
    else:
        models_to_try = _resolve_models(worker)

    try:
        # A direct reply (decision model) that turns out to need tools answers
        # NEEDS_AGENT_MARKER; the message then runs again with the full agent.
        for _attempt in range(2):
            attempt_history = list(history)
            tools_enabled = bool(worker.get('tools_enabled', 1)) if worker else True
            if direct_reply:
                tools_enabled = False  # the decision model chose a direct reply
            is_admin = _check_is_admin(current_sender_id)
            include_tool_rules = tools_enabled

            # Build system prompt
            # Fase 1: decide whether the first model enforces the JSON contract
            # natively (structured output) so the builder can omit the prose block.
            from agent.lc import outputs as lc_outputs
            _provider0 = lc_outputs.resolve_provider_for_model(models_to_try[0]) if models_to_try else None
            native_structured = lc_outputs.schema_enforced_by_api(
                _provider0, models_to_try[0] if models_to_try else "", has_tools=tools_enabled
            )
            if is_voice:
                # Voice: current date/time/location plus the worker's own
                # instructions. No standard/channel rules, JSON contract or memory.
                instructions = ((worker or {}).get('worker_instructions') or '').strip()
                system_prompt = _voice_context()
                if instructions:
                    system_prompt = f"{system_prompt}\n\n{instructions}"
            else:
                system_prompt = build_system_prompt(
                    cursor=cursor,
                    worker=worker,
                    channel_id=channel_id,
                    include_tool_rules=include_tool_rules,
                    has_image=bool(current_image_base64 or extra_parts),
                    worker_name=worker_name,
                    native_structured=native_structured,
                    models_to_try=models_to_try,
                )
            if direct_reply:
                # No tools in this reply: hand back to the agent instead of guessing.
                system_prompt = f"{system_prompt}\n\n{DIRECT_REPLY_RULE}"
            if separate_context:
                context = context_for_system_prompt(history, rag_block)
                if context:
                    system_prompt = f"{system_prompt}\n\n{context}"

            # Build config kwargs
            tools = get_permitted_tools(is_admin=is_admin, is_group=is_wa_group, is_direct=is_wa_private) if tools_enabled else None
            if tools and not session_channel.startswith(VOICE_AGENT_CHANNEL_PREFIX):
                # Picking another chat is only for the voice agent channel.
                from tools.chat_history import VOICE_AGENT_ONLY_TOOLS
                tools = [t for t in tools if getattr(t, '__name__', '') not in VOICE_AGENT_ONLY_TOOLS]
            if tools:
                # TOOL_RELEVANCE_FILTER: keep the tools most similar to the plain
                # user message (local embeddings); fail-open to the full set.
                from agent.lc.tools_lc import filter_tools_by_relevance

                tools = filter_tools_by_relevance(
                    tools, _tool_query(history, rag_query),
                    always_keep=(
                        _is_always_kept_tool if (is_wa_group or is_wa_private)
                        else _is_chat_tool if session_channel.startswith(VOICE_AGENT_CHANNEL_PREFIX)
                        else None
                    ),
                )
            thinking_enabled = bool(worker.get('thinking_enabled', 0)) if worker else False
            show_tools_results = bool(worker.get('show_tools_results', 1)) if worker else True

            config_kwargs = build_config_kwargs(
                system_prompt=system_prompt,
                tools=tools,
                thinking_enabled=thinking_enabled,
                show_tools_results=show_tools_results,
                temperature=worker.get('temperature') if worker else None,
                thinking_level=worker.get('thinking_level') if worker else None,
                quantizations=worker.get('quantizations') if worker else None,
            )
            if is_voice:
                config_kwargs["plain_text_reply"] = True

            # Live status (one reply edited at each step) when the channel supports it.
            from agent import status as agent_status
            status_reporter = getattr(on_complete, "report_status", None)
            status_token = agent_status.set_status_reporter(status_reporter) if status_reporter else None
            try:
                agent_status.report_status(agent_status.THINKING)
                if separate_context:
                    attempt_history = []  # already in the system prompt
                from agent.llm_usage import usage_worker

                with usage_worker(worker_name):
                    mock_response = execute_autonomous_loop(attempt_history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=on_complete, show_plan_in_chat=show_tools_results, worker_name=worker_name, direct=direct_reply)
            finally:
                if status_token is not None:
                    agent_status.reset_status_reporter(status_token)
            if direct_reply and _needs_agent(mock_response):
                logger.info(f"Direct reply for {message_in_id} needs tools; running the full agent")
                direct_reply = False
                continue
            break

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

    _deliver_final(on_complete, mock_response)

    return message_out_id, mock_response


def process_ide_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent for IDE messages, using ide_messages_in/out tables.
    """
    # Fast-path for /stop command
    if stop_command_worker(content) is not None:
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
        native_structured = lc_outputs.schema_enforced_by_api(
            _provider0, models_to_try[0] if models_to_try else "", has_tools=True
        )
        system_prompt = build_system_prompt(
            cursor=cursor,
            ide_prompt=ide_prompt,
            native_structured=native_structured,
            models_to_try=models_to_try,
        )

        # Build config kwargs
        ide_tools = get_permitted_tools()
        if ide_tools:
            # TOOL_RELEVANCE_FILTER: keep the tools most similar to the user
            # message (local embeddings); fail-open to the full set.
            from agent.lc.tools_lc import filter_tools_by_relevance

            ide_tools = filter_tools_by_relevance(ide_tools, content)
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
