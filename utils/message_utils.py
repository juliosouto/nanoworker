import re

import requests


def _mention_regex(name, require_at=True):
    """
    Builds a case-insensitive regex that matches a worker mention.

    - With "@": matched ANYWHERE in the text but with a word boundary, so
      "@Mini" matches "Oi @Mini, tudo bem?" but NOT "@Miniflores".
    - Without "@" (require_at=False): anchored at the beginning of the text,
      as before, to avoid matching common words in the middle of a sentence.
    """
    escaped = re.escape(name.strip())
    if not escaped:
        return None
    if require_at:
        return re.compile(rf"(?:^|[^\w@])@{escaped}(?![\w])", re.IGNORECASE | re.UNICODE)
    # The bare form is anchored at the start of the message; leading
    # whitespace is tolerated.
    return re.compile(rf"^\s*{escaped}(?![\w])", re.IGNORECASE | re.UNICODE)


def _find_worker_mention(content, worker_names, require_at=True):
    """
    Returns the name of the first worker mentioned in `content`, or None.

    `worker_names` is a list of worker names (any case). The "@name" form is
    matched anywhere in the text; the bare "name" form only at the beginning.
    """
    if not content or not worker_names:
        return None
    for name in worker_names:
        name_clean = (name or "").strip()
        if not name_clean:
            continue
        name_no_spaces = re.sub(r"\s+", "", name_clean)
        candidates = [name_clean]
        if name_no_spaces and name_no_spaces != name_clean:
            candidates.append(name_no_spaces)
        for candidate in candidates:
            pattern = _mention_regex(candidate, require_at=True)
            if pattern and pattern.search(content):
                return name_clean
        if not require_at:
            for candidate in candidates:
                pattern = _mention_regex(candidate, require_at=False)
                if pattern and pattern.search(content):
                    return name_clean
    return None


def _fetch_own_identity():
    """
    Fetches the identity of our own WhatsApp account from the Baileys worker.

    Returns a dict with the known identifiers (phone number, LID, JIDs) or an
    empty dict when the Baileys worker is unreachable.
    """
    identity = {}
    try:
        resp = requests.get('http://127.0.0.1:3000/me', timeout=2)
        if resp.status_code == 200:
            payload = resp.json()
            for key in ('number', 'lid_number'):
                value = payload.get(key)
                if value:
                    identity[key] = str(value)
            for key in ('jid', 'lid'):
                value = payload.get(key)
                if value:
                    identity[key] = str(value)
    except Exception:
        pass
    return identity


def _own_identity_ids(identity):
    """Normalizes an identity dict into a set of comparable identifiers."""
    ids = set()
    for key in ('number', 'lid_number'):
        value = identity.get(key)
        if value:
            ids.add(str(value))
    for key in ('jid', 'lid'):
        value = identity.get(key)
        if value:
            ids.add(str(value).split(':')[0])
            ids.add(str(value).split('@')[0])
    return ids


def _find_worker_mention_loose(content, worker_names):
    """
    Returns the name of the first worker mentioned in `content`, or None.

    Looser matching used for audio transcriptions: the worker name may appear
    anywhere in the snippet, with or without the "@" prefix.
    """
    if not content or not worker_names:
        return None
    snippet = content.lower()
    for name in worker_names:
        name_clean = (name or "").strip().lower()
        if not name_clean:
            continue
        name_no_spaces = re.sub(r"\s+", "", name_clean)
        for candidate in (name_clean, name_no_spaces):
            if not candidate:
                continue
            if candidate in snippet or f"@{candidate}" in snippet:
                return name_clean
    return None


def _mentions_own_account(data, identity=None):
    """
    True when the message natively mentions our own WhatsApp account.

    When the user picks a contact from the WhatsApp "@" list, the message text
    becomes "@<phone-number>" and the actual target only exists in
    contextInfo.mentionedJid. This is forwarded by the Baileys worker as
    `mentioned_jid` / `native_mention`.
    """
    if not data:
        return False
    if data.get('native_mention'):
        return True
    mentioned = data.get('mentioned_jid')
    if not mentioned:
        return False
    if isinstance(mentioned, str):
        mentioned = [mentioned]

    if identity is None:
        identity = _fetch_own_identity()
    own_ids = _own_identity_ids(identity)
    if not own_ids:
        # Without our own identity we cannot tell whether the mention targets
        # us; the Baileys worker already resolved it via `native_mention`.
        return False

    for jid in mentioned:
        if not isinstance(jid, str):
            continue
        base = jid.split('@')[0].split(':')[0]
        if base in own_ids:
            return True
    return False

def get_default_worker(workers=None):
    from database import get_db
    if workers is None:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, worker_name, worker_model, worker_instructions, is_default, thinking_enabled, tools_enabled, show_tools_results, temperature FROM workers_config')
        workers = [dict(w) for w in cursor.fetchall()]
        conn.close()

    for worker in workers:
        if worker['is_default']:
            return worker
    
    if workers:
        return workers[0]
    return None

def resolve_worker_from_content(content):
    """
    Looks for a mention of any worker name in content or transcription.
    The "@name" form is matched anywhere in the text (with a word boundary),
    so "Oi @Mini, tudo bem?" resolves to Mini. The bare "name" form only
    matches at the beginning of the text.
    Returns the worker dict if matched, otherwise returns the default worker.
    """
    from database import get_db
    if not content:
        return get_default_worker()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, worker_name, worker_model, worker_instructions, is_default, thinking_enabled, tools_enabled, show_tools_results, temperature FROM workers_config')
    workers = [dict(w) for w in cursor.fetchall()]
    conn.close()

    from database import get_config
    require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"

    # If content has a [Quoted message from...] block, strip it for mention inspection
    lookup_content = content
    if lookup_content.lower().lstrip().startswith("[quoted message from:"):
        # The actual message comment starts after the double newline following the quote block
        split_parts = lookup_content.split("\n\n", 1)
        if len(split_parts) > 1:
            lookup_content = split_parts[1].strip()

    worker_names = [w['worker_name'] for w in workers]

    # 1. Check for a text mention (anywhere in the text when prefixed with "@")
    matched_name = _find_worker_mention(lookup_content, worker_names, require_at)
    if matched_name:
        for worker in workers:
            if (worker['worker_name'] or '').strip().lower() == matched_name.strip().lower():
                return worker

    # 2. Check for audio mention in transcription
    if '\n[Transcription]: ' in content:
        transcription = content.split('\n[Transcription]: ', 1)[1].strip()
        matched_name = _find_worker_mention_loose(transcription[:30], worker_names)
        if matched_name:
            for worker in workers:
                if (worker['worker_name'] or '').strip().lower() == matched_name.strip().lower():
                    return worker

    return get_default_worker(workers)

def should_process_wa_message(channel_base, sender_id, content="", is_group=False, sender_id_alt=None, return_reason=False, mention_data=None):
    """
    Determines if a WhatsApp message should be processed based on config.
    It expects the channel_base and sender_id to accurately determine note-to-self.

    Args:
        mention_data (dict|None): Optional webhook payload used to detect a
            NATIVE WhatsApp mention (the "@" picker). When the user picks a
            contact from the list, the text becomes "@<phone-number>" and the
            worker name never appears in the text, so the mention can only be
            detected through contextInfo.mentionedJid.

        return_reason (bool): When True, returns a 2-tuple (allowed: bool, reason: str|None)
            where reason is a specific code for why a message was refused. When False
            (default), returns a plain bool to keep backward compatibility.

    Reason codes:
        "bot_disabled", "audio_mentions_disabled", "no_worker_mentioned",
        "no_worker_mentioned_in_transcription", "sender_not_allowed".
    """
    from database import get_db, get_config
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allowed_from, bot_enabled, allow_mentions, allow_audio_mentions FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    conn.close()

    reason = None

    if not config:
        allowed = True
    elif not config['bot_enabled']:
        allowed = False
        reason = "bot_disabled"
    else:
        try:
            allow_mentions = bool(config['allow_mentions'])
        except (IndexError, KeyError):
            allow_mentions = True

        try:
            allow_audio_mentions = bool(config['allow_audio_mentions'])
        except (IndexError, KeyError):
            allow_audio_mentions = False

        # Check if ANY worker is mentioned in the content
        worker_mentioned = False
        is_audio_transcript = bool(content and '\n[Transcription]: ' in content)
        worker_names = []
        if content:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT worker_name FROM workers_config')
            worker_names = [row['worker_name'].strip() for row in cursor.fetchall()]
            conn.close()

            require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"

            # Check text mention. The "@name" form is matched anywhere in the
            # text (with a word boundary), so "Oi @Mini, ..." is detected.
            if allow_mentions and _find_worker_mention(content, worker_names, require_at):
                worker_mentioned = True

            # Check audio mention
            if not worker_mentioned and allow_audio_mentions and is_audio_transcript:
                transcription = content.split('\n[Transcription]: ', 1)[1].strip()
                if _find_worker_mention_loose(transcription[:30], worker_names):
                    worker_mentioned = True

        # Fetch our own identity once: it is used both to detect a note-to-self
        # chat and to tell whether a native mention targets our account.
        identity = {}
        try:
            identity = _fetch_own_identity()
        except Exception:
            identity = {}

        # A native WhatsApp mention (the "@" picker) does not contain the worker
        # name in the text, so it is detected through contextInfo.mentionedJid.
        native_mention = False
        if mention_data:
            native_mention = _mentions_own_account(mention_data, identity=identity)

        clean_sender = str(sender_id).split('@')[0] if sender_id else ''
        clean_channel = str(channel_base).split('@')[0] if channel_base else ''

        is_chat_with_oneself = False
        own_ids = _own_identity_ids(identity)
        if clean_channel and clean_channel in own_ids:
            is_chat_with_oneself = True

        if native_mention and allow_mentions:
            # The user explicitly picked our account in the "@" list: this is
            # a mention of a worker, regardless of the text content.
            # The "allow_mentions" switch still governs it, so the admin can
            # turn group responses off entirely.
            worker_mentioned = True

        if is_chat_with_oneself:
            allowed = True
        elif not worker_mentioned:
            # As per user explicit requirement: The ONLY exception to process messages without
            # mentions is chat with oneself. Therefore, if we are here and no worker was
            # mentioned, we MUST discard the message.
            allowed = False
            if is_audio_transcript:
                reason = "audio_mentions_disabled" if not allow_audio_mentions \
                    else "no_worker_mentioned_in_transcription"
            else:
                reason = "no_worker_mentioned"
        else:
            # If a worker WAS mentioned, we must check if the sender is allowed to interact with the bot.
            allowed_from = config['allowed_from']
            if not allowed_from or not allowed_from.strip() or allowed_from.strip() == '*':
                allowed = True
            else:
                allowed_list = [num.strip() for num in allowed_from.split(',') if num.strip()]
                sender_ids_to_check = {clean_sender}
                if sender_id_alt:
                    clean_sender_alt = str(sender_id_alt).split('@')[0]
                    sender_ids_to_check.add(clean_sender_alt)
                if not sender_ids_to_check & set(allowed_list):
                    allowed = False
                    reason = "sender_not_allowed"
                else:
                    allowed = True

    if return_reason:
        return allowed, reason
    return allowed

def _strip_mention(text, prefix):
    """
    Removes the first occurrence of `prefix` from `text`, wherever it appears.

    Returns a tuple (cleaned_text, removed) where `removed` tells whether the
    prefix was actually found and removed.
    """
    if not text or not prefix:
        return text, False
    escaped = re.escape(prefix)
    if prefix.startswith('@'):
        # The "@" form is unambiguous: match it anywhere in the text.
        pattern = re.compile(rf"(?:^|[^\w@]){escaped}(?![\w])", re.IGNORECASE | re.UNICODE)
    else:
        # The bare form only matches at the beginning of the text. Leading
        # whitespace is part of the match so the match offsets stay aligned
        # with the original string.
        pattern = re.compile(rf"^\s*{escaped}(?![\w])", re.IGNORECASE | re.UNICODE)
    match = pattern.search(text)
    if not match:
        return text, False
    cleaned = (
        text[:match.start()].rstrip() + " " + text[match.end():].lstrip()
    ).strip()
    return cleaned, True


def clean_mention(content, agent_name=None):
    """
    Remove the @WorkerName mention from the message content.
    The mention is removed whether it is at the start of the message or in the
    middle of a sentence ("Oi @Mini, tudo bem?" -> "Oi tudo bem?").
    Returns the cleaned string.
    """
    if not content:
        return ""
    
    cleaned_content = content.strip()
    
    worker = resolve_worker_from_content(content)
    if worker:
        worker_name_clean = worker['worker_name'].strip().lower()
        worker_name_no_spaces = worker_name_clean.replace(" ", "")
        
        from database import get_config
        require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"
        
        prefixes = [f"@{worker_name_clean}", f"@{worker_name_no_spaces}"]
        if not require_at:
            prefixes.extend([worker_name_clean, worker_name_no_spaces])

        # The mention may live inside a "[Quoted message from: ...]" block, i.e.
        # after the blank line that separates the quote from the actual
        # comment. In that case apply the removal to the comment body only.
        quote_header = None
        body = cleaned_content
        if cleaned_content.lower().startswith('[quoted message from:') and '\n\n' in cleaned_content:
            quote_header, body = cleaned_content.split('\n\n', 1)

        # Remove the mention wherever it appears in the text (the "@" form is
        # unambiguous; the bare form only when it starts the text).
        for prefix in prefixes:
            body, removed = _strip_mention(body, prefix)
            if removed:
                break

        cleaned_content = body if quote_header is None else f"{quote_header}\n\n{body}"

        if '\n[Transcription]: ' in cleaned_content:
            parts = cleaned_content.split('\n[Transcription]: ', 1)
            original_text = parts[0]
            transcription = parts[1].strip()
            
            for prefix in [f"@{worker_name_clean}", f"@{worker_name_no_spaces}", worker_name_clean, worker_name_no_spaces]:
                if transcription.lower().startswith(prefix):
                    transcription = transcription[len(prefix):].strip()
                    break
                
            cleaned_content = f"{original_text}\n[Transcription]: {transcription}"
            
    return cleaned_content

# Placeholder used when a media part (image/file) must not be re-sent to the LLM.
MEDIA_PLACEHOLDER = "[midia/anexo enviado anteriormente - ja visualizado]"


def check_rate_limit(sender_id):
    """
    Checks if the sender has exceeded their rate limit.
    If not, logs the usage.
    Returns True if allowed, False if exceeded.
    """
    from database import get_db
    conn = get_db()
    cursor = conn.cursor()
    
    # Get the limit
    cursor.execute('SELECT rate_limit_per_minute FROM whatsapp_config WHERE id = 1')
    row = cursor.fetchone()
    if not row:
        conn.close()
        return True
    
    try:
        limit = int(row['rate_limit_per_minute'])
    except (TypeError, ValueError, KeyError):
        limit = 0
        
    if limit <= 0:
        conn.close()
        return True
        
    # Check usage
    # Clean up old records
    cursor.execute("DELETE FROM rate_limit_usage WHERE timestamp < datetime('now', '-1 minute')")
    
    # Count requests
    cursor.execute("SELECT COUNT(*) FROM rate_limit_usage WHERE sender_id = ?", (sender_id,))
    count = cursor.fetchone()[0]
    
    if count >= limit:
        conn.commit()
        conn.close()
        return False
        
    # Log usage
    cursor.execute("INSERT INTO rate_limit_usage (sender_id) VALUES (?)", (sender_id,))
    conn.commit()
    conn.close()
    
    return True

def format_dict_to_lines(data, prefix=""):
    """
    Recursively formats a dictionary or list into a list of strings,
    with each key-value pair on a separate line.
    """
    lines = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.extend(format_dict_to_lines(v, prefix + "  "))
            else:
                lines.append(f"{prefix}{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.extend(format_dict_to_lines(item, prefix + "  "))
            else:
                lines.append(f"{prefix}- {item}")
    else:
        lines.append(f"{prefix}{data}")
    return lines

def format_document_search_results(results):
    """
    Formats the search results from search_documents_data_in_database tool.
    Places each detail in extracted_data and metadata on a new line (key: value).
    """
    if not isinstance(results, list):
        return str(results)
    
    formatted_output = []
    for doc in results:
        formatted_output.append(f"Document ID: {doc.get('id', 'N/A')}")
        formatted_output.append(f"File Name: {doc.get('file_name', 'Unknown')}")
        formatted_output.append(f"Category: {doc.get('category', 'Unknown')}")
        
        extracted_data = doc.get("extracted_data", {})
        if extracted_data:
            formatted_output.append("Extracted Data:")
            formatted_output.extend(format_dict_to_lines(extracted_data, prefix="  "))
            
        metadata = doc.get("metadata", {})
        if metadata:
            formatted_output.append("Metadata:")
            formatted_output.extend(format_dict_to_lines(metadata, prefix="  "))
            
        formatted_output.append("-" * 40)
        
    return "\n".join(formatted_output)

def process_tools_for_llm(tools):
    """
    Processes all permitted tools sent to any LLM.
    If the USE_RECIPES_AS_TOOLS database config is true, it wraps each tool
    function preserving its name, docstring, and signature, while delegating 
    calls to the original function. Otherwise, returns the tools unmodified.
    """
    if not tools:
        return tools

    from database import get_config
    use_recipes = get_config("USE_RECIPES_AS_TOOLS", "true").lower() == "true"
    if not use_recipes:
        return tools

    import inspect
    from functools import wraps

    def make_wrapper(f):
        @wraps(f)
        def recipe_wrapper(*args, **kwargs):
            return f(*args, **kwargs)
            
        recipe_wrapper.__name__ = f.__name__
        recipe_wrapper.__doc__ = f.__doc__
        recipe_wrapper.__signature__ = inspect.signature(f)
        return recipe_wrapper

    processed = []
    for func in tools:
        if not callable(func):
            processed.append(func)
            continue
        processed.append(make_wrapper(func))
        
    return processed


# Instruction prefix prepended to the user's prompt when PLAN_BEFORE_EXECUTION is enabled.
PLAN_BEFORE_EXECUTION_PROMPT = """[Plan Before Execution]
Before fulfilling the request below, you MUST first:
1. Review the list of tools available to you in this conversation.
2. Present a concise step-by-step plan describing which tools you will use, in what order, and why each step is necessary to fully deliver the result requested by the user.
3. Put that plan in the "execution_plan" field of your JSON output (it is internal and not shown to the user unless configured).
4. Then execute the plan using the tools, step by step, and put ONLY the final result in the "llm_response" field of your JSON output.

The user's request follows below:"""


def apply_plan_before_execution(content):
    """
    When the PLAN_BEFORE_EXECUTION config is enabled, wraps the user's content
    with instructions asking the LLM to review the available tools and outline
    a step-by-step plan before executing. Otherwise (or for empty content),
    returns the content unmodified.
    """
    if not content:
        return content

    from database import get_config
    enabled = get_config("PLAN_BEFORE_EXECUTION", "false").lower() == "true"
    if not enabled:
        return content

    return f"{PLAN_BEFORE_EXECUTION_PROMPT}\n\n{content}"



def resolve_target_jid(data):
    """
    Extract the target JID for replies from the webhook payload.
    """
    jid = data.get('remote_jid') or data.get('sender_jid')
    if not jid:
        jid = f"{data.get('sender_id')}@s.whatsapp.net"
    return jid


def check_wa_permissions(data, content):
    """
    Validate WhatsApp message permissions and rate limits.

    Returns:
        tuple: (allowed: bool, reason: str | None)
    """
    import logging
    channel_base = data['channel_id'].replace('wa_web:', '')
    is_group = (data.get('remote_jid') or '').endswith('@g.us') or data['channel_id'].endswith('@g.us')
    sender_id = data.get('sender_id')
    sender_id_alt = data.get('sender_id_alt')

    allowed, reason = should_process_wa_message(
        channel_base, sender_id, content, is_group,
        sender_id_alt=sender_id_alt, return_reason=True,
        mention_data=data
    )
    if not allowed:
        logging.info(
            f"Ignored message from {sender_id} (alt: {sender_id_alt}) in channel {channel_base} "
            f"due to WhatsApp config permissions (reason={reason})."
        )
        return False, reason or "permissions_or_disabled"

    if not check_rate_limit(sender_id):
        logging.warning(f"Rate limit exceeded for {sender_id}")
        return False, "rate_limit"

    return True, None
