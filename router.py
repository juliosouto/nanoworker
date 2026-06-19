import logging
import threading
import uuid

from agent_runner import process_ide_message, process_message
from database import get_config, get_db
from utils.message_utils import clean_mention

logger = logging.getLogger(__name__)

def route_inbound_message(channel_id, content, sender_id=None, sender_id_alt=None, sender_name=None, image_base64=None, file_mime_type=None, file_name=None, on_complete=None, client_message_id=None):
    """
    Finds/creates a session, writes to messages_in, and dispatches
    processing in a background thread. Returns immediately.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Deduplicate based on client_message_id
    if client_message_id:
        cursor.execute('SELECT id, session_id FROM messages_in WHERE client_message_id = ? LIMIT 1', (client_message_id,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            logger.info(f"Duplicate message ignored: client_message_id={client_message_id}")
            return existing['id'], existing['session_id'], False

    # 1. Resolve agent for this channel (for MVP, just pick agent-1)
    agent_id = 'agent-1'
    
    # 2. Find or create session
    cursor.execute('SELECT id FROM sessions WHERE agent_id = ? AND channel_id = ?', (agent_id, channel_id))
    session = cursor.fetchone()
    
    if session:
        session_id = session['id']
    else:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        cursor.execute('INSERT INTO sessions (id, agent_id, channel_id) VALUES (?, ?, ?)', 
                       (session_id, agent_id, channel_id))
        conn.commit()

    # 3. Write to messages_in
    message_id = f"msg-in-{uuid.uuid4().hex[:8]}"
    cursor.execute('''
        INSERT INTO messages_in (id, session_id, content, sender_id, sender_id_alt, sender_name, image_base64, file_mime_type, file_name, client_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (message_id, session_id, content, sender_id, sender_id_alt, sender_name, image_base64, file_mime_type, file_name, client_message_id))
    conn.commit()
    
    from utils.message_utils import get_default_worker
    default_worker = get_default_worker()
    agent_name = default_worker['worker_name'] if default_worker else ''
    cleaned_content = clean_mention(content, agent_name)

    if cleaned_content == "/new":
        cursor.execute('DELETE FROM messages_in WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM messages_out WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()
        
        if on_complete:
            try:
                on_complete("History cleared! Starting a new conversation.")
            except Exception as e:
                logger.error(f"on_complete callback failed: {e}")
                
        return message_id, session_id, True  # is_sync=True (immediate response)

    if cleaned_content == "/list":
        from database import get_all_workers_with_capabilities
        workers = get_all_workers_with_capabilities()
        
        response_lines = ["📋 *Available Workers & Capabilities:*"]
        if not workers:
            response_lines.append("\nNenhum worker encontrado.")
        else:
            for w in workers:
                name = w.get('worker_name', 'Unknown')
                model = w.get('worker_model', 'Unknown')
                
                inputs = []
                if w.get('text_input'): inputs.append("Text")
                if w.get('image_input'): inputs.append("Image")
                if w.get('audio_input'): inputs.append("Audio")
                if w.get('video_input'): inputs.append("Video")
                if w.get('document_input'): inputs.append("Document")
                
                outputs = []
                if w.get('text_output'): outputs.append("Text")
                if w.get('image_output'): outputs.append("Image")
                if w.get('audio_output'): outputs.append("Audio")
                if w.get('video_output'): outputs.append("Video")
                if w.get('document_output'): outputs.append("Document")
                
                in_str = ", ".join(inputs) if inputs else "None"
                out_str = ", ".join(outputs) if outputs else "None"
                
                response_lines.append(f"\n• *{name}* ({model})")
                response_lines.append(f"  📥 Inputs: {in_str}")
                response_lines.append(f"  📤 Outputs: {out_str}")
            
        final_message = "\n".join(response_lines)
        
        conn.close()
        
        if on_complete:
            try:
                on_complete(final_message)
            except Exception as e:
                logger.error(f"on_complete callback failed: {e}")
                
        return message_id, session_id, True  # is_sync=True (immediate response)

    conn.close()

    # 4. Dispatch processing in a background thread
    thread = threading.Thread(
        target=process_message,
        args=(message_id, session_id, content),
        kwargs={"on_complete": on_complete},
        daemon=True
    )
    thread.start()
    logger.info(f"Dispatched thread for message {message_id} in session {session_id}")

    return message_id, session_id, False  # is_sync=False (async processing)


def route_ide_message(channel_id, content, sender_id=None):
    """
    Routes messages for the IDE interface.
    Dispatches processing in a background thread. Returns immediately.
    """
    conn = get_db()
    cursor = conn.cursor()

    agent_id = 'agent-1'

    cursor.execute('SELECT id FROM sessions WHERE agent_id = ? AND channel_id = ?', (agent_id, channel_id))
    session = cursor.fetchone()

    if session:
        session_id = session['id']
    else:
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        cursor.execute('INSERT INTO sessions (id, agent_id, channel_id) VALUES (?, ?, ?)',
                       (session_id, agent_id, channel_id))
        conn.commit()

    message_id = f"msg-in-{uuid.uuid4().hex[:8]}"
    cursor.execute('''
        INSERT INTO ide_messages_in (id, session_id, content, sender_id)
        VALUES (?, ?, ?, ?)
    ''', (message_id, session_id, content, sender_id))
    conn.commit()
    conn.close()

    # Dispatch processing in a background thread
    thread = threading.Thread(
        target=process_ide_message,
        args=(message_id, session_id, content),
        daemon=True
    )
    thread.start()
    logger.info(f"Dispatched IDE thread for message {message_id} in session {session_id}")

    return message_id, session_id
