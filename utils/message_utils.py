import requests

def should_process_wa_message(sender_id, content="", is_group=False):
    from database import get_db, get_config
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allowed_from, bot_enabled, allow_mentions, allow_audio_mentions FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    conn.close()
    
    if not config:
        return True
        
    if not config['bot_enabled']:
        return False

    try:
        allow_mentions = bool(config['allow_mentions'])
    except (IndexError, KeyError):
        allow_mentions = True

    try:
        allow_audio_mentions = bool(config['allow_audio_mentions'])
    except (IndexError, KeyError):
        allow_audio_mentions = False

    agent_name = get_config('agent_name', '')
    if agent_name and content:
        # Check text mention
        if allow_mentions and content.lower().startswith(f"@{agent_name.lower()}"):
            return True
        
        # Check audio mention
        if allow_audio_mentions and '\n[Transcription]: ' in content:
            transcription = content.split('\n[Transcription]: ', 1)[1].strip().lower()
            print(f"DEBUG TRANSCRIPTION (bot={agent_name}): '{transcription}'", flush=True)
            
            agent_lower = agent_name.lower()
            if agent_lower in transcription[:30] or f"@{agent_lower}" in transcription[:30]:
                return True

    if is_group:
        # For groups, if it didn't match the mention checks above, we MUST ignore it.
        # Otherwise, the bot would respond to every audio sent by allowed users in the group!
        return False

    clean_sender = str(sender_id).split('@')[0] if sender_id else ''

    try:
        resp = requests.get('http://127.0.0.1:3000/me', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            own_number = data.get('number')
            lid_number = data.get('lid_number')
            if own_number and clean_sender == str(own_number):
                return True
            if lid_number and clean_sender == str(lid_number):
                return True
    except Exception:
        pass
        
    allowed_from = config['allowed_from']
    if not allowed_from or not allowed_from.strip():
        return False
        
    allowed_list = [num.strip() for num in allowed_from.split(',') if num.strip()]
    clean_sender = str(sender_id).split('@')[0] if sender_id else ''
    if clean_sender not in allowed_list:
        return False
            
    return True

def clean_mention(content, agent_name):
    """
    Remove the @AgentName mention prefix from the start of the message content.
    Returns the cleaned string.
    """
    if not content:
        return ""
    
    cleaned_content = content.strip()
    if agent_name:
        agent_name_lower = agent_name.lower()
        mention_prefix = f"@{agent_name_lower}"
        
        if cleaned_content.lower().startswith(mention_prefix):
            cleaned_content = cleaned_content[len(mention_prefix):].strip()
            
        if '\n[Transcription]: ' in cleaned_content:
            parts = cleaned_content.split('\n[Transcription]: ', 1)
            original_text = parts[0]
            transcription = parts[1].strip()
            
            # Remove agent name from transcription start if it's there
            if transcription.lower().startswith(mention_prefix):
                transcription = transcription[len(mention_prefix):].strip()
            elif transcription.lower().startswith(agent_name_lower):
                transcription = transcription[len(agent_name_lower):].strip()
                
            cleaned_content = f"{original_text}\n[Transcription]: {transcription}"
            
    return cleaned_content

def truncate_message(content, max_length=1000):
    """
    Truncates a message if it exceeds max_length, keeping the last max_length characters.
    Useful for very long messages in WhatsApp groups.
    """
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
