import requests

def should_process_wa_message(sender_id, content=""):
    from database import get_db, get_config
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allowed_from, bot_enabled, allow_mentions FROM whatsapp_config WHERE id = 1')
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

    if allow_mentions:
        agent_name = get_config('agent_name', '')
        if agent_name and content and content.lower().startswith(f"@{agent_name.lower()}"):
            return True

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
        mention_prefix = f"@{agent_name.lower()}"
        if cleaned_content.lower().startswith(mention_prefix):
            cleaned_content = cleaned_content[len(mention_prefix):].strip()
            
    return cleaned_content

def truncate_message(content, max_length=1000):
    """
    Truncates a message if it exceeds max_length, keeping the last max_length characters.
    Useful for very long messages in WhatsApp groups.
    """
    if content and len(content) > max_length:
        return content[-max_length:]
    return content
