import os
import shutil
import sqlite3
from datetime import datetime
from database import get_db, encrypt_value, DB_PATH


def backup_database():
    """
    Creates a timestamped backup copy of the active database file
    into the bin/backups/ directory. The filename follows the format:
    YYYY-MM-DD HH-MM-SS.db
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(project_root, 'bin', 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d %H-%M-%S')
    backup_filename = f"{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    # Resolve DB_PATH relative to project root if not absolute
    db_source = DB_PATH if os.path.isabs(DB_PATH) else os.path.join(project_root, DB_PATH)

    shutil.copy2(db_source, backup_path)
    return backup_path

def setup_app_config():
    """
    Populates the app_config table with default configuration values.
    Existing values for the targeted keys are deleted first.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        keys_to_clear = [
            'agent_name', 'USE_RECIPES_AS_TOOLS', 'AUTONOMOUS_MODE', 'DEFAULT_LLM_PROVIDER',
            'DEFAULT_LLM_MODEL', 'GEMINI_MODEL', 'QWEN_MODEL',
            'PERM_TERMINAL', 'PERM_PLAYWRIGHT', 'PERM_FS', 'PERM_WEB_SEARCH', 'PERM_TOOL_CREATOR',
            'MESSAGE_SLICE_SIZE_TOKENS'
        ]
        # Clear existing configs in scope
        cursor.execute(
            f"DELETE FROM app_config WHERE key IN ({','.join(['?'] * len(keys_to_clear))})",
            keys_to_clear
        )

        default_configs = [
            ('agent_name', 'Nano'),
            ('REQUIRE_AT_PREFIX', 'false'),
            ('USE_RECIPES_AS_TOOLS', 'false'),
            ('AUTONOMOUS_MODE', '1'),
            ('DEFAULT_LLM_PROVIDER', 'Google'),
            ('DEFAULT_LLM_MODEL', 'gemini-3.1-flash-lite'),
            ('GEMINI_MODEL', 'gemini-3.1-flash-lite'),
            ('QWEN_MODEL', 'qwen-plus'),
            ('PERM_TERMINAL', 'true'),
            ('PERM_PLAYWRIGHT', 'true'),
            ('PERM_FS', 'true'),
            ('PERM_WEB_SEARCH', 'true'),
            ('PERM_TOOL_CREATOR', 'true'),
            ('MESSAGE_SLICE_SIZE_TOKENS', '2000')
        ]
        for key, value in default_configs:
            cursor.execute('INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
    finally:
        conn.close()

def setup_ide_prompt():
    """
    Populates the ide_prompt configuration key inside the app_config table.
    The existing ide_prompt is deleted first.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Clear existing ide_prompt
        cursor.execute("DELETE FROM app_config WHERE key = 'ide_prompt'")

        default_prompt = (
            "You are an expert Senior Software Engineer and Architect operating as an interactive IDE Agent. "
            "Your goal is to assist with codebase exploration, refactoring, debugging, and feature implementation "
            "with absolute precision and zero technical debt.\n\n"
            "### 1. Two-Step Execution Workflow (Plan & Authorize)\n"
            "You must strictly adhere to a two-step cycle. You are forbidden from generating final code modifications "
            "or executing changes until the user explicitly approves your plan.\n\n"
            "- **Step 1: The Complete Plan:** Output a comprehensive, structured plan containing:\n"
            "  - **Analysis:** Root cause, requirements, and architecture context.\n"
            "  - **Proposed Changes:** Exact files, modules, or functions to be modified or created.\n"
            "  - **Implementation Steps:** Sequential, technical execution strategy.\n"
            "  - **Side Effects & Edge Cases:** Potential breaking changes, performance impacts, or test failures.\n"
            "  - **Awaiting Authorization:** Prompt the user for explicit confirmation to proceed and **stop execution immediately**.\n\n"
            "- **Step 2: Execution:** Only after receiving explicit user authorization, proceed to execute the approved plan.\n\n"
            "### 2. Code Generation & Modification Rules\n"
            "- **Precision Diffs:** Provide only the specific blocks of code that need to be changed or added. "
            "Avoid rewriting entire files. Never use placeholders like `// rest of code remains the same`.\n"
            "- **Architectural Alignment:** Adhere strictly to the existing codebase patterns, naming conventions, "
            "typing standards (strict type hints), and architectural boundaries.\n"
            "- **Defensive Programming:** Integrate robust error handling, validation, logging, and edge-case management.\n"
            "- **No Regressions:** Ensure modifications do not break existing test suites, API contracts, or performance constraints.\n\n"
            "### 3. Communication Protocol\n"
            "- Be direct, highly technical, and completely objective.\n"
            "- Omit conversational pleasantries, introductory fluff, and repetitive explanations.\n"
            "- Focus purely on actionable technical solutions and code clarity."
        )
        cursor.execute('''
            INSERT OR REPLACE INTO app_config (key, value)
            VALUES (?, ?)
        ''', ('ide_prompt', default_prompt))
        conn.commit()
    finally:
        conn.close()


def setup_ide_settings():
    """
    Populates the ide_settings table with default IDE workspace environment settings.
    Existing settings in scope are deleted first.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        settings_to_clear = ['theme', 'editor_font_size', 'sidebar_open', 'CURRENT_PROJECT_PATH']
        # Clear existing settings in scope
        cursor.execute(
            f"DELETE FROM ide_settings WHERE key IN ({','.join(['?'] * len(settings_to_clear))})",
            settings_to_clear
        )

        default_settings = [
            ('theme', 'dark'),
            ('editor_font_size', '14'),
            ('sidebar_open', 'true'),
            ('CURRENT_PROJECT_PATH', '/Users/juliosouto/projects/nanoworker')
        ]
        for key, value in default_settings:
            cursor.execute('INSERT OR REPLACE INTO ide_settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
    finally:
        conn.close()


def setup_llm_config():
    """
    Populates the llm_config table with standard LLM model specifications and definitions.
    All existing models in the table are deleted first.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Clear all existing LLM models
        cursor.execute("DELETE FROM llm_config")

        default_models = [
            ('gemini-3.1-flash-lite', 'Google', None, 1, 1, 1, 1, 1048576, 65536, 1, 1, 1, 1, 1, None, None, None, 1, 0, 0, 0, 0),
            ('gemini-3-flash-preview', 'Google', None, 1, 1, 1, 1, 1048576, 65536, 1, 1, 1, 1, 1, None, None, None, 1, 0, 0, 0, 0),
            ('gemini-3.5-flash', 'Google', None, 1, 1, 1, 1, 1048576, 65536, 1, 1, 1, 1, 1, None, None, None, 1, 0, 0, 0, 0),
            ('gemini-2.5-flash', 'Google', None, 1, 1, 1, 1, 1048576, 65536, 1, 1, 1, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('gemma-4-26b-a4b-it', 'Google', None, 1, 1, 0, 1, 262000, 16400, 1, 1, 0, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('gemma-4-31b-it', 'Google', None, 1, 1, 0, 1, 262000, 16400, 1, 1, 0, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('qwen-turbo', 'Qwen', None, 0, 1, 1, 1, 995000, 32000, 1, 0, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('qwen3.5-flash', 'Qwen', None, 0, 1, 1, 1, 991000, 983000, 1, 1, 0, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('qwen3.6-flash', 'Qwen', None, 0, 1, 1, 1, 991000, 983000, 1, 1, 0, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('gemini-2.5-flash-lite', 'Google', None, 1, 1, 1, 1, 1048576, 65536, 1, 1, 1, 1, 0, None, None, None, 1, 0, 0, 0, 0),
            ('openai/gpt-oss-20b', 'Groq', None, 1, 1, 1, 1, None, None, 1, 0, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('gpt-5-nano', 'OpenAI', None, 1, 1, 1, 1, None, None, 1, 1, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('ollama/llama3.1', 'Ollama', None, 1, 1, 1, 1, 128000, 8192, 1, 0, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('openrouter/openai/gpt-4o', 'OpenRouter', None, 1, 1, 1, 1, None, None, 1, 1, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('openrouter/anthropic/claude-3.5-sonnet', 'OpenRouter', None, 1, 1, 1, 1, None, None, 1, 1, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0),
            ('openrouter/meta-llama/llama-3.1-70b-instruct', 'OpenRouter', None, 1, 1, 1, 1, None, None, 1, 1, 0, 0, 0, None, None, None, 1, 0, 0, 0, 0)
        ]
        for model in default_models:
            cursor.execute('''
                INSERT INTO llm_config (
                    model_name, provider, api_key, enabled, json_output, thinking, function_calling,
                    context_window, max_output_tokens, text_input, image_input, audio_input,
                    video_input, document_input, rate_tpm, rate_rpm, rate_rpd,
                    text_output, image_output, audio_output, video_output, document_output
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', model)
        conn.commit()
    finally:
        conn.close()

def setup_agents():
    """
    Populates the agents table with standard default agent definitions.
    The default agent is deleted first if it exists.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Clear default agent in scope
        cursor.execute("DELETE FROM agents WHERE id = 'agent-1'")

        cursor.execute('''
            INSERT OR REPLACE INTO agents (id, name, description)
            VALUES (?, ?, ?)
        ''', ('agent-1', 'Default NanoWorker Agent', 'A simple agent for MVP testing'))
        conn.commit()
    finally:
        conn.close()

def setup_whatsapp_config():
    """
    Populates the whatsapp_config table with standard settings, targeting only the requested fields.
    Scope is limited to: bot_enabled, allow_mentions, rate_limit_per_minute, allow_audio_mentions.
    Old configurations for these specific fields are directly overwritten/cleared.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT COUNT(*) FROM whatsapp_config WHERE id = 1')
        exists = cursor.fetchone()[0] > 0
        if exists:
            # Overwrite only the scoped fields, leaving other fields intact
            cursor.execute('''
                UPDATE whatsapp_config
                SET bot_enabled = ?, allow_mentions = ?, rate_limit_per_minute = ?, allow_audio_mentions = ?
                WHERE id = 1
            ''', (1, 1, 6, 1))
        else:
            cursor.execute('''
                INSERT INTO whatsapp_config (
                    id, bot_enabled, allow_mentions, rate_limit_per_minute, allow_audio_mentions
                )
                VALUES (?, ?, ?, ?, ?)
            ''', (1, 1, 1, 6, 1))
        conn.commit()
    finally:
        conn.close()

def setup_workers_config():
    """
    Populates the workers_config table with standard worker configs matching active agents.
    All existing workers in the table are deleted first.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Clear all existing workers
        cursor.execute("DELETE FROM workers_config")

        default_workers = [
            (
                'Nano', 'gemini-3.1-flash-lite',
                'You are a helpful and precise assistant.',
                1, 0, 1
            )
        ]
        for worker in default_workers:
            cursor.execute('''
                INSERT INTO workers_config (
                    worker_name, worker_model, worker_instructions, is_default, thinking_enabled, tools_enabled
                )
                VALUES (?, ?, ?, ?, ?, ?)
            ''', worker)
        conn.commit()
    finally:
        conn.close()

def setup_tools_config():
    """
    Populates the tools_config table with default configuration values for all available tools.
    By default, all tools are enabled, but access from groups and direct messages by other users is disabled.
    """
    from database import get_db
    from tools import AVAILABLE_TOOLS
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Clear all existing configs
        cursor.execute("DELETE FROM tools_config")
        
        for tool in AVAILABLE_TOOLS:
            tool_name = getattr(tool, '__name__', str(tool))
            cursor.execute('''
                INSERT INTO tools_config (
                    tool_name, enabled, allow_others_from_group_msgs, allow_others_from_direct_msgs
                )
                VALUES (?, 1, 0, 0)
            ''', (tool_name,))
        conn.commit()
    finally:
        conn.close()
