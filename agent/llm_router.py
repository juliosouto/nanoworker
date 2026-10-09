"""
LLM routing logic: selects the correct provider based on database config,
and implements fallback across multiple models.
"""
import logging
import uuid

from agent.db_feedback import insert_feedback
from agent.stop_check import StopRequestedError
import agent.llm_providers as _providers

logger = logging.getLogger(__name__)

# Heuristic used across the project: 1 token ~= 4 chars.
_CHARS_PER_TOKEN = 4
# Safety margin reserved on top of the accounted input tokens.
_SAFE_MARGIN_TOKENS = 1024
# OpenRouter reserves this many output tokens by default when max_tokens is omitted
# (this is exactly the "32000 in the output" seen in context-limit errors).
_DEFAULT_OUTPUT_RESERVE = 32000


def _estimate_tokens(text) -> int:
    """Rough token estimate for a string (1 token ~= 4 chars, matching truncate_message)."""
    if not text:
        return 0
    return max(1, len(str(text)) // _CHARS_PER_TOKEN)


def _history_text(msg) -> str:
    """
    Defensively extracts text from a single history item.

    Supports both the Gemini-format types.Content objects (built by
    _build_history_from_db) and plain OpenAI-style dicts with 'content'.
    """
    if hasattr(msg, "parts"):
        return " ".join(
            getattr(p, "text", "") or "" for p in msg.parts if getattr(p, "text", None)
        )
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        return str(content) if content else ""
    return str(getattr(msg, "content", "") or "")


def _prune_history_to_fit(history, context_window, config_kwargs, content, max_output_tokens=None):
    """
    Trims old conversation history to fit within the model's context window.

    Uses the "Context Window" and "Max Output Tokens" configured for the model in
    the LLM models web UI (llm_config table). The current user message is NEVER
    trimmed; only the oldest messages are dropped until the estimated input fits.

    When context_window is unset (NULL/0), returns the history unchanged so the
    previous behavior is preserved.

    Returns:
        list: The (possibly trimmed) history, with order preserved.
    """
    try:
        context = int(context_window) if context_window else 0
    except (ValueError, TypeError):
        context = 0

    if context <= 0:
        return history

    # Reserve part of the context for the model output. When the user configured
    # "Max Output Tokens" for the model we use it; otherwise we mirror the output
    # reservation that API gateways (e.g. OpenRouter) apply by default (32000).
    try:
        reserve_output = int(max_output_tokens) if max_output_tokens else _DEFAULT_OUTPUT_RESERVE
    except (ValueError, TypeError):
        reserve_output = _DEFAULT_OUTPUT_RESERVE

    # Cost of the system prompt, the tools and the current user message.
    system_token = _estimate_tokens(config_kwargs.get("system_instruction", ""))
    tools_token = 0
    for tool in config_kwargs.get("tools", []) or []:
        tools_token += _estimate_tokens(getattr(tool, "__doc__", "") or "")

    current_token = _estimate_tokens(content)
    if isinstance(content, list):
        current_token = _estimate_tokens(" ".join(
            p.text if getattr(p, "text", None) else str(p) for p in content
        ))

    budget = (
        context
        - reserve_output
        - _SAFE_MARGIN_TOKENS
        - system_token
        - tools_token
        - current_token
    )

    oldest = 0  # number of oldest messages to drop
    used = 0
    for i in range(len(history) - 1, -1, -1):
        used += _estimate_tokens(_history_text(history[i]))
        if used > budget and i != len(history) - 1:
            oldest = i + 1
            break

    if oldest > 0:
        logger.info(
            f"[llm_router] Pruned {oldest} oldest message(s) to fit context "
            f"(budget {budget}, kept {len(history) - oldest}/{len(history)})."
        )
        return list(history[oldest:])

    return history


def route_llm_call(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, is_ide: bool, on_complete=None) -> str:
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
        on_complete (callable, optional): Callback for real-time messages.

    Returns:
        str: Response processed by the selected model.
    """
    table = "ide_messages_out" if is_ide else "messages_out"

    from database import get_db, decrypt_value
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT provider, api_key, thinking, context_window, max_output_tokens FROM llm_config WHERE model_name = ?", (model_name,))
    row = c.fetchone()
    conn.close()

    provider = None
    api_key = None
    model_thinking = False
    context_window = None
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
            context_window = row['context_window']
        except (KeyError, IndexError, TypeError):
            context_window = None
        try:
            max_output_tokens = row['max_output_tokens']
        except (KeyError, IndexError, TypeError):
            max_output_tokens = None

    local_kwargs = config_kwargs.copy()
    if not model_thinking:
        local_kwargs.pop('thinking_config', None)

    # Trim old history to the model's context window configured in the LLM models UI.
    # Only active when 'Context Window' is set; otherwise history is passed as-is.
    history = _prune_history_to_fit(history, context_window, local_kwargs, content, max_output_tokens or None)

    # NVIDIA is checked first (before the Qwen/OpenAI branches) because NIM hosts
    # models whose last path segment overlaps other providers' heuristics, e.g.
    # "nvidia/qwen/qwen3-next-80b-a3b-instruct" or "nvidia/openai/gpt-oss-120b".
    # Relying on the "provider" column (user-configured) is the source of truth;
    # "nvidia/" prefix fallback covers models not registered in llm_config.
    if provider == "nvidia" or model_name.lower().startswith("nvidia/"):
        return _providers.call_nvidia_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens, on_complete=on_complete)
    elif provider == "qwen" or model_name.lower().startswith("qwen"):
        return _providers.call_qwen_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, on_complete=on_complete)
    elif provider == "groq" or model_name.lower().startswith("groq/"):
        return _providers.call_groq_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens, on_complete=on_complete)
    elif provider == "openai" or model_name.lower().startswith("openai/"):
        return _providers.call_openai_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens, on_complete=on_complete)
    elif provider == "ollama" or model_name.lower().startswith("ollama/"):
        from database import get_config
        ollama_base_url = get_config("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return _providers.call_ollama_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, ollama_base_url, max_output_tokens, on_complete=on_complete)
    elif provider == "openrouter" or model_name.lower().startswith("openrouter/"):
        return _providers.call_openrouter_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens, on_complete=on_complete)
    else:
        return _providers.call_gemini_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, on_complete=on_complete)


def invoke_llm_with_fallback(history: list, config_kwargs: dict, content, models_to_try: list, cursor, session_id: str, message_in_id: str, is_ide: bool = False, on_complete=None) -> str:
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
        on_complete (callable, optional): Callback for real-time messages.

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
            response_text = route_llm_call(model_name, history, config_kwargs, content, cursor, session_id, message_in_id, is_ide, on_complete=on_complete)
            return response_text
        except StopRequestedError:
            # The user requested /stop while a retry was in flight: abort the
            # whole fallback chain instead of switching to the next model.
            raise
        except Exception as e:
            error_str = str(e)
            if i < len(models_to_try) - 1:
                continue
            else:
                raise e

    return "Error: All models failed."
