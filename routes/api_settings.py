import os
import subprocess

from flask import Blueprint, jsonify, request

from database import get_config, get_db, set_config

api_settings_bp = Blueprint('api_settings', __name__)

@api_settings_bp.route('/api/config/agent_name', methods=['GET'])
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

@api_settings_bp.route('/api/permissions/request', methods=['POST'])
def request_os_permission():
    data = request.json
    perm_type = data.get('permission')
    
    try:
        if perm_type == 'calendar':
            subprocess.run(['osascript', '-e', 'tell application "Calendar" to get calendars'], capture_output=True, timeout=5)
        elif perm_type == 'contacts':
            subprocess.run(['osascript', '-e', 'tell application "Contacts" to get name of people'], capture_output=True, timeout=5)
        elif perm_type == 'terminal':
            subprocess.run(['osascript', '-e', 'tell application "Terminal" to get windows'], capture_output=True, timeout=5)
        elif perm_type == 'safari':
            subprocess.run(['osascript', '-e', 'tell application "Safari" to get properties of front document'], capture_output=True, timeout=5)
        elif perm_type == 'fs':
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
            icloud_path = os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/')
            if os.path.exists(icloud_path):
                subprocess.run(['ls', icloud_path], capture_output=True, timeout=5)
        elif perm_type == 'mail':
            subprocess.run(['osascript', '-e', 'tell application "Mail" to get name of accounts'], capture_output=True, timeout=5)
        elif perm_type == 'system_data':
            safari_path = os.path.expanduser('~/Library/Safari')
            if os.path.exists(safari_path):
                subprocess.run(['ls', safari_path], capture_output=True, timeout=5)
                
        return jsonify({"status": "success", "message": f"Permission requested for {perm_type}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_settings_bp.route('/api/settings', methods=['POST'])
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
        'perm_screenshot': 'PERM_SCREENSHOT',
        'perm_web_search': 'PERM_WEB_SEARCH'
    }
    
    for json_key, db_key in bool_mapping.items():
        if json_key in data and data[json_key] is not None:
            val = 'true' if data[json_key] else 'false'
            set_config(db_key, val)
            
    return jsonify({"status": "success", "message": "Settings saved"}), 200
