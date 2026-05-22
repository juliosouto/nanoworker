from flask import Flask, render_template, request, jsonify, send_file, Response
from database import init_db, get_db, get_config, set_config, get_ide_config, set_ide_config
from router import route_inbound_message, route_ide_message
import subprocess
from channels.whatsapp_cloud import (
    verify_webhook as wa_verify,
    parse_incoming_messages as wa_parse,
    send_text_message as wa_send,
    mark_as_read as wa_mark_read,
    is_configured as wa_is_configured,
)
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import logging
import atexit

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Initialize database and apply migrations on startup
init_db()

# Ensure static directory exists
if not os.path.exists('static'):
    os.makedirs('static')

# Global variable for project path
CURRENT_PROJECT_PATH = get_ide_config('CURRENT_PROJECT_PATH')

# Start the Baileys background worker
worker_process = None
run_workers = False
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    run_workers = True
elif __name__ != '__main__':
    run_workers = True

if run_workers:
    worker_script = os.path.join(os.path.dirname(__file__), 'node_scripts', 'wa_worker.js')
    if os.path.exists(worker_script):
        logging.info("Starting Baileys WhatsApp Worker (wa_worker.js) in the background...")
        worker_process = subprocess.Popen(['node', worker_script])
        
        def cleanup_worker():
            if worker_process:
                logging.info("Shutting down Baileys WhatsApp Worker...")
                worker_process.terminate()
                worker_process.wait()
                
        atexit.register(cleanup_worker)

    import threading
    from sweeper import sweep
    sweeper_thread = threading.Thread(target=sweep, daemon=True)
    sweeper_thread.start()
    logging.info("Started Sweeper thread for scheduled tasks.")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_file_tree(dir_path, base_dir):
    tree = []
    try:
        entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name in ['.git', '.venv', 'node_modules', '__pycache__', '.DS_Store', '.whatsapp_session', 'nanoworker.db', '.store']:
                continue
            
            rel_path = os.path.relpath(entry.path, start=base_dir)
            
            if entry.is_dir():
                tree.append({
                    "name": entry.name,
                    "path": rel_path,
                    "type": "directory",
                    "children": get_file_tree(entry.path, base_dir)
                })
            else:
                tree.append({
                    "name": entry.name,
                    "path": rel_path,
                    "type": "file"
                })
    except Exception as e:
        logging.error(f"Error reading directory {dir_path}: {e}")
    return tree

@app.route('/')
def chat():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents')
    agents = cursor.fetchall()
    
    cursor.execute('''
        SELECT 
            s.id, s.agent_id, s.channel_id, s.created_at,
            (
                SELECT MAX(created_at) FROM (
                    SELECT created_at FROM messages_in WHERE session_id = s.id
                    UNION ALL
                    SELECT created_at FROM messages_out WHERE session_id = s.id
                )
            ) as last_message_at
        FROM sessions s
        WHERE s.channel_id LIKE 'web-chat%'
        ORDER BY COALESCE(last_message_at, s.created_at) DESC
    ''')
    sessions = cursor.fetchall()
    
    chat_id = request.args.get('chat_id')
    if not chat_id and sessions:
        first_channel = sessions[0]['channel_id']
        chat_id = first_channel.replace('web-chat-', '') if first_channel.startswith('web-chat-') else 'default'

    if chat_id:
        channel_id = f"web-chat-{chat_id}" if chat_id != 'default' else 'web-chat'
        cursor.execute('SELECT id FROM sessions WHERE channel_id = ?', (channel_id,))
        session = cursor.fetchone()
        if session:
            session_id = session['id']
            cursor.execute('''
                SELECT 'in' as type, id, session_id, content, image_base64, file_mime_type, file_name, created_at FROM messages_in WHERE session_id = ?
                UNION ALL
                SELECT 'out' as type, id, session_id, content, NULL as image_base64, NULL as file_mime_type, NULL as file_name, created_at FROM messages_out WHERE session_id = ?
                ORDER BY created_at DESC, type DESC LIMIT 50
            ''', (session_id, session_id))
            messages = cursor.fetchall()
            messages = list(messages)[::-1]
        else:
            messages = []
    else:
        messages = []

    conn.close()
    
    return render_template('chat.html', agents=agents, messages=messages, sessions=sessions, chat_id=chat_id)

@app.route('/ide')
def ide_page():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents')
    agents = cursor.fetchall()
    
    cursor.execute('''
        SELECT 
            s.id, s.agent_id, s.channel_id, s.created_at,
            (
                SELECT MAX(created_at) FROM (
                    SELECT created_at FROM ide_messages_in WHERE session_id = s.id
                    UNION ALL
                    SELECT created_at FROM ide_messages_out WHERE session_id = s.id
                )
            ) as last_message_at
        FROM sessions s
        WHERE s.channel_id LIKE 'ide-%'
        ORDER BY COALESCE(last_message_at, s.created_at) DESC
    ''')
    sessions = cursor.fetchall()
    
    chat_id = request.args.get('chat_id')
    session_id = None
    if chat_id and sessions:
        # Find the session that matches this chat_id
        for s in sessions:
            if s['channel_id'] == f"ide-{chat_id}":
                session_id = s['id']
                break

    if session_id:
        cursor.execute('''
            SELECT 'in' as type, id, session_id, content, created_at FROM ide_messages_in WHERE session_id = ?
            UNION ALL
            SELECT 'out' as type, id, session_id, content, created_at FROM ide_messages_out WHERE session_id = ?
            ORDER BY created_at DESC, type DESC LIMIT 50
        ''', (session_id, session_id))
        messages = cursor.fetchall()
        messages = list(messages)[::-1]
    else:
        messages = []

    conn.close()
    
    return render_template('ide.html', agents=agents, messages=messages, sessions=sessions, chat_id=chat_id, session_id=session_id, current_project_path=CURRENT_PROJECT_PATH)

@app.route('/api/files', methods=['GET'])
def list_files():
    root_dir = CURRENT_PROJECT_PATH if CURRENT_PROJECT_PATH else ROOT_DIR
    tree = get_file_tree(root_dir, root_dir)
    return jsonify(tree)

@app.route('/api/files/content', methods=['GET'])
def get_file_content():
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({"error": "Path is required"}), 400
    
    root_dir = CURRENT_PROJECT_PATH if CURRENT_PROJECT_PATH else ROOT_DIR
    safe_path = os.path.abspath(os.path.join(root_dir, file_path))
    if not safe_path.startswith(root_dir):
        return jsonify({"error": "Access denied"}), 403
        
    if not os.path.exists(safe_path) or os.path.isdir(safe_path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({"content": content, "path": file_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/files/save', methods=['POST'])
def save_file_content():
    data = request.json
    if not data or 'path' not in data or 'content' not in data:
        return jsonify({"error": "Missing path or content"}), 400
        
    file_path = data['path']
    content = data['content']
    
    root_dir = CURRENT_PROJECT_PATH if CURRENT_PROJECT_PATH else ROOT_DIR
    safe_path = os.path.abspath(os.path.join(root_dir, file_path))
    if not safe_path.startswith(root_dir):
        return jsonify({"error": "Access denied"}), 403
        
    try:
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "File saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/temp/<path:filename>')
def serve_temp_file(filename):
    import os
    from flask import send_file
    safe_path = os.path.abspath(os.path.join("temp", filename))
    if not safe_path.startswith(os.path.abspath("temp")):
        return "Access denied", 403
    if not os.path.exists(safe_path):
        return "File not found", 404
    return send_file(safe_path)

@app.route('/api/set_project_path', methods=['POST'])
def set_project_path():
    global CURRENT_PROJECT_PATH
    data = request.json
    project_path = data.get('project_path')
    
    if not project_path:
        return jsonify({"error": "Missing project_path"}), 400
    
    abs_path = os.path.abspath(project_path)
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return jsonify({"error": "Invalid directory path"}), 400
        
    CURRENT_PROJECT_PATH = abs_path
    set_ide_config('CURRENT_PROJECT_PATH', abs_path)
    return jsonify({"status": "success", "project_path": abs_path})

@app.route('/api/select_folder_dialog', methods=['GET'])
def select_folder_dialog():
    try:
        script = '''
        tell application "System Events"
            activate
            set theFolder to choose folder with prompt "Select Project Folder:"
            POSIX path of theFolder
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if result.returncode == 0:
            folder_path = result.stdout.strip()
            return jsonify({"status": "success", "path": folder_path})
        else:
            return jsonify({"status": "cancelled", "path": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/settings')
def settings_page():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents')
    agents = cursor.fetchall()
    cursor.execute('SELECT * FROM sessions')
    sessions = cursor.fetchall()
    conn.close()

    current_model = get_config('GEMINI_MODEL', 'gemini-2.0-flash')
    has_api_key = bool(get_config('GEMINI_API_KEY'))
    has_wa_token = bool(os.environ.get('WHATSAPP_ACCESS_TOKEN'))
    wa_phone_id = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')
    wa_verify_token = get_config('WHATSAPP_VERIFY_TOKEN', '')
    
    # Check if Baileys session exists
    auth_path = os.path.join(os.path.dirname(__file__), '.store', 'auth', 'creds.json')
    has_wa_web_session = os.path.exists(auth_path)
    
    return render_template('settings.html', 
        agents=agents, sessions=sessions, 
        current_model=current_model, has_api_key=has_api_key,
        has_wa_token=has_wa_token, wa_phone_id=wa_phone_id, 
        wa_verify_token=wa_verify_token, has_wa_web_session=has_wa_web_session,
        system_prompt=get_config('SYSTEM_PROMPT', ''),
        thinking_enabled=get_config('THINKING_ENABLED', 'false').lower() == 'true')

@app.route('/settings/whatsapp')
def whatsapp_settings_page():
    auth_path = os.path.join(os.path.dirname(__file__), '.store', 'auth', 'creds.json')
    has_wa_web_session = os.path.exists(auth_path)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allowed_from, allowed_to, bot_enabled, allow_mentions FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    conn.close()
    
    allowed_from = config['allowed_from'] if config else ''
    allowed_to = config['allowed_to'] if config else ''
    bot_enabled = bool(config['bot_enabled']) if config else True
    
    # Safely handle missing column before migration runs
    try:
        allow_mentions = bool(config['allow_mentions']) if config else True
    except (IndexError, KeyError):
        allow_mentions = True
    
    return render_template('whatsapp_settings.html', 
                           has_wa_web_session=has_wa_web_session,
                           allowed_from=allowed_from,
                           allowed_to=allowed_to,
                           bot_enabled=bot_enabled,
                           allow_mentions=allow_mentions)

@app.route('/api/whatsapp/config', methods=['POST'])
def save_whatsapp_config():
    data = request.json
    allowed_from = data.get('allowed_from', '')
    allowed_to = data.get('allowed_to', '')
    bot_enabled = 1 if data.get('bot_enabled') else 0
    allow_mentions = 1 if data.get('allow_mentions') else 0
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE whatsapp_config 
        SET allowed_from = ?, allowed_to = ?, bot_enabled = ?, allow_mentions = ?
        WHERE id = 1
    ''', (allowed_from, allowed_to, bot_enabled, allow_mentions))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/config/agent_name', methods=['GET'])
def get_agent_name_api():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allow_mentions FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    conn.close()
    
    try:
        allow_mentions = bool(config['allow_mentions']) if config else True
    except (IndexError, KeyError):
        allow_mentions = True
        
    return jsonify({
        "agent_name": get_config('agent_name', ''),
        "allow_mentions": allow_mentions
    })

@app.route('/settings/general')
def general_config_page():
    return render_template('general_config.html')

@app.route('/settings/agent_behavior')
def agent_behavior_config_page():
    return render_template('agent_behavior_config.html',
        agent_name=get_config('agent_name', ''),
        system_prompt=get_config('SYSTEM_PROMPT', ''),
        thinking_enabled=get_config('THINKING_ENABLED', 'false').lower() == 'true',
        add_datetime_enabled=get_config('ADD_DATETIME_ENABLED', 'false').lower() == 'true',
        ide_prompt=get_config('IDE_PROMPT', ''))

@app.route('/settings/permissions')
def permissions_config_page():
    return render_template('permissions_config.html',
        perm_terminal=get_config('PERM_TERMINAL', 'false').lower() == 'true',
        perm_playwright=get_config('PERM_PLAYWRIGHT', 'false').lower() == 'true',
        perm_safari=get_config('PERM_SAFARI', 'false').lower() == 'true',
        perm_fs=get_config('PERM_FS', 'false').lower() == 'true',
        perm_calendar=get_config('PERM_CALENDAR', 'false').lower() == 'true',
        perm_contacts=get_config('PERM_CONTACTS', 'false').lower() == 'true',
        perm_photos=get_config('PERM_PHOTOS', 'false').lower() == 'true',
        perm_icloud=get_config('PERM_ICLOUD', 'false').lower() == 'true',
        perm_notes=get_config('PERM_NOTES', 'false').lower() == 'true',
        perm_reminders=get_config('PERM_REMINDERS', 'false').lower() == 'true',
        perm_mail=get_config('PERM_MAIL', 'false').lower() == 'true',
        perm_messages=get_config('PERM_MESSAGES', 'false').lower() == 'true',
        perm_system_data=get_config('PERM_SYSTEM_DATA', 'false').lower() == 'true',
        perm_screenshot=get_config('PERM_SCREENSHOT', 'false').lower() == 'true'
    )

@app.route('/api/permissions/request', methods=['POST'])
def request_os_permission():
    data = request.json
    perm_type = data.get('permission')
    
    try:
        if perm_type == 'calendar':
            # Trigger Calendar permission prompt
            subprocess.run(['osascript', '-e', 'tell application "Calendar" to get calendars'], capture_output=True, timeout=5)
        elif perm_type == 'contacts':
            subprocess.run(['osascript', '-e', 'tell application "Contacts" to get name of people'], capture_output=True, timeout=5)
        elif perm_type == 'terminal':
            # Trigger Terminal/Automation permission prompt
            subprocess.run(['osascript', '-e', 'tell application "Terminal" to get windows'], capture_output=True, timeout=5)
        elif perm_type == 'safari':
            # Trigger Safari Automation permission prompt
            subprocess.run(['osascript', '-e', 'tell application "Safari" to get properties of front document'], capture_output=True, timeout=5)
        elif perm_type == 'fs':
            # Trigger File System (Documents/Desktop) permission prompt
            import os
            docs_path = os.path.expanduser('~/Documents')
            if os.path.exists(docs_path):
                subprocess.run(['ls', docs_path], capture_output=True, timeout=5)
        elif perm_type == 'photos':
            subprocess.run(['osascript', '-e', 'tell application "Photos" to get name of albums'], capture_output=True, timeout=5)
        elif perm_type == 'notes':
            subprocess.run(['osascript', '-e', 'tell application "Notes" to get name of folders'], capture_output=True, timeout=5)
        elif perm_type == 'reminders':
            subprocess.run(['osascript', '-e', 'tell application "Reminders" to get name of lists'], capture_output=True, timeout=5)
        elif perm_type == 'icloud':
            import os
            icloud_path = os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/')
            if os.path.exists(icloud_path):
                subprocess.run(['ls', icloud_path], capture_output=True, timeout=5)
        elif perm_type == 'mail':
            subprocess.run(['osascript', '-e', 'tell application "Mail" to get name of accounts'], capture_output=True, timeout=5)
        elif perm_type == 'system_data':
            import os
            safari_path = os.path.expanduser('~/Library/Safari')
            if os.path.exists(safari_path):
                subprocess.run(['ls', safari_path], capture_output=True, timeout=5)
                
        return jsonify({"status": "success", "message": f"Permission requested for {perm_type}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/settings/llm')
def llm_config_page():
    current_model = get_config('GEMINI_MODEL', 'gemini-2.0-flash')
    has_api_key = bool(get_config('GEMINI_API_KEY'))
    qwen_model = os.environ.get('QWEN_MODEL', 'qwen-plus')
    has_qwen_key = bool(get_config('QWEN_API_KEY'))
    deepseek_model = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
    has_deepseek_key = bool(get_config('DEEPSEEK_API_KEY'))
    openai_model = os.environ.get('OPENAI_MODEL', 'gpt-4o')
    has_openai_key = bool(get_config('OPENAI_API_KEY'))
    anthropic_model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
    has_anthropic_key = bool(get_config('ANTHROPIC_API_KEY'))
    
    llm_pref_1 = os.environ.get('LLM_PREF_1', '')
    llm_pref_2 = get_config('LLM_PREF_2', '')
    llm_pref_3 = get_config('LLM_PREF_3', '')
    llm_pref_4 = get_config('LLM_PREF_4', '')
    llm_pref_5 = get_config('LLM_PREF_5', '')

    return render_template('llm_config.html', 
        current_model=current_model, has_api_key=has_api_key,
        qwen_model=qwen_model, has_qwen_key=has_qwen_key,
        deepseek_model=deepseek_model, has_deepseek_key=has_deepseek_key,
        openai_model=openai_model, has_openai_key=has_openai_key,
        anthropic_model=anthropic_model, has_anthropic_key=has_anthropic_key,
        llm_pref_1=llm_pref_1, llm_pref_2=llm_pref_2,
        llm_pref_3=llm_pref_3, llm_pref_4=llm_pref_4,
        llm_pref_5=llm_pref_5)

@app.route('/cron')
def cron_jobs_page():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.id, c.session_id, c.description, c.content, c.cron_expression, c.next_run, c.is_active, s.channel_id
        FROM cron_jobs c
        LEFT JOIN sessions s ON c.session_id = s.id
        ORDER BY c.next_run ASC
    ''')
    jobs = cursor.fetchall()
    conn.close()
    return render_template('cron_jobs.html', jobs=jobs)

@app.route('/api/cron/<job_id>/toggle', methods=['POST'])
def toggle_cron_job(job_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT is_active FROM cron_jobs WHERE id = ?', (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Job not found"}), 404
        
    new_status = 0 if row['is_active'] else 1
    cursor.execute('UPDATE cron_jobs SET is_active = ? WHERE id = ?', (new_status, job_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "is_active": bool(new_status)}), 200

@app.route('/api/cron/<job_id>', methods=['DELETE'])
def delete_cron_job(job_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cron_jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200

@app.route('/api/whatsapp/auth-stream')
def whatsapp_auth_stream():
    """
    SSE endpoint to stream QR code from the Node.js Baileys subprocess.
    """
    def generate():
        script_path = os.path.join(os.path.dirname(__file__), 'node_scripts', 'wa_auth.js')
        process = subprocess.Popen(
            ['node', script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    yield f"data: {line.strip()}\n\n"
        finally:
            process.terminate()
            process.wait()

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/whatsapp/logout', methods=['POST'])
def whatsapp_logout():
    import shutil
    auth_dir = os.path.join(os.path.dirname(__file__), '.store', 'auth')
    if os.path.exists(auth_dir):
        shutil.rmtree(auth_dir)
    return jsonify({"status": "success"})

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

    import requests
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

@app.route('/api/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'content' not in data or 'channel_id' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    if data['channel_id'].startswith('wa_web:'):
        if not should_process_wa_message(data.get('sender_id'), data.get('content', '')):
            logging.info(f"Ignored message from {data.get('sender_id')} due to WhatsApp config permissions.")
            return jsonify({"status": "ignored", "reason": "permissions_or_disabled"}), 200

    content = data['content']
    
    # Process audio if present
    if 'audio_base64' in data:
        import base64
        import tempfile
        from utils.audio import transcribe_audio
        try:
            audio_data = base64.b64decode(data['audio_base64'])
            ext = ".ogg"
            if data.get('mimetype', '').startswith('audio/mp4'):
                ext = ".m4a"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                tf.write(audio_data)
                temp_path = tf.name
                
            transcription = transcribe_audio(temp_path)
            content = f"{content}\n[Transcrição]: {transcription}"
            
            try:
                os.unlink(temp_path)
            except:
                pass
        except Exception as e:
            logging.error(f"Failed to process webhook audio: {e}")
            content = f"{content}\n[Erro interno ao processar áudio]"
            
    # Build on_complete callback for WhatsApp Baileys replies
    on_complete = None
    if data['channel_id'].startswith('wa_web:'):
        # Trigger typing indicator
        try:
            import requests as req
            target_jid = data.get('sender_jid')
            if not target_jid:
                target_jid = f"{data.get('sender_id')}@s.whatsapp.net"
            req.post('http://127.0.0.1:3000/presence', json={"jid": target_jid, "state": "composing"}, timeout=1)
        except Exception as e:
            logging.error(f"Failed to send composing presence: {e}")

        def on_complete(out_text):
            import requests as req
            from utils.audio_utils import extract_and_generate_audio
            target_jid = data.get('sender_jid')
            if not target_jid:
                target_jid = f"{data.get('sender_id')}@s.whatsapp.net"
            
            try:
                logging.info(f"on_complete triggered for {target_jid} with text length {len(out_text)}")
                text_to_send, audio_path = extract_and_generate_audio(out_text)
                
                if text_to_send:
                    resp = req.post('http://127.0.0.1:3000/send', json={"text": text_to_send, "jid": target_jid}, timeout=5)
                    logging.info(f"Text send response: {resp.status_code} {resp.text}")
                    
                if audio_path:
                    resp = req.post('http://127.0.0.1:3000/send_audio', json={"file_path": audio_path, "jid": target_jid}, timeout=5)
                    logging.info(f"Audio send response: {resp.status_code} {resp.text}")
                elif '<audio>' in out_text and not audio_path:
                    resp = req.post('http://127.0.0.1:3000/send', json={"text": "[Erro ao gerar áudio]", "jid": target_jid}, timeout=5)
                    logging.info(f"Audio error send response: {resp.status_code} {resp.text}")

            except Exception as e:
                logging.error(f"Failed to send reply to Baileys Worker: {e}")

    file_path = None
    b64_data = data.get('file_base64') or data.get('image_base64')
    if b64_data:
        import uuid
        import base64
        import os
        try:
            # Create temp dir if it doesn't exist
            os.makedirs("temp", exist_ok=True)
            fname = data.get('file_name', 'attachment')
            file_path = os.path.join("temp", f"{uuid.uuid4().hex}_{fname}")
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            # Prefix with path: so the reader knows it's a file
            file_path = "path:" + file_path
        except Exception as e:
            logging.error(f"Failed to save attachment to temp/: {e}")
            file_path = None

    in_id, session_id, is_sync = route_inbound_message(
        channel_id=data['channel_id'],
        content=content,
        sender_id=data.get('sender_id'),
        image_base64=file_path,
        file_mime_type=data.get('file_mime_type'),
        file_name=data.get('file_name'),
        on_complete=on_complete
    )
    
    # /new command is synchronous — return immediate response
    if is_sync:
        return jsonify({
            "status": "received",
            "message_in_id": in_id,
            "session_id": session_id,
            "response_text": "History cleared! Starting a new conversation.",
            "created_at": "Just now"
        }), 200

    return jsonify({
        "status": "processing", 
        "message_in_id": in_id,
        "session_id": session_id,
    }), 202

@app.route('/api/ide-webhook', methods=['POST'])
def ide_webhook():
    data = request.json
    if not data or 'content' not in data or 'channel_id' not in data:
        return jsonify({"error": "Missing required fields"}), 400
        
    in_id, session_id = route_ide_message(
        channel_id=data['channel_id'],
        content=data['content'],
        sender_id=data.get('sender_id')
    )

    return jsonify({
        "status": "processing", 
        "message_in_id": in_id,
        "session_id": session_id,
    }), 202


@app.route('/api/messages/poll', methods=['GET'])
def poll_messages():
    """
    Polling endpoint for frontends to fetch new messages.
    Query params:
      - message_in_id: the inbound message ID to find replies for
      - type: 'chat' or 'ide' — which message tables to query
    """
    message_in_id = request.args.get('message_in_id')
    msg_type = request.args.get('type', 'chat')

    if not message_in_id:
        return jsonify({"error": "message_in_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    is_done = False

    if msg_type == 'ide':
        cursor.execute('''
            SELECT id, session_id, content, created_at
            FROM ide_messages_out
            WHERE in_reply_to = ?
            ORDER BY created_at ASC
        ''', (message_in_id,))
        rows = cursor.fetchall()
        
        cursor.execute('SELECT processed FROM ide_messages_in WHERE id = ?', (message_in_id,))
        status_row = cursor.fetchone()
    else:
        cursor.execute('''
            SELECT id, session_id, content, created_at
            FROM messages_out
            WHERE in_reply_to = ?
            ORDER BY created_at ASC
        ''', (message_in_id,))
        rows = cursor.fetchall()
        
        cursor.execute('SELECT processed FROM messages_in WHERE id = ?', (message_in_id,))
        status_row = cursor.fetchone()

    if status_row and status_row['processed'] == 2:
        is_done = True

    messages = []
    for row in rows:
        messages.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "content": row["content"],
            "created_at": row["created_at"],
        })

    conn.close()
    return jsonify({"messages": messages, "is_done": is_done}), 200


@app.route('/api/chat/search', methods=['GET'])
def search_chat_sessions():
    """
    Search across all web-chat sessions for messages containing the query.
    Returns a list of matching channel_ids so the sidebar can be filtered.
    Query params:
      - q: search query string
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"matching_channels": []}), 200

    conn = get_db()
    cursor = conn.cursor()
    like_pattern = f'%{query}%'

    cursor.execute('''
        SELECT DISTINCT s.channel_id
        FROM sessions s
        WHERE s.channel_id LIKE 'web-chat%'
          AND (
              EXISTS (
                  SELECT 1 FROM messages_in mi
                  WHERE mi.session_id = s.id AND mi.content LIKE ? COLLATE NOCASE
              )
              OR EXISTS (
                  SELECT 1 FROM messages_out mo
                  WHERE mo.session_id = s.id AND mo.content LIKE ? COLLATE NOCASE
              )
          )
    ''', (like_pattern, like_pattern))

    rows = cursor.fetchall()
    matching = [row['channel_id'] for row in rows]
    conn.close()

    return jsonify({"matching_channels": matching}), 200

@app.route('/api/chat/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    conn = get_db()
    cursor = conn.cursor()
    channel_id = f"web-chat-{chat_id}" if chat_id != 'default' else 'web-chat'
    
    cursor.execute('SELECT id FROM sessions WHERE channel_id = ?', (channel_id,))
    session = cursor.fetchone()
    
    if session:
        session_id = session['id']
        cursor.execute('DELETE FROM messages_in WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM messages_out WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM cron_jobs WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
    
    conn.close()
    return jsonify({"status": "success"}), 200

# ---------------------------------------------------------------------------
# WhatsApp Cloud API Webhook (Mantido)
# ---------------------------------------------------------------------------

@app.route('/whatsapp/webhook', methods=['GET'])
def whatsapp_verify():
    body, status = wa_verify(request.args)
    return body, status

@app.route('/whatsapp/webhook', methods=['POST'])
def whatsapp_inbound():
    payload = request.json
    messages = wa_parse(payload)

    for msg in messages:
        sender_id = msg["sender"]
        
        if not should_process_wa_message(sender_id):
            logging.info(f"Ignored Cloud API message from {sender_id} due to WhatsApp config permissions.")
            continue

        channel_id = f"whatsapp:{sender_id}"
        content = msg["content"]
        wa_mark_read(msg["message_id"])
        
        # Build callback to send reply via WhatsApp Cloud API
        def make_wa_callback(sid):
            def callback(out_text):
                wa_send(sid, out_text)
            return callback

        route_inbound_message(
            channel_id=channel_id,
            content=content,
            sender_id=sender_id,
            on_complete=make_wa_callback(sender_id)
        )

    return jsonify({"status": "ok"}), 200

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    
    mapping = {
        'gemini_api_key': 'GEMINI_API_KEY',
        'llm_model': 'GEMINI_MODEL',
        'qwen_api_key': 'QWEN_API_KEY',
        'qwen_model': 'QWEN_MODEL',
        'deepseek_api_key': 'DEEPSEEK_API_KEY',
        'deepseek_model': 'DEEPSEEK_MODEL',
        'openai_api_key': 'OPENAI_API_KEY',
        'openai_model': 'OPENAI_MODEL',
        'anthropic_api_key': 'ANTHROPIC_API_KEY',
        'anthropic_model': 'ANTHROPIC_MODEL',
        'llm_pref_1': 'LLM_PREF_1',
        'llm_pref_2': 'LLM_PREF_2',
        'llm_pref_3': 'LLM_PREF_3',
        'llm_pref_4': 'LLM_PREF_4',
        'llm_pref_5': 'LLM_PREF_5',
        'whatsapp_access_token': 'WHATSAPP_ACCESS_TOKEN',
        'whatsapp_phone_number_id': 'WHATSAPP_PHONE_NUMBER_ID',
        'whatsapp_verify_token': 'WHATSAPP_VERIFY_TOKEN',
        'system_prompt': 'SYSTEM_PROMPT',
        'ide_prompt': 'IDE_PROMPT',
        'agent_name': 'agent_name'
    }
    
    for json_key, db_key in mapping.items():
        if json_key in data and data[json_key] is not None:
            set_config(db_key, data[json_key])
            
    bool_mapping = {
        'thinking_enabled': 'THINKING_ENABLED',
        'add_datetime_enabled': 'ADD_DATETIME_ENABLED',
        'perm_terminal': 'PERM_TERMINAL',
        'perm_playwright': 'PERM_PLAYWRIGHT',
        'perm_safari': 'PERM_SAFARI',
        'perm_fs': 'PERM_FS',
        'perm_calendar': 'PERM_CALENDAR',
        'perm_contacts': 'PERM_CONTACTS',
        'perm_photos': 'PERM_PHOTOS',
        'perm_icloud': 'PERM_ICLOUD',
        'perm_notes': 'PERM_NOTES',
        'perm_reminders': 'PERM_REMINDERS',
        'perm_mail': 'PERM_MAIL',
        'perm_messages': 'PERM_MESSAGES',
        'perm_system_data': 'PERM_SYSTEM_DATA',
        'perm_screenshot': 'PERM_SCREENSHOT'
    }
    
    for json_key, db_key in bool_mapping.items():
        if json_key in data and data[json_key] is not None:
            val = 'true' if data[json_key] else 'false'
            set_config(db_key, val)
            
    return jsonify({"status": "success", "message": "Settings saved"}), 200

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
