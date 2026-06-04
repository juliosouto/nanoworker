import os
import time
import uuid

from dotenv import load_dotenv
from google import genai
from google.genai import types

import standard_prompts
from database import get_config, get_db
from tools import get_permitted_tools
from utils.session import current_session_id
from utils.message_utils import truncate_message, process_tools_for_llm

load_dotenv(override=True)

def convert_to_openai_tool(func) -> dict:
    """
    Converts a Python function into an OpenAI compatible tool schema.
    """
    import inspect
    name = func.__name__
    
    # Docstring parsing for description
    doc = func.__doc__ or ""
    description = doc.strip().split("\n\n")[0].strip() if doc else f"Executes function {name}"
    
    sig = inspect.signature(func)
    properties = {}
    required = []
    
    # Type map Python to JSON Schema
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object"
    }
    
    for param_name, param in sig.parameters.items():
        if param_name in ["self", "args", "kwargs"]:
            continue
            
        param_type = type_map.get(param.annotation, "string")
        
        # Simple extraction of parameter description from docstring if present
        param_desc = f"Parameter {param_name}"
        if doc:
            for line in doc.split("\n"):
                if f"{param_name}:" in line or f"{param_name} " in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        param_desc = parts[1].strip()
                        break
                        
        properties[param_name] = {
            "type": param_type,
            "description": param_desc
        }
        
        if param.default == inspect.Parameter.empty:
            required.append(param_name)
            
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description[:1024],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }

def execute_openai_compatible_llm(client, model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, limit_tokens: int = None) -> str:
    """
    Unified recursive executor loop for OpenAI-compatible LLM providers that dynamically
    converts tools and executes python function calls.
    """
    # 1. Map history and content to OpenAI format
    messages = []
    if "system_instruction" in config_kwargs:
        messages.append({"role": "system", "content": config_kwargs["system_instruction"]})
        
    for msg in history:
        role = "user" if msg.role == "user" else "assistant"
        text_parts = [p.text for p in msg.parts if getattr(p, 'text', None)]
        messages.append({"role": role, "content": " ".join(text_parts)})
        
    if isinstance(content, list):
        text_parts = []
        for p in content:
            if isinstance(p, str):
                text_parts.append(p)
            elif getattr(p, 'text', None):
                text_parts.append(p.text)
    else:
        text_parts = [content]
    messages.append({"role": "user", "content": " ".join([t for t in text_parts if t])})
    
    # 2. Convert raw python functions into OpenAI tool schemas
    permitted_tools = config_kwargs.get("tools", [])
    openai_tools = [convert_to_openai_tool(f) for f in permitted_tools] if permitted_tools else None
    
    # Normalize model name for reasoning detection
    model_lower = model_name.lower()
    model_base = model_lower.split("/")[-1] if "/" in model_lower else model_lower
    is_reasoning = model_base.startswith("o1") or model_base.startswith("o3") or "nano" in model_base
    
    # 3. Tool execution loop (max 10 iterations)
    for iteration in range(10):
        call_args = {
            "model": model_name,
            "messages": messages,
        }
        if openai_tools:
            call_args["tools"] = openai_tools
            
        if not is_reasoning:
            call_args["temperature"] = 1.0
            if limit_tokens:
                call_args["max_tokens"] = limit_tokens
        else:
            if limit_tokens:
                call_args["max_completion_tokens"] = limit_tokens
                
        try:
            response = client.chat.completions.create(**call_args)
        except Exception as e:
            err_msg = str(e).lower()
            if "max_tokens" in err_msg or "unsupported" in err_msg or "parameter" in err_msg:
                fallback_args = {
                    "model": model_name,
                    "messages": messages,
                }
                if openai_tools:
                    fallback_args["tools"] = openai_tools
                if limit_tokens:
                    fallback_args["max_completion_tokens"] = limit_tokens
                response = client.chat.completions.create(**fallback_args)
            else:
                raise e
                
        message = response.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)
        
        if not tool_calls:
            # We reached the final text answer, return it
            return message.content or ""
            
        # We have tool calls!
        # A. Append assistant message with tool calls to standard OpenAI history
        serialized_tool_calls = []
        for tc in tool_calls:
            serialized_tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": serialized_tool_calls
        })
        
        # B. Execute the tools in Python and log feedback in the output table
        tools_used = []
        tool_results = []
        for tc in tool_calls:
            tool_name = tc.function.name
            arguments_str = tc.function.arguments
            
            import json
            try:
                args = json.loads(arguments_str) if arguments_str else {}
            except Exception:
                args = {}
                
            # Log execution starting
            feedback_msg = f"⚙️ Executing local tool: {tool_name}..."
            cursor.execute(f'''
                INSERT INTO {table} (id, session_id, in_reply_to, content)
                VALUES (?, ?, ?, ?)
            ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback_msg))
            cursor.connection.commit()
            
            # Execute Python function
            result = "Tool not found"
            for f in permitted_tools:
                if f.__name__ == tool_name:
                    try:
                        result = f(**args)
                    except Exception as ex:
                        result = f"Error executing {tool_name}: {str(ex)}"
                    break
                    
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            tool_results.append(str(result))
            
            # Append tool response message to OpenAI history
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tool_name,
                "content": str(result)
            })
            
        # Log execution finished
        if tools_used:
            tools_str = ", ".join(tools_used)
            results_str = "\n\nResults:\n- " + "\n- ".join([r[:500] + '...' if len(r) > 500 else r for r in tool_results])
            feedback_done = f"⚙️ Executed tools: {tools_str}{results_str}"
            cursor.execute(f'''
                INSERT INTO {table} (id, session_id, in_reply_to, content)
                VALUES (?, ?, ?, ?)
            ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback_done))
            cursor.connection.commit()
            
    return "Error: Tool execution loop exceeded maximum iterations."

def call_gemini_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None) -> str:
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
                    cursor.execute(f'''
                        INSERT INTO {table} (id, session_id, in_reply_to, content)
                        VALUES (?, ?, ?, ?)
                    ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback))
                    cursor.connection.commit()
                    time.sleep(2)
                    continue
                elif any(err in error_str for err in ["400", "401", "403", "429"]) or getattr(e, 'code', 0) in [400, 401, 403, 429]:
                    raise e
                else:
                    raise e
                    
        if not response:
            break # All retries failed
            
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
            feedback_msg = f"⚙️ Executing local tool: {tool_name}..."
            cursor.execute(f'''
                INSERT INTO {table} (id, session_id, in_reply_to, content)
                VALUES (?, ?, ?, ?)
            ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback_msg))
            cursor.connection.commit()
            
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
            results_str = "\n\nResults:\n- " + "\n- ".join([r[:500] + '...' if len(r) > 500 else r for r in tool_results])
            feedback_done = f"⚙️ Executed tools: {tools_str}{results_str}"
            cursor.execute(f'''
                INSERT INTO {table} (id, session_id, in_reply_to, content)
                VALUES (?, ?, ?, ?)
            ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback_done))
            cursor.connection.commit()
            
        current_content = function_responses
                
    if success:
        return response_text or "Executed tool calls successfully."
    return "Error: Gemini model failed or exceeded maximum iterations."

def call_qwen_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None) -> str:
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
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table)

def call_groq_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None, max_output_tokens: int = None) -> str:
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
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens)

def call_openai_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None, max_output_tokens: int = None) -> str:
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
    return execute_openai_compatible_llm(client, model_name, history, config_kwargs, content, cursor, session_id, message_in_id, table, limit_tokens)

def route_llm_call(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, is_ide: bool) -> str:
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
        return call_qwen_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)
    elif provider == "groq" or model_name.lower().startswith("groq/"):
        return call_groq_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens)
    elif provider == "openai" or model_name.lower().startswith("openai/"):
        return call_openai_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key, max_output_tokens)
    else:
        return call_gemini_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)

def invoke_llm_with_fallback(history: list, config_kwargs: dict, content: any, models_to_try: list, cursor: any, session_id: str, message_in_id: str, is_ide: bool = False) -> str:
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
        cursor.execute(f'''
            INSERT INTO {table} (id, session_id, in_reply_to, content)
            VALUES (?, ?, ?, ?)
        ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, f"Using {first_model}"))
        cursor.connection.commit()

    for i, model_name in enumerate(models_to_try):
        if i > 0:
            cursor.execute(f'''
                INSERT INTO {table} (id, session_id, in_reply_to, content)
                VALUES (?, ?, ?, ?)
            ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, f"Changing to {model_name}"))
            cursor.connection.commit()
            
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

def execute_autonomous_loop(history, config_kwargs, initial_content, models_to_try, cursor, session_id, message_in_id, is_ide, on_complete=None):
    from database import get_config
    import json
    import re
    from google.genai import types

    try:
        autonomous_limit = int(get_config("AUTONOMOUS_MODE", "1"))
    except:
        autonomous_limit = 1
    if autonomous_limit < 1:
        autonomous_limit = 1
    elif autonomous_limit > 20:
        autonomous_limit = 20

    current_send_content = list(initial_content) if isinstance(initial_content, list) else [initial_content]
    final_response = ""

    for iteration in range(autonomous_limit):
        mock_response_raw = invoke_llm_with_fallback(history, config_kwargs, current_send_content, models_to_try, cursor, session_id, message_in_id, is_ide=is_ide)
        
        parsed_json = None
        raw_text = mock_response_raw.strip()
        
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
            
        try:
            parsed_json = json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                try:
                    parsed_json = json.loads(match.group(0))
                except:
                    pass
        
        if parsed_json and isinstance(parsed_json, dict) and "llm_response" in parsed_json and "is_the_user_request_completely_satisfied" in parsed_json:
            final_response = parsed_json["llm_response"]
            is_satisfied = parsed_json.get("is_the_user_request_completely_satisfied")
            user_prompt_val = parsed_json.get("user_prompt", "")
            
            if is_satisfied is True:
                break
            else:
                if iteration < autonomous_limit - 1:
                    feedback_text = f"Your response does not completely answer the user's prompt. Try a different approach or tool.\n{{\n  \"user_prompt\": {json.dumps(user_prompt_val)},\n  \"llm_response\": {json.dumps(final_response)},\n  \"is_the_user_request_completely_satisfied\": null\n}}\nPlease try again."
                    
                    import uuid
                    table = "ide_messages_out" if is_ide else "messages_out"
                    user_feedback_msg = f"🔄 Agent reflecting (Iteration {iteration + 1}/{autonomous_limit}): The request is not completely satisfied yet. Continuing..."
                    try:
                        cursor.execute(f'''
                            INSERT INTO {table} (id, session_id, in_reply_to, content)
                            VALUES (?, ?, ?, ?)
                        ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, user_feedback_msg))
                        cursor.connection.commit()
                    except:
                        pass
                    
                    if on_complete:
                        try:
                            on_complete(user_feedback_msg)
                        except Exception as e:
                            print(f"Failed to call on_complete: {e}")
                    
                    parts = []
                    for p in current_send_content:
                        if isinstance(p, str):
                            parts.append(types.Part.from_text(text=p))
                        else:
                            parts.append(p)
                    history.append(types.Content(role="user", parts=parts))
                    history.append(types.Content(role="model", parts=[types.Part.from_text(text=mock_response_raw)]))
                    current_send_content = [types.Part.from_text(text=feedback_text)]
                else:
                    break
        else:
            final_response = mock_response_raw
            break
            
    return final_response

def process_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent, providing it with tools and conversation history.
    """
    original_content = content
    # Wait a bit to debounce multiple rapid messages (like multiple images from WhatsApp)
    time.sleep(2)

    conn = get_db()
    cursor = conn.cursor()

    # Check if a newer message arrived while we slept
    cursor.execute('SELECT id FROM messages_in WHERE session_id = ? AND rowid > (SELECT rowid FROM messages_in WHERE id = ?) LIMIT 1', (session_id, message_in_id))
    newer = cursor.fetchone()
    if newer:
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
        conn.close()
        return message_in_id, "Skipped to allow newer message to process batch."

    # Mark as processed
    cursor.execute('UPDATE messages_in SET processed = 1 WHERE id = ?', (message_in_id,))
    conn.commit()
    
    # Set the current session context for tools
    current_session_id.set(session_id)

    # Fetch session's channel_id to determine if it is a WhatsApp group
    cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
    session_row = cursor.fetchone()
    is_wa_group = False
    is_wa_private = False
    if session_row:
        channel_id = session_row['channel_id']
        if channel_id.startswith('wa_web:') or channel_id.startswith('whatsapp:'):
            clean_channel = channel_id.replace('wa_web:', '').replace('whatsapp:', '')
            if '-' in clean_channel or clean_channel.startswith('120363'):
                is_wa_group = True
            else:
                is_wa_private = True
    
    # Fetch history
    cursor.execute('''
        SELECT 'user' as role, content, image_base64, file_mime_type, file_name, created_at, gemini_file_uri, sender_id 
        FROM messages_in 
        WHERE session_id = ? AND id != ?
        
        UNION ALL
        
        SELECT 'model' as role, content, NULL as image_base64, NULL as file_mime_type, NULL as file_name, created_at, NULL as gemini_file_uri, NULL as sender_id 
        FROM messages_out 
        WHERE session_id = ?
        
        ORDER BY created_at ASC
    ''', (session_id, message_in_id, session_id))
    
    rows = cursor.fetchall()
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        if role == 'user':
            if is_wa_group:
                msg_content = truncate_message(msg_content, 1000)
            if row['sender_id']:
                msg_content = f"[Message from: {row['sender_id']}]\n{msg_content}"
        parts = [types.Part.from_text(text=msg_content)]
        if row['image_base64']:
            from utils.image_utils import build_gemini_part
            mime_type = row['file_mime_type'] or "image/jpeg"
            part = build_gemini_part(row['image_base64'], mime_type, row['gemini_file_uri'])
            if part:
                parts.insert(0, part)
                if row['image_base64'].startswith('path:'):
                    parts.insert(1, types.Part.from_text(text=f"[Attached Document File Path: {row['image_base64'][5:]}]"))
        
        if history and history[-1].role == role:
            history[-1].parts.extend(parts)
        else:
            history.append(
                types.Content(role=role, parts=parts)
            )

    # Get current message info
    cursor.execute('SELECT image_base64, file_mime_type, file_name, gemini_file_uri, sender_id FROM messages_in WHERE id = ?', (message_in_id,))
    current_msg = cursor.fetchone()
    current_image_base64 = current_msg['image_base64'] if current_msg else None
    current_gemini_uri = current_msg['gemini_file_uri'] if current_msg else None
    current_sender_id = current_msg['sender_id'] if current_msg else None
    
    # Ensure client is available for fallback handling
    client = None

    from utils.message_utils import resolve_worker_from_content, clean_mention
    worker = resolve_worker_from_content(original_content)
    
    # Clean worker mention from content
    content = clean_mention(original_content)

    if is_wa_group:
        content = truncate_message(content, 1000)

    if current_sender_id:
        content = f"[Message from: {current_sender_id}]\n{content}"
    send_content = [content]
    if current_image_base64:
        from utils.image_utils import upload_and_build_gemini_part
        mime_type = current_msg['file_mime_type'] or "image/jpeg"
        part, new_uri = upload_and_build_gemini_part(client, current_image_base64, mime_type, current_gemini_uri)
        if part:
            send_content.insert(0, part)
            if current_image_base64.startswith('path:'):
                send_content.insert(1, f"[Attached Document File Path: {current_image_base64[5:]}]")
        if new_uri:
            cursor.execute("UPDATE messages_in SET gemini_file_uri = ? WHERE id = ?", (new_uri, message_in_id))
            conn.commit()

    if history and history[-1].role == 'user':
        last_user = history.pop()
        send_content = last_user.parts + send_content

    models_to_try = []
    if worker and worker.get('worker_model'):
        models_to_try = [worker['worker_model']]
    else:
        preferences = [get_config(f"LLM_PREF_{i}") for i in range(1, 6)]
        models_to_try = [m for m in preferences if m and m.strip()]
        if not models_to_try:
            models_to_try = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]
    
    try:
        tools_enabled = bool(worker.get('tools_enabled', 1)) if worker else True

        # Determine if the sender is the bot admin (the logged-in number)
        is_admin = False
        if current_sender_id:
            try:
                import requests
                res = requests.get('http://127.0.0.1:3000/me', timeout=2)
                if res.status_code == 200:
                    data = res.json()
                    bot_number = str(data.get('number', ''))
                    lid_number = str(data.get('lid_number', ''))
                    clean_sender = str(current_sender_id).split('@')[0]
                    if (bot_number and clean_sender == bot_number) or (lid_number and clean_sender == lid_number):
                        is_admin = True
            except Exception:
                pass

        include_tool_rules = tools_enabled

        system_prompt = ""
        if worker and worker.get('worker_instructions'):
            system_prompt = worker['worker_instructions']
        else:
            system_prompt = ""
        
        cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
        session_row = cursor.fetchone()
        if session_row:
            channel_id = session_row['channel_id']
            if channel_id.startswith('whatsapp:') or channel_id.startswith('wa_web:'):
                if include_tool_rules:
                    system_prompt = f"This message comes from WhatsApp. To reply to the current conversation, simply output your text directly. Do NOT use the send_whatsapp_message tool for standard replies. The system will automatically forward your text to the chat. However, if you need to send an image or file (like a screenshot), you MUST use the send_whatsapp_file tool (with phone_number='self').\n\n{system_prompt}"
                else:
                    system_prompt = f"This message comes from WhatsApp. To reply to the current conversation, simply output your text directly. The system will automatically forward your text to the chat.\n\n{system_prompt}"
            elif channel_id.startswith('web-chat'):
                system_prompt = f"This message comes from the web chat (HTML). You must reply via the web chat.\n\n{system_prompt}"
        thinking_enabled = bool(worker.get('thinking_enabled', 0)) if worker else False
            
        from database import get_ide_config
        project_path = get_ide_config('CURRENT_PROJECT_PATH')
        if project_path:
            system_prompt = f"IMPORTANT: You are currently operating in the workspace directory: {project_path}\nYou MUST use this absolute path as the base directory for all file operations (reading, writing, searching) unless the user specifies otherwise.\n\n{system_prompt}"
        
        # Fetch and inject user memory instructions
        try:
            cursor.execute('SELECT id, instruction FROM user_memory')
            memories = cursor.fetchall()
            if memories:
                memory_block = "User Memory / Persistent Instructions:\n" + "\n".join(f"[ID: {r['id']}] {r['instruction']}" for r in memories)
                if system_prompt:
                    system_prompt = f"{memory_block}\n\n{system_prompt}"
                else:
                    system_prompt = memory_block
        except Exception as e:
            import logging
            logging.error(f"Error fetching user memory: {e}")

        config_kwargs = {
            "temperature": 0.0,
        }
        if tools_enabled:
            config_kwargs["tools"] = process_tools_for_llm(get_permitted_tools(is_admin=is_admin, is_group=is_wa_group, is_direct=is_wa_private))
        
        worker_name = worker['worker_name'] if worker else None
        system_prompt = standard_prompts.apply_standard_rules(system_prompt, worker_name=worker_name, include_tool_rules=include_tool_rules)
        
        if current_image_base64:
            system_prompt = standard_prompts.apply_image_document_rules(system_prompt)
        
        json_schema_prompt = """
You MUST output your final response as a valid JSON object matching exactly this schema:
{
  "user_prompt": "<the user's original request>",
  "llm_response": "<your complete response addressing the request>",
  "is_the_user_request_completely_satisfied": <boolean>
}
Do not include any markdown formatting like ```json, just the raw JSON object.
"""
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{json_schema_prompt}"
        else:
            system_prompt = json_schema_prompt

        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        
        if thinking_enabled:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)
        
        mock_response = execute_autonomous_loop(history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=on_complete)
        
    except Exception as e:
        error_str = str(e)
        if "403" in error_str and "PERMISSION_DENIED" in error_str:
            try:
                cursor.execute('UPDATE messages_in SET gemini_file_uri = NULL WHERE session_id = ?', (session_id,))
                conn.commit()
            except Exception:
                pass
            mock_response = "⚠️ A permission error occurred with old history files (possible API Key change or expired file). The file cache for this session was cleared automatically to resolve the issue. Please resend your message to proceed!"
        else:
            mock_response = f"Error calling LLM API: {error_str}"
    
    # Write to messages_out safely
    message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    try:
        cursor.execute('''
            INSERT INTO messages_out (id, session_id, in_reply_to, content)
            VALUES (?, ?, ?, ?)
        ''', (message_out_id, session_id, message_in_id, mock_response))
        
        cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
        conn.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to save final response to DB: {e}")
    finally:
        try:
            conn.close()
        except:
            pass
    
    if on_complete:
        try:
            on_complete(mock_response)
        except Exception as e:
            import logging
            logging.error(f"on_complete callback failed: {e}")
    
    return message_out_id, mock_response


def process_ide_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent for IDE messages, using ide_messages_in/out tables.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('UPDATE ide_messages_in SET processed = 1 WHERE id = ?', (message_in_id,))
    conn.commit()

    # Set the current session context for tools
    current_session_id.set(session_id)

    cursor.execute('''
        SELECT 'user' as role, content, created_at 
        FROM ide_messages_in 
        WHERE session_id = ? AND id != ?
        
        UNION ALL
        
        SELECT 'model' as role, content, created_at 
        FROM ide_messages_out 
        WHERE session_id = ?
        
        ORDER BY created_at ASC
    ''', (session_id, message_in_id, session_id))

    rows = cursor.fetchall()
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg_content)])
        )

    preferences = [get_config(f"LLM_PREF_{i}") for i in range(1, 6)]
    models_to_try = [m for m in preferences if m and m.strip()]
    if not models_to_try:
        models_to_try = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]

    try:
        system_prompt = get_config("IDE_PROMPT", "")
        
        from database import get_ide_config
        project_path = get_ide_config('CURRENT_PROJECT_PATH')
        if project_path:
            system_prompt = f"IMPORTANT: You are currently operating in the workspace directory: {project_path}\nYou MUST use this absolute path as the base directory for all file operations (reading, writing, searching) unless the user specifies otherwise.\n\n{system_prompt}"

        thinking_enabled = get_config("THINKING_ENABLED", "false").lower() == "true"

        # Fetch and inject user memory instructions
        try:
            cursor.execute('SELECT id, instruction FROM user_memory')
            memories = cursor.fetchall()
            if memories:
                memory_block = "User Memory / Persistent Instructions:\n" + "\n".join(f"[ID: {r['id']}] {r['instruction']}" for r in memories)
                if system_prompt:
                    system_prompt = f"{memory_block}\n\n{system_prompt}"
                else:
                    system_prompt = memory_block
        except Exception as e:
            import logging
            logging.error(f"Error fetching user memory: {e}")

        config_kwargs = {
            "tools": process_tools_for_llm(get_permitted_tools()),
            "temperature": 0.0,
        }

        system_prompt = standard_prompts.apply_standard_rules(system_prompt)

        json_schema_prompt = """
You MUST output your final response as a valid JSON object matching exactly this schema:
{
  "user_prompt": "<the user's original request>",
  "llm_response": "<your complete response addressing the request>",
  "is_the_user_request_completely_satisfied": <boolean>
}
Do not include any markdown formatting like ```json, just the raw JSON object.
"""
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{json_schema_prompt}"
        else:
            system_prompt = json_schema_prompt

        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        if thinking_enabled:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)

        mock_response = execute_autonomous_loop(history, config_kwargs, content, models_to_try, cursor, session_id, message_in_id, is_ide=True)

    except Exception as e:
        mock_response = f"Error calling LLM API: {str(e)}"

    message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    cursor.execute('''
        INSERT INTO ide_messages_out (id, session_id, in_reply_to, content)
        VALUES (?, ?, ?, ?)
    ''', (message_out_id, session_id, message_in_id, mock_response))

    cursor.execute('UPDATE ide_messages_in SET processed = 2 WHERE id = ?', (message_in_id,))

    conn.commit()
    conn.close()

    if on_complete:
        try:
            on_complete(mock_response)
        except Exception as e:
            import logging
            logging.error(f"on_complete callback failed: {e}")

    return message_out_id, mock_response
