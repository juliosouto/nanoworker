"""
LLM routing logic: selects the correct provider based on database config,
and implements fallback across multiple models.
"""
import uuid

from agent.db_feedback import insert_feedback
import agent.llm_providers as _providers


def route_llm_call(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, is_ide: bool) -> str:
    """
    Routes the LLM call to the appropriate provider (Qwen, Groq, OpenAI, or Gemini)
    based on the configurations stored in the database for the requested model.

    Arguments:
        model_name (str): The name of the selected model.
        history (list): The conversation history.
        config_kwargs (dict): Configuration arguments for the LLM.
        content (any): Content of the message to be processed.
        cursor (sqlite3.Cursor): Database cursor for logging operations.
        session_id (str): Session identifier.
        message_in_id (str): Source message identifier.
        is_ide (bool): Flag indicating if the request originated from the IDE interface.

    Returns:
        str: Response processed by the selected model.
    """
    table = "ide_messages_out" if is_ide else "messages_out"

    from database import get_db, decrypt_value
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT provider, api_key, thinking, max_output_tokens FROM llm_config WHERE model_name = ?", (model_name,))
    row = c.fetchone()
    conn.close()

    provider = None
    api_key = None
    model_thinking = False
    max_output_tokens = None
    if row:
        try:
            provider = row['provider'].lower() if row['provider'] else None
        except (KeyError, IndexError, TypeError):
            provider = None
        try:
            if row['api_key']:
                api_key = decrypt_value(row['api_key'])
        except (KeyError, IndexError, TypeError):
            api_key = None
        try:
            model_thinking = bool(row['thinking'])
        except (KeyError, IndexError, TypeError):
            model_thinking = False
        try:
            max_output_tokens = row['max_output_tokens']
        except (KeyError, IndexError, TypeError):
            max_output_tokens = None

    local_kwargs = config_kwargs.copy()
    if not model_thinking:
        local_kwargs.pop('thinking_config', None)

    if provider == "qwen" or model_name.lower().startswith("qwen"):
        return _providers.call_qwen_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)
    elif provider == "groq" or model_name.lower().startswith("groq/"):
        return _providers.call_groq_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens)
    elif provider == "openai" or model_name.lower().startswith("openai/"):
        return _providers.call_openai_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens)
    elif provider == "ollama" or model_name.lower().startswith("ollama/"):
        from database import get_config
        ollama_base_url = get_config("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return _providers.call_ollama_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, ollama_base_url, max_output_tokens)
    else:
        return _providers.call_gemini_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)


def invoke_llm_with_fallback(history: list, config_kwargs: dict, content, models_to_try: list, cursor, session_id: str, message_in_id: str, is_ide: bool = False) -> str:
    """
    Iteratively tries to invoke a list of preferred models in case of failure.
    Logs feedback messages in the database informing model changes.

    Arguments:
        history (list): The conversation history.
        config_kwargs (dict): Configurations for generation.
        content (any): The content of the current user message.
        models_to_try (list): An ordered list of model names to try.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Associated input message ID.
        is_ide (bool): If true, sends feedback to ide_messages_out. Default is False.

    Returns:
        str: The response from the first successful model, or a general error message if all fail.
    """
    table = "ide_messages_out" if is_ide else "messages_out"

    cursor.execute(f'''
        SELECT content FROM {table} 
        WHERE session_id = ? 
        AND (content LIKE 'Using %' OR content LIKE 'Changing to %')
        ORDER BY rowid DESC LIMIT 1
    ''', (session_id,))
    last_feedback = cursor.fetchone()

    last_model = None
    if last_feedback:
        last_content = last_feedback['content']
        if last_content.startswith('Using '):
            last_model = last_content[6:]
        elif last_content.startswith('Changing to '):
            last_model = last_content[12:]

    first_model = models_to_try[0]
    if first_model != last_model:
        insert_feedback(cursor, table, session_id, message_in_id, f"Using {first_model}")

    for i, model_name in enumerate(models_to_try):
        if i > 0:
            insert_feedback(cursor, table, session_id, message_in_id, f"Changing to {model_name}")

        try:
            response_text = route_llm_call(model_name, history, config_kwargs, content, cursor, session_id, message_in_id, is_ide)
            return response_text
        except Exception as e:
            error_str = str(e)
            if i < len(models_to_try) - 1:
                continue
            else:
                raise e

    return "Error: All models failed."
