import os
import subprocess

from flask import Blueprint, jsonify, request

from database import get_config, get_db, set_config, update_tool_config
from security import limiter

api_settings_bp = Blueprint('api_settings', __name__)

@api_settings_bp.route('/api/config/agent_name', methods=['GET'])
def get_agent_name_api():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allow_mentions, allow_audio_mentions FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    
    # Query all worker names
    cursor.execute('SELECT worker_name FROM workers_config')
    worker_names = [row['worker_name'].strip() for row in cursor.fetchall()]
    conn.close()
    
    try:
        allow_mentions = bool(config['allow_mentions']) if config else True
    except (IndexError, KeyError):
        allow_mentions = True

    try:
        allow_audio_mentions = bool(config['allow_audio_mentions']) if config else False
    except (IndexError, KeyError):
        allow_audio_mentions = False
        
    from utils.message_utils import get_default_worker
    default_worker = get_default_worker()
    agent_name = default_worker['worker_name'] if default_worker else ''
    
    require_at_prefix = get_config("REQUIRE_AT_PREFIX", "true").lower() == "true"
    use_recipes_as_tools = get_config("USE_RECIPES_AS_TOOLS", "true").lower() == "true"
    try:
        autonomous_mode = int(get_config("AUTONOMOUS_MODE", "1"))
    except (ValueError, TypeError):
        autonomous_mode = 1
    
    return jsonify({
        "agent_name": agent_name,
        "worker_names": worker_names,
        "allow_mentions": allow_mentions,
        "allow_audio_mentions": allow_audio_mentions,
        "require_at_prefix": require_at_prefix,
        "use_recipes_as_tools": use_recipes_as_tools,
        "autonomous_mode": autonomous_mode
    })

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
        'openrouter_api_key': 'OPENROUTER_API_KEY',
        'openrouter_model': 'OPENROUTER_MODEL',
        'llm_pref_1': 'LLM_PREF_1',
        'llm_pref_2': 'LLM_PREF_2',
        'llm_pref_3': 'LLM_PREF_3',
        'llm_pref_4': 'LLM_PREF_4',
        'llm_pref_5': 'LLM_PREF_5',
        'whatsapp_access_token': 'WHATSAPP_ACCESS_TOKEN',
        'whatsapp_phone_number_id': 'WHATSAPP_PHONE_NUMBER_ID',
        'whatsapp_verify_token': 'WHATSAPP_VERIFY_TOKEN',
        'ide_prompt': 'IDE_PROMPT',
        'whisper_model': 'WHISPER_MODEL',
        'autonomous_mode': 'AUTONOMOUS_MODE',
        'message_slice_size_tokens': 'MESSAGE_SLICE_SIZE_TOKENS'
    }
    
    for json_key, db_key in mapping.items():
        if json_key in data and data[json_key] is not None:
            set_config(db_key, data[json_key])
            
    bool_mapping = {
        'require_at_prefix': 'REQUIRE_AT_PREFIX',
        'use_recipes_as_tools': 'USE_RECIPES_AS_TOOLS',
        'show_tools_results': 'SHOW_TOOLS_RESULTS',
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
        'perm_web_search': 'PERM_WEB_SEARCH',
        'perm_tool_creator': 'PERM_TOOL_CREATOR',
        'tool_creator_double_check': 'TOOL_CREATOR_DOUBLE_CHECK'
    }
    
    for json_key, db_key in bool_mapping.items():
        if json_key in data and data[json_key] is not None:
            val = 'true' if data[json_key] else 'false'
            set_config(db_key, val)
            
    return jsonify({"status": "success", "message": "Settings saved"}), 200

@api_settings_bp.route('/api/settings/tools', methods=['POST'])
def save_tool_setting():
    data = request.json
    tool_name = data.get('tool_name')
    
    if tool_name is not None:
        updates = {}
        if 'enabled' in data:
            updates['enabled'] = data['enabled']
        if 'allow_others_from_direct_msgs' in data:
            updates['allow_others_from_direct_msgs'] = data['allow_others_from_direct_msgs']
        if 'allow_others_from_group_msgs' in data:
            updates['allow_others_from_group_msgs'] = data['allow_others_from_group_msgs']
            
        update_tool_config(tool_name, updates)
        return jsonify({"status": "success", "message": f"Tool {tool_name} saved"}), 200
    
    return jsonify({"status": "error", "message": "Invalid payload"}), 400

@api_settings_bp.route('/api/login/toggle', methods=['POST'])
@limiter.limit("10 per minute")
def toggle_login():
    data = request.json
    enabled = data.get('enabled')
    if enabled:
        set_config('LOGIN_ENABLED', 'true')
        token = get_config('LOGIN_TOKEN')
        if not token:
            import secrets
            token = "nw-" + secrets.token_urlsafe(48)
            set_config('LOGIN_TOKEN', token)
        return jsonify({'status': 'success', 'enabled': True, 'token': token}), 200
    else:
        set_config('LOGIN_ENABLED', 'false')
        return jsonify({'status': 'success', 'enabled': False}), 200

@api_settings_bp.route('/api/settings/tools/<tool_name>', methods=['DELETE'])
def delete_self_developed_tool(tool_name):
    if '..' in tool_name or '/' in tool_name or '\\' in tool_name:
        return jsonify({"status": "error", "message": "Invalid tool name"}), 400
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os_folders = ['windows', 'linux', 'macos']
    file_deleted = False
    
    for os_name in os_folders:
        file_path = os.path.join(project_root, "tools", "self-developed", os_name, f"{tool_name}.py")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
            except Exception as e:
                return jsonify({"status": "error", "message": f"Failed to delete file: {str(e)}"}), 500
                
    if not file_deleted:
        return jsonify({"status": "error", "message": "Tool file not found"}), 404
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tools_config WHERE tool_name = ?", (tool_name.lower(),))
        conn.commit()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500
    finally:
        conn.close()
        
    return jsonify({"status": "success", "message": f"Tool {tool_name} successfully deleted"}), 200

@api_settings_bp.route('/api/setup', methods=['POST'])
@limiter.limit("5 per minute")
def initial_setup():
    data = request.json or {}
    gemini_key = data.get('gemini_api_key')
    openai_key = data.get('openai_api_key')
    groq_key = data.get('groq_api_key')
    qwen_key = data.get('qwen_api_key')
    openrouter_key = data.get('openrouter_api_key')

    # Import setup utilities
    from utils.setup_utils import (
        backup_database,
        setup_app_config,
        setup_ide_prompt,
        setup_ide_settings,
        setup_llm_config,
        setup_agents,
        setup_whatsapp_config,
        setup_workers_config,
        setup_tools_config
    )
    from database import encrypt_value

    try:
        # Backup the database before any destructive operations
        backup_path = backup_database()

        # Run all setup utilities
        setup_app_config()
        setup_ide_prompt()
        setup_ide_settings()
        setup_llm_config()
        setup_agents()
        setup_whatsapp_config()
        setup_workers_config()
        setup_tools_config()

        # Update API keys in app_config if provided
        if gemini_key:
            set_config('GEMINI_API_KEY', gemini_key)
        if openai_key:
            set_config('OPENAI_API_KEY', openai_key)
        if groq_key:
            set_config('GROQ_API_KEY', groq_key)
        if qwen_key:
            set_config('QWEN_API_KEY', qwen_key)
        if openrouter_key:
            set_config('OPENROUTER_API_KEY', openrouter_key)

        # Also update the newly seeded models in llm_config
        conn = get_db()
        cursor = conn.cursor()
        try:
            if gemini_key:
                enc_gemini = encrypt_value(gemini_key)
                cursor.execute("UPDATE llm_config SET api_key = ? WHERE provider = 'Google'", (enc_gemini,))
            if openai_key:
                enc_openai = encrypt_value(openai_key)
                cursor.execute("UPDATE llm_config SET api_key = ? WHERE provider = 'OpenAI' OR provider = 'openai'", (enc_openai,))
            if groq_key:
                enc_groq = encrypt_value(groq_key)
                cursor.execute("UPDATE llm_config SET api_key = ? WHERE provider = 'Groq' OR provider = 'groq'", (enc_groq,))
            if qwen_key:
                enc_qwen = encrypt_value(qwen_key)
                cursor.execute("UPDATE llm_config SET api_key = ? WHERE provider = 'DashScope' OR provider = 'Qwen'", (enc_qwen,))
            if openrouter_key:
                enc_or = encrypt_value(openrouter_key)
                cursor.execute("UPDATE llm_config SET api_key = ? WHERE provider = 'OpenRouter' OR provider = 'openrouter'", (enc_or,))
            conn.commit()
        finally:
            conn.close()

        return jsonify({"status": "success", "message": "Setup completed successfully!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

