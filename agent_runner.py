import uuid
import os
from database import get_config
import time
from database import get_db
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tools import AVAILABLE_TOOLS
from tools.browser import current_session_id

load_dotenv(override=True)

def invoke_llm_with_fallback(client, history, config_kwargs, content, models_to_try, cursor, session_id, message_in_id, is_ide=False):
    max_retries = 5
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
            
        chat = client.chats.create(
            model=model_name,
            history=history,
            config=types.GenerateContentConfig(**config_kwargs)
        )
        
        success = False
        response_text = None
        for attempt in range(max_retries):
            try:
                response = chat.send_message(content)
                response_text = response.text
                if not response_text:
                    response_text = "Executed tool calls successfully."
                success = True
                break
            except Exception as e:
                error_str = str(e)
                if "503" in error_str:
                    feedback = f"⚠️ Erro 503 na tentativa {attempt + 1}/5. Tentando novamente..."
                    cursor.execute(f'''
                        INSERT INTO {table} (id, session_id, in_reply_to, content)
                        VALUES (?, ?, ?, ?)
                    ''', (f"msg-out-{uuid.uuid4().hex[:8]}", session_id, message_in_id, feedback))
                    cursor.connection.commit()
                    time.sleep(2)
                    continue
                elif any(err in error_str for err in ["400", "401", "403", "429"]) or getattr(e, 'code', 0) in [400, 401, 403, 429]:
                    if i < len(models_to_try) - 1:
                        break
                    else:
                        raise e
                else:
                    raise e
                    
        if success:
            return response_text
            
    return "Error: All models failed."

def process_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent, providing it with tools and conversation history.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Mark as processed
    cursor.execute('UPDATE messages_in SET processed = 1 WHERE id = ?', (message_in_id,))
    conn.commit()
    
    # Set the current session context for tools
    current_session_id.set(session_id)
    
    # Fetch history
    cursor.execute('''
        SELECT 'user' as role, content, image_base64, file_mime_type, file_name, created_at, gemini_file_uri 
        FROM messages_in 
        WHERE session_id = ? AND id != ?
        
        UNION ALL
        
        SELECT 'model' as role, content, NULL as image_base64, NULL as file_mime_type, NULL as file_name, created_at, NULL as gemini_file_uri 
        FROM messages_out 
        WHERE session_id = ?
        
        ORDER BY created_at ASC
    ''', (session_id, message_in_id, session_id))
    
    rows = cursor.fetchall()
    history = []
    for row in rows:
        role = row['role']
        msg_content = row['content']
        parts = [types.Part.from_text(text=msg_content)]
        if row['image_base64']:
            mime_type = row['file_mime_type'] or "image/jpeg"
            if row['gemini_file_uri']:
                parts.insert(0, types.Part.from_uri(file_uri=row['gemini_file_uri'], mime_type=mime_type))
            elif row['image_base64'].startswith('uri:'):
                file_uri = row['image_base64'][4:]
                parts.insert(0, types.Part.from_uri(file_uri=file_uri, mime_type=mime_type))
            elif row['image_base64'].startswith('path:'):
                file_path = row['image_base64'][5:]
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        img_data = f.read()
                    parts.insert(0, types.Part.from_bytes(data=img_data, mime_type=mime_type))
            else:
                import base64
                img_data = base64.b64decode(row['image_base64'])
                parts.insert(0, types.Part.from_bytes(data=img_data, mime_type=mime_type))
        
        history.append(
            types.Content(role=role, parts=parts)
        )

    # Get current message image
    cursor.execute('SELECT image_base64, file_mime_type, file_name, gemini_file_uri FROM messages_in WHERE id = ?', (message_in_id,))
    current_msg = cursor.fetchone()
    current_image_base64 = current_msg['image_base64'] if current_msg else None
    current_gemini_uri = current_msg['gemini_file_uri'] if current_msg else None
    
    # Generate response using Gemini API
    api_key = get_config("GEMINI_API_KEY")
    client = None
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
        except Exception:
            pass

    send_content = [content]
    if current_image_base64:
        mime_type = current_msg['file_mime_type'] or "image/jpeg"
        if current_gemini_uri:
            send_content.insert(0, types.Part.from_uri(file_uri=current_gemini_uri, mime_type=mime_type))
        elif current_image_base64.startswith('uri:'):
            file_uri = current_image_base64[4:]
            send_content.insert(0, types.Part.from_uri(file_uri=file_uri, mime_type=mime_type))
        elif current_image_base64.startswith('path:'):
            file_path = current_image_base64[5:]
            if os.path.exists(file_path):
                if client:
                    try:
                        uploaded_file = client.files.upload(file=file_path, config={"mime_type": mime_type})
                        
                        import time
                        # Poll until processing is complete
                        while uploaded_file.state.name == "PROCESSING":
                            time.sleep(2)
                            uploaded_file = client.files.get(name=uploaded_file.name)
                            
                        if uploaded_file.state.name == "FAILED":
                            raise ValueError("Gemini failed to process the uploaded file.")
                            
                        send_content.insert(0, types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type))
                        # Save the URI in the database so we don't upload again!
                        cursor.execute("UPDATE messages_in SET gemini_file_uri = ? WHERE id = ?", (uploaded_file.uri, message_in_id))
                        conn.commit()
                    except Exception as e:
                        import logging
                        logging.error(f"Failed to upload file to Gemini: {e}")
                        # Fallback to from_bytes if upload fails (might work for images)
                        with open(file_path, "rb") as f:
                            img_data = f.read()
                        send_content.insert(0, types.Part.from_bytes(data=img_data, mime_type=mime_type))
                else:
                    with open(file_path, "rb") as f:
                        img_data = f.read()
                    send_content.insert(0, types.Part.from_bytes(data=img_data, mime_type=mime_type))
        else:
            import base64
            img_data = base64.b64decode(current_image_base64)
            send_content.insert(0, types.Part.from_bytes(data=img_data, mime_type=mime_type))

    preferences = [os.environ.get(f"LLM_PREF_{i}") for i in range(1, 6)]
    models_to_try = [m for m in preferences if m and m.strip()]
    if not models_to_try:
        models_to_try = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]
    
    if not api_key:
        mock_response = "Error: GEMINI_API_KEY is not set. Please set it in the dashboard settings."
    else:
        try:
            client = genai.Client(api_key=api_key)
            
            system_prompt = get_config("SYSTEM_PROMPT", "")
            thinking_enabled = get_config("THINKING_ENABLED", "false").lower() == "true"
            add_datetime_enabled = get_config("ADD_DATETIME_ENABLED", "false").lower() == "true"
            
            if add_datetime_enabled:
                import datetime
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                system_prompt = f"Current Datetime: {current_time}\n\n{system_prompt}"
                
            from database import get_ide_config
            project_path = get_ide_config('CURRENT_PROJECT_PATH')
            if project_path:
                system_prompt = f"IMPORTANT: You are currently operating in the workspace directory: {project_path}\nYou MUST use this absolute path as the base directory for all file operations (reading, writing, searching) unless the user specifies otherwise.\n\n{system_prompt}"
            
            config_kwargs = {
                "tools": AVAILABLE_TOOLS,
                "temperature": 0.0,
            }
            
            if system_prompt:
                config_kwargs["system_instruction"] = system_prompt
            
            if thinking_enabled:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)
            
            mock_response = invoke_llm_with_fallback(client, history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False)
            
                
        except Exception as e:
            mock_response = f"Error calling Gemini API: {str(e)}"
    
    # Write to messages_out
    message_out_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    cursor.execute('''
        INSERT INTO messages_out (id, session_id, in_reply_to, content)
        VALUES (?, ?, ?, ?)
    ''', (message_out_id, session_id, message_in_id, mock_response))
    
    cursor.execute('UPDATE messages_in SET processed = 2 WHERE id = ?', (message_in_id,))
    
    conn.commit()
    conn.close()
    
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

    api_key = get_config("GEMINI_API_KEY")

    preferences = [os.environ.get(f"LLM_PREF_{i}") for i in range(1, 6)]
    models_to_try = [m for m in preferences if m and m.strip()]
    if not models_to_try:
        models_to_try = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]

    if not api_key:
        mock_response = "Error: GEMINI_API_KEY is not set. Please set it in the dashboard settings."
    else:
        try:
            client = genai.Client(api_key=api_key)

            system_prompt = get_config("IDE_PROMPT", "")
            
            from database import get_ide_config
            project_path = get_ide_config('CURRENT_PROJECT_PATH')
            if project_path:
                system_prompt = f"IMPORTANT: You are currently operating in the workspace directory: {project_path}\nYou MUST use this absolute path as the base directory for all file operations (reading, writing, searching) unless the user specifies otherwise.\n\n{system_prompt}"

            thinking_enabled = get_config("THINKING_ENABLED", "false").lower() == "true"

            config_kwargs = {
                "tools": AVAILABLE_TOOLS,
                "temperature": 0.0,
            }

            if system_prompt:
                config_kwargs["system_instruction"] = system_prompt

            if thinking_enabled:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)

            mock_response = invoke_llm_with_fallback(client, history, config_kwargs, content, models_to_try, cursor, session_id, message_in_id, is_ide=True)

        except Exception as e:
            mock_response = f"Error calling Gemini API: {str(e)}"

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
