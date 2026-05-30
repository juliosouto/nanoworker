import os

from flask import Blueprint, render_template, request

import state
from database import get_config, get_db

views_bp = Blueprint('views', __name__)

@views_bp.route('/')
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

@views_bp.route('/ide')
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
    return render_template('ide.html', agents=agents, messages=messages, sessions=sessions, chat_id=chat_id, session_id=session_id, current_project_path=state.CURRENT_PROJECT_PATH)

@views_bp.route('/settings')
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
    
    auth_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.store', 'auth', 'creds.json')
    has_wa_web_session = os.path.exists(auth_path)
    
    return render_template('settings.html', 
        agents=agents, sessions=sessions, 
        current_model=current_model, has_api_key=has_api_key,
        has_wa_token=has_wa_token, wa_phone_id=wa_phone_id, 
        wa_verify_token=wa_verify_token, has_wa_web_session=has_wa_web_session,
        system_prompt=get_config('SYSTEM_PROMPT', ''),
        thinking_enabled=get_config('THINKING_ENABLED', 'false').lower() == 'true')

@views_bp.route('/settings/whatsapp')
def whatsapp_settings_page():
    auth_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.store', 'auth', 'creds.json')
    has_wa_web_session = os.path.exists(auth_path)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT allowed_from, allowed_to, bot_enabled, allow_mentions, allow_audio_mentions, rate_limit_per_minute FROM whatsapp_config WHERE id = 1')
    config = cursor.fetchone()
    conn.close()
    
    allowed_from = config['allowed_from'] if config else ''
    allowed_to = config['allowed_to'] if config else ''
    bot_enabled = bool(config['bot_enabled']) if config else True
    
    try:
        allow_mentions = bool(config['allow_mentions']) if config else True
    except (IndexError, KeyError):
        allow_mentions = True

    try:
        allow_audio_mentions = bool(config['allow_audio_mentions']) if config else False
    except (IndexError, KeyError):
        allow_audio_mentions = False

    try:
        rate_limit = int(config['rate_limit_per_minute']) if config else 0
    except (IndexError, KeyError, TypeError, ValueError):
        rate_limit = 0
    
    return render_template('whatsapp_settings.html', 
                           has_wa_web_session=has_wa_web_session,
                           allowed_from=allowed_from,
                           allowed_to=allowed_to,
                           bot_enabled=bot_enabled,
                           allow_mentions=allow_mentions,
                           allow_audio_mentions=allow_audio_mentions,
                           rate_limit=rate_limit)

@views_bp.route('/settings/general')
def general_config_page():
    return render_template('general_config.html')

@views_bp.route('/settings/agent_behavior')
def agent_behavior_config_page():
    from utils.message_utils import get_default_worker
    default_worker = get_default_worker()
    agent_name = default_worker['worker_name'] if default_worker else ''
    return render_template('agent_behavior_config.html',
        agent_name=agent_name,
        system_prompt=get_config('SYSTEM_PROMPT', ''),
        require_at_prefix=get_config('REQUIRE_AT_PREFIX', 'true').lower() == 'true',
        ide_prompt=get_config('IDE_PROMPT', ''))

@views_bp.route('/settings/permissions')
def permissions_config_page():
    import platform
    os_type = platform.system()
    return render_template('permissions_config.html',
        os_type=os_type,
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
        perm_screenshot=get_config('PERM_SCREENSHOT', 'false').lower() == 'true',
        perm_web_search=get_config('PERM_WEB_SEARCH', 'false').lower() == 'true',
        perm_tool_creator=get_config('PERM_TOOL_CREATOR', 'false').lower() == 'true'
    )

@views_bp.route('/settings/advanced')
def advanced_settings_page():
    return render_template('advanced-settings.html',
        tool_creator_double_check=get_config('TOOL_CREATOR_DOUBLE_CHECK', 'false').lower() == 'true',
        whisper_model=get_config('WHISPER_MODEL', 'small')
    )

@views_bp.route('/settings/tools')
def tools_management_page():
    from tools import AVAILABLE_TOOLS
    import inspect
    from collections import defaultdict
    
    def get_tool_category(tool_func):
        mod_name = getattr(tool_func, '__module__', '')
        if 'self_developed' in mod_name or 'self-developed' in mod_name:
            return 'Self-Developed'
            
        name = tool_func.__name__
        if 'note' in name: return 'Notes'
        if 'calendar' in name: return 'Calendar'
        if 'contact' in name: return 'Contacts'
        if 'mail' in name: return 'Mail'
        if 'photo' in name or 'album' in name: return 'Photos'
        if 'reminder' in name: return 'Reminders'
        if 'icloud' in name: return 'iCloud'
        if 'browser' in name or 'webpage' in name: return 'Browser'
        if 'whatsapp' in name: return 'WhatsApp'
        if 'schedule' in name: return 'Scheduling'
        if 'search_web' in name: return 'Web Search'
        if 'screenshot' in name: return 'Screenshot'
        if name in ['read_file', 'write_file']: return 'File System'
        if 'command' in name: return 'Terminal'
        if 'memory' in name: return 'Memory'
        if 'tool' in name: return 'Tool Creator'
        return 'Other'
        
    sections = defaultdict(list)
    
    for tool_func in list(AVAILABLE_TOOLS):
        # Verify self-developed tool file still exists
        mod_name = getattr(tool_func, '__module__', '')
        if 'self_developed' in mod_name or 'self-developed' in mod_name:
            import sys, os
            if mod_name in sys.modules:
                module = sys.modules[mod_name]
                if hasattr(module, '__file__') and module.__file__:
                    if not os.path.exists(module.__file__):
                        AVAILABLE_TOOLS.remove(tool_func)
                        continue

        tool_name = tool_func.__name__
        # Default is true if not set
        is_enabled = get_config(f'TOOL_{tool_name.upper()}', 'true').lower() == 'true'
        
        doc = tool_func.__doc__ or "No description available."
        short_doc = doc.strip().split('\n')[0] # Get first line of docstring
        
        tool_length = len(tool_name)
        if tool_func.__doc__:
            tool_length += len(str(tool_func.__doc__))
            
        try:
            sig = inspect.signature(tool_func)
            for param_name, param in sig.parameters.items():
                tool_length += len(param_name)
                if param.annotation != inspect.Parameter.empty:
                    tool_length += len(str(param.annotation))
        except Exception:
            pass
            
        tool_tokens = (tool_length // 4) + 15
        
        sections[get_tool_category(tool_func)].append({
            'name': tool_name,
            'enabled': is_enabled,
            'description': short_doc,
            'tokens': tool_tokens
        })
        
    # Sort sections and their tools alphabetically (case-insensitive for keys), but put Self-Developed last
    sorted_sections = {}
    for category in sorted(sections.keys(), key=lambda k: k.lower()):
        if category != 'Self-Developed':
            sorted_sections[category] = sorted(sections[category], key=lambda x: x['name'])
            
    if 'Self-Developed' in sections:
        sorted_sections['Self-Developed'] = sorted(sections['Self-Developed'], key=lambda x: x['name'])
    
    return render_template('tools_management.html', sections=sorted_sections)

@views_bp.route('/settings/llm')
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
    
    llm_pref_1 = get_config('LLM_PREF_1', '')
    llm_pref_2 = get_config('LLM_PREF_2', '')
    llm_pref_3 = get_config('LLM_PREF_3', '')
    llm_pref_4 = get_config('LLM_PREF_4', '')
    llm_pref_5 = get_config('LLM_PREF_5', '')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM llm_config')
    models = cursor.fetchall()
    conn.close()

    model_list = []
    for model in models:
        m = dict(model)
        if m.get('api_key'):
            m['has_key'] = True
            m['api_key'] = '••••••••••••'
        else:
            m['has_key'] = False
            m['api_key'] = ''
            
        def is_true(val):
            return val in [1, '1', True, 'true', 'True']

        inputs = []
        if is_true(m.get('text_input')): inputs.append({'label': 'Text', 'bg': 'rgba(255, 255, 255, 0.08)', 'color': 'var(--text-main)'})
        if is_true(m.get('image_input')): inputs.append({'label': 'Image', 'bg': 'rgba(0, 150, 255, 0.12)', 'color': '#80c0ff'})
        if is_true(m.get('audio_input')): inputs.append({'label': 'Audio', 'bg': 'rgba(255, 100, 255, 0.12)', 'color': '#ff99ff'})
        if is_true(m.get('video_input')): inputs.append({'label': 'Video', 'bg': 'rgba(255, 150, 0, 0.12)', 'color': '#ffb84d'})
        if is_true(m.get('document_input')): inputs.append({'label': 'Doc', 'bg': 'rgba(255, 255, 100, 0.12)', 'color': '#ffff99'})
        m['inputs'] = inputs

        outputs = []
        if is_true(m.get('text_output')): outputs.append({'label': 'Text', 'bg': 'rgba(255, 255, 255, 0.08)', 'color': 'var(--text-main)'})
        if is_true(m.get('image_output')): outputs.append({'label': 'Image', 'bg': 'rgba(0, 150, 255, 0.12)', 'color': '#80c0ff'})
        if is_true(m.get('audio_output')): outputs.append({'label': 'Audio', 'bg': 'rgba(255, 100, 255, 0.12)', 'color': '#ff99ff'})
        if is_true(m.get('json_output')): outputs.append({'label': 'JSON', 'bg': 'rgba(150, 150, 255, 0.12)', 'color': '#b3b3ff'})
        if is_true(m.get('thinking')): outputs.append({'label': 'Thinking', 'bg': 'rgba(100, 255, 100, 0.12)', 'color': '#a3ffa3'})
        if is_true(m.get('function_calling')): outputs.append({'label': 'Tools', 'bg': 'rgba(255, 100, 100, 0.12)', 'color': '#ff9999'})
        m['outputs'] = outputs
        
        model_list.append(m)

    return render_template('llm_config.html', 
        current_model=current_model, has_api_key=has_api_key,
        qwen_model=qwen_model, has_qwen_key=has_qwen_key,
        deepseek_model=deepseek_model, has_deepseek_key=has_deepseek_key,
        openai_model=openai_model, has_openai_key=has_openai_key,
        anthropic_model=anthropic_model, has_anthropic_key=has_anthropic_key,
        llm_pref_1=llm_pref_1, llm_pref_2=llm_pref_2,
        llm_pref_3=llm_pref_3, llm_pref_4=llm_pref_4,
        llm_pref_5=llm_pref_5,
        models=model_list)

@views_bp.route('/workers')
def workers_page():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, worker_name, worker_model, worker_instructions, is_default, thinking_enabled FROM workers_config')
    workers = cursor.fetchall()
    
    cursor.execute('SELECT model_name, provider FROM llm_config WHERE enabled = 1')
    models = cursor.fetchall()
    conn.close()

    worker_list = [dict(w) for w in workers]
    model_list = [dict(m) for m in models]
    return render_template('workers.html', workers=worker_list, models=model_list)

@views_bp.route('/cron')
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

@views_bp.route('/dashboard')
def dashboard_page():
    from standard_prompts import apply_standard_rules
    from tools import get_permitted_tools
    from database import get_ide_config
    import inspect
    import datetime
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, instruction FROM user_memory')
    memories = cursor.fetchall()
    conn.close()
    
    memory_block = ""
    if memories:
        memory_block = "User Memory / Persistent Instructions:\n" + "\n".join(f"[ID: {r['id']}] {r['instruction']}" for r in memories)
        
    project_path = get_ide_config('CURRENT_PROJECT_PATH')
    if project_path:
        memory_block += f"\n\nIMPORTANT: You are currently operating in the workspace directory: {project_path}\n"
        
    
    from utils.message_utils import get_default_worker
    default_worker = get_default_worker()
    system_prompt = default_worker['worker_instructions'] if default_worker else ''
    default_name = default_worker['worker_name'] if default_worker else None
    full_system_prompt = apply_standard_rules(system_prompt, worker_name=default_name)
    full_system_prompt = f"{memory_block}\n{full_system_prompt}"
    system_tokens = len(full_system_prompt) // 4
    
    permitted_tools = get_permitted_tools()
    tools_length = 0
    json_overhead = len(permitted_tools) * 15 # Approximate JSON schema structure overhead per tool
    
    for t in permitted_tools:
        tools_length += len(t.__name__)
        if t.__doc__:
            tools_length += len(str(t.__doc__))
            
        try:
            sig = inspect.signature(t)
            for param_name, param in sig.parameters.items():
                tools_length += len(param_name)
                if param.annotation != inspect.Parameter.empty:
                    tools_length += len(str(param.annotation))
        except Exception:
            pass
            
    tools_tokens = (tools_length // 4) + json_overhead
    user_tokens = 50
    
    double_check_enabled = get_config('TOOL_CREATOR_DOUBLE_CHECK', 'false').lower() == 'true'
    # Adding ~500 tokens as a base input estimate for the double-check prompt (original code + user prompt)
    double_check_tokens = 500 if double_check_enabled else 0
    
    total_min = user_tokens + system_tokens + tools_tokens
    
    # Assume a ceiling of ~3000 tokens for long conversation history
    history_ceiling_tokens = 3000
    total_max = total_min + history_ceiling_tokens + double_check_tokens
    
    return render_template('dashboard.html', 
                           user_tokens=user_tokens,
                           system_tokens=system_tokens,
                           tools_tokens=tools_tokens,
                           total_min=total_min,
                           total_max=total_max,
                           double_check_tokens=double_check_tokens)
