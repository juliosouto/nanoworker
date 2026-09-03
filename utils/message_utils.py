import requests

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
    Looks for a mention of any worker name at the start of content or transcription.
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

    content_lower = content.lower().strip()
    from database import get_config
    require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"
    
    # 1. Check for text mention at the start (handling both with/without spaces)
    for worker in workers:
        worker_name_clean = worker['worker_name'].strip().lower()
        worker_name_no_spaces = worker_name_clean.replace(" ", "")
        
        if content_lower.startswith(f"@{worker_name_clean}") or content_lower.startswith(f"@{worker_name_no_spaces}"):
            return worker
            
        if not require_at:
            if content_lower.startswith(worker_name_clean) or content_lower.startswith(worker_name_no_spaces):
                return worker

    # 2. Check for audio mention in transcription
    if '\n[Transcription]: ' in content:
        transcription = content.split('\n[Transcription]: ', 1)[1].strip().lower()
        for worker in workers:
            worker_name_clean = worker['worker_name'].strip().lower()
            worker_name_no_spaces = worker_name_clean.replace(" ", "")
            
            if worker_name_clean in transcription[:30] or f"@{worker_name_clean}" in transcription[:30] or \
               worker_name_no_spaces in transcription[:30] or f"@{worker_name_no_spaces}" in transcription[:30]:
                return worker

    return get_default_worker(workers)

def should_process_wa_message(channel_base, sender_id, content="", is_group=False, sender_id_alt=None, return_reason=False):
    """
    Determines if a WhatsApp message should be processed based on config.
    It expects the channel_base and sender_id to accurately determine note-to-self.

    Args:
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
        if content:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT worker_name FROM workers_config')
            worker_names = [row['worker_name'].strip().lower() for row in cursor.fetchall()]
            conn.close()

            content_lower = content.lower().strip()
            require_at = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"
            for name in worker_names:
                name_no_spaces = name.replace(" ", "")
                if not name: continue

                # Check text mention
                if allow_mentions:
                    if content_lower.startswith(f"@{name}") or content_lower.startswith(f"@{name_no_spaces}"):
                        worker_mentioned = True
                        break
                    if not require_at:
                        if content_lower.startswith(name) or content_lower.startswith(name_no_spaces):
                            worker_mentioned = True
                            break

                # Check audio mention
                if allow_audio_mentions and is_audio_transcript:
                    transcription = content.split('\n[Transcription]: ', 1)[1].strip().lower()
                    if name in transcription[:30] or f"@{name}" in transcription[:30] or \
                       name_no_spaces in transcription[:30] or f"@{name_no_spaces}" in transcription[:30]:
                        worker_mentioned = True
                        break

        clean_sender = str(sender_id).split('@')[0] if sender_id else ''
        clean_channel = str(channel_base).split('@')[0] if channel_base else ''

        is_chat_with_oneself = False
        try:
            resp = requests.get('http://127.0.0.1:3000/me', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                own_number = data.get('number')
                lid_number = data.get('lid_number')
                if own_number and clean_channel == str(own_number):
                    is_chat_with_oneself = True
                if lid_number and clean_channel == str(lid_number):
                    is_chat_with_oneself = True
        except Exception:
            pass

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

def clean_mention(content, agent_name=None):
    """
    Remove the @WorkerName mention prefix from the start of the message content.
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
            
        for prefix in prefixes:
            if cleaned_content.lower().startswith(prefix):
                cleaned_content = cleaned_content[len(prefix):].strip()
                break
            
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

def truncate_message(content, max_length=None):
    """
    Truncates a message if it exceeds max_length characters, keeping the last max_length characters.
    Useful for very long messages in WhatsApp groups.
    If max_length is not provided, fetches the token limit from the database and converts it to characters (1 token ≈ 4 chars).
    """
    if max_length is None:
        from database import get_config
        try:
            tokens = int(get_config("MESSAGE_SLICE_SIZE_TOKENS", "2000"))
        except (ValueError, TypeError):
            tokens = 250
        max_length = tokens * 4

    if content and len(content) > max_length:
        return content[-max_length:]
    return content

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
        sender_id_alt=sender_id_alt, return_reason=True
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
