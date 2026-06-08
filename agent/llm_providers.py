"""
LLM provider-specific call functions.
Each function handles the API client setup and delegates to the appropriate execution loop.
"""
import time
import uuid

from google import genai
from google.genai import types

from agent.db_feedback import insert_feedback
from agent.openai_tools import execute_openai_compatible_llm
from database import get_config


def call_gemini_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, api_key: str = None, on_complete=None) -> str:
    """
    Makes a call to the Google Gemini API.
    Supports tool calls (function calling) with a manual loop
    to provide partial feedback to the user.

    Arguments:
        model_name (str): The name of the Gemini model to use.
        history (list): The conversation history in the API's expected format.
        config_kwargs (dict): Additional generation configurations.
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): Database cursor for logs and partial feedback.
        session_id (str): Chat session ID.
        message_in_id (str): ID of the input message being processed.
        table (str): Table name to insert feedback (e.g. messages_out).
        api_key (str, optional): Gemini API Key. Raises exception if not provided.

    Returns:
        str: The generated response text.
    """
    max_retries = 5
    if not api_key:
        raise ValueError("API Key for Gemini model is not set.")
    client = genai.Client(api_key=api_key)

    # Disable automatic function calling so we can handle it manually
    if "tools" in config_kwargs and config_kwargs["tools"]:
        config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

    chat = client.chats.create(
        model=model_name,
        history=history,
        config=types.GenerateContentConfig(**config_kwargs)
    )

    success = False
    response_text = None
    current_content = content

    # Tool execution loop (max 10 iterations)
    for iteration in range(10):
        response = None
        for attempt in range(max_retries):
            try:
                response = chat.send_message(current_content)
                break
            except Exception as e:
                error_str = str(e)
                if "503" in error_str:
                    feedback = f"⚠️ 503 Error on attempt {attempt + 1}/{max_retries}. Retrying..."
                    insert_feedback(cursor, table, session_id, message_in_id, feedback)
                    time.sleep(2)
                    continue
                elif any(err in error_str for err in ["400", "401", "403", "429"]) or getattr(e, 'code', 0) in [400, 401, 403, 429]:
                    raise e
                else:
                    raise e

        if not response:
            break  # All retries failed

        function_calls = getattr(response, 'function_calls', []) or []
        if not function_calls and hasattr(response, 'candidates') and response.candidates:
            for part in response.candidates[0].content.parts:
                if getattr(part, 'function_call', None):
                    function_calls.append(part.function_call)

        if not function_calls:
            response_text = response.text
            success = True
            break

        permitted_tools = config_kwargs.get("tools", [])
        tools_used = []
        tool_results = []
        function_responses = []

        for fc in function_calls:
            tool_name = fc.name
            args = dict(fc.args) if fc.args else {}

            # Log execution starting
            msg_start = f"⚙️ Executing local tool: {tool_name}..."
            insert_feedback(cursor, table, session_id, message_in_id, msg_start)

            # Execute Python function
            result = "Tool not found"
            for f in permitted_tools:
                if getattr(f, '__name__', '') == tool_name:
                    try:
                        result = f(**args)
                    except Exception as ex:
                        result = f"Error executing {tool_name}: {str(ex)}"
                    break

            if tool_name not in tools_used:
                tools_used.append(tool_name)
            tool_results.append(str(result))

            resp_dict = result if isinstance(result, dict) else {"result": result}
            function_responses.append(types.Part.from_function_response(
                name=tool_name,
                response=resp_dict
            ))

        # Log execution finished
        if tools_used:
            tools_str = ", ".join(tools_used)
            results_str = "\nResults:\n- " + "\n- ".join(tool_results)
            msg_end = f"⚙️ Executed tools: {tools_str}{results_str}"
            insert_feedback(cursor, table, session_id, message_in_id, msg_end)
            if on_complete and get_config("SHOW_TOOLS_RESULTS", "true").lower() == "true":
                try:
                    on_complete(msg_end)
                except Exception:
                    pass

        current_content = function_responses

    if success:
        return response_text or "Executed tool calls successfully."
    return "Error: Gemini model failed or exceeded maximum iterations."


def call_qwen_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, api_key: str = None, on_complete=None) -> str:
    """
    Makes a call to the OpenAI API compatible with Qwen models (DashScope).

    Arguments:
        model_name (str): The name of the Qwen model.
        history (list): The conversation history.
        config_kwargs (dict): Additional generation configurations (e.g. system_instruction).
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Input message ID.
        table (str): Output table name.
        api_key (str, optional): Qwen API Key. Raises exception if missing.

    Returns:
        str: The generated response text.
    """
    import openai
    if not api_key:
        raise ValueError("API Key for Qwen model is not set.")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, on_complete=on_complete)


def call_groq_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, api_key: str = None, max_output_tokens: int = None, on_complete=None) -> str:
    """
    Makes a call to the Groq API.

    Arguments:
        model_name (str): The name of the Groq model.
        history (list): The conversation history.
        config_kwargs (dict): Additional generation configurations (e.g. system_instruction).
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Input message ID.
        table (str): Output table name.
        api_key (str, optional): Groq API Key. Raises exception if missing.
        max_output_tokens (int, optional): Maximum limit for output tokens.

    Returns:
        str: The generated response text.
    """
    from groq import Groq
    if not api_key:
        raise ValueError("API Key for Groq model is not set.")

    client = Groq(api_key=api_key)
    limit_tokens = max_output_tokens if max_output_tokens else 1024
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens, on_complete=on_complete)


def call_openai_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, api_key: str = None, max_output_tokens: int = None, on_complete=None) -> str:
    """
    Makes a call to the OpenAI API.

    Arguments:
        model_name (str): The name of the OpenAI model.
        history (list): The conversation history.
        config_kwargs (dict): Additional generation configurations (e.g. system_instruction).
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Input message ID.
        table (str): Output table name.
        api_key (str, optional): OpenAI API Key. Raises exception if missing.
        max_output_tokens (int, optional): Maximum limit for output tokens.

    Returns:
        str: The generated response text.
    """
    import openai
    if not api_key:
        raise ValueError("API Key for OpenAI model is not set.")

    client = openai.OpenAI(api_key=api_key)
    limit_tokens = max_output_tokens if max_output_tokens else None
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens, on_complete=on_complete)


def call_ollama_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, base_url: str = "http://localhost:11434/v1", max_output_tokens: int = None, on_complete=None) -> str:
    """
    Makes a call to the Ollama API locally (OpenAI compatible).

    Arguments:
        model_name (str): The name of the Ollama model.
        history (list): The conversation history.
        config_kwargs (dict): Additional generation configurations.
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Input message ID.
        table (str): Output table name.
        base_url (str, optional): The base URL for the Ollama API. Defaults to localhost.
        max_output_tokens (int, optional): Maximum limit for output tokens.

    Returns:
        str: The generated response text.
    """
    import openai

    # Strip the "ollama/" prefix if it exists to pass the correct model name to Ollama
    actual_model_name = model_name[7:] if model_name.lower().startswith("ollama/") else model_name

    # We use a dummy API key because Ollama doesn't require one, but openai client does
    client = openai.OpenAI(api_key="ollama", base_url=base_url)
    limit_tokens = max_output_tokens if max_output_tokens else None
    return execute_openai_compatible_llm(client, actual_model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens, on_complete=on_complete)


def call_openrouter_llm(model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, api_key: str = None, max_output_tokens: int = None, on_complete=None) -> str:
    """
    Makes a call to the OpenRouter API.

    Arguments:
        model_name (str): The name of the OpenRouter model.
        history (list): The conversation history.
        config_kwargs (dict): Additional generation configurations (e.g. system_instruction).
        content (any): The content of the current user message.
        cursor (sqlite3.Cursor): The database cursor.
        session_id (str): Session ID.
        message_in_id (str): Input message ID.
        table (str): Output table name.
        api_key (str, optional): OpenRouter API Key. Raises exception if missing.
        max_output_tokens (int, optional): Maximum limit for output tokens.

    Returns:
        str: The generated response text.
    """
    import openai
    if not api_key:
        raise ValueError("API Key for OpenRouter model is not set.")

    # Strip the "openrouter/" prefix if it exists
    actual_model_name = model_name[11:] if model_name.lower().startswith("openrouter/") else model_name

    # OpenRouter requires default headers for ranking, passing them here
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/nanoworker", 
            "X-OpenRouter-Title": "NanoWorker"
        }
    )
    limit_tokens = max_output_tokens if max_output_tokens else None
    return execute_openai_compatible_llm(client, actual_model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens, on_complete=on_complete)
