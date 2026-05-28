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
from utils.message_utils import truncate_message

load_dotenv(override=True)

def call_gemini_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None) -> str:
    """
    Realiza uma chamada para a API do Google Gemini.
    Suporta chamadas de ferramentas (function calling) e lida com retentativas 
    em caso de falhas transitórias (como erro 503).
    
    Argumentos:
        model_name (str): O nome do modelo Gemini a ser utilizado.
        history (list): O histórico da conversa no formato esperado pela API.
        config_kwargs (dict): Configurações adicionais de geração.
        content (any): O conteúdo da mensagem atual do usuário.
        cursor (sqlite3.Cursor): O cursor do banco de dados para logs e feedbacks parciais.
        session_id (str): ID da sessão de chat.
        message_in_id (str): ID da mensagem de entrada sendo processada.
        table (str): Nome da tabela para inserir feedbacks (ex: messages_out).
        api_key (str, opcional): Chave de API do Gemini. Levanta exceção se não fornecida.
        
    Retorna:
        str: O texto da resposta gerada pelo modelo.
    """
    max_retries = 5
    if not api_key:
        raise ValueError("API Key for Gemini model is not set.")
    client = genai.Client(api_key=api_key)
    
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
                tools_used = []
                tool_results = []
                if hasattr(response, 'automatic_function_calling_history') and response.automatic_function_calling_history:
                    for h in response.automatic_function_calling_history:
                        for p in getattr(h, 'parts', []):
                            if getattr(p, 'function_call', None):
                                tool_name = p.function_call.name
                                if tool_name not in tools_used:
                                    tools_used.append(tool_name)
                            if getattr(p, 'function_response', None):
                                resp_val = str(getattr(p.function_response, 'response', ''))
                                if isinstance(getattr(p.function_response, 'response', None), dict):
                                    resp_dict = p.function_response.response
                                    if 'result' in resp_dict:
                                        resp_val = str(resp_dict['result'])
                                if resp_val:
                                    tool_results.append(resp_val)
                
                if tools_used:
                    tools_str = ", ".join(tools_used)
                    results_str = ""
                    if tool_results:
                        results_str = "\n\nResultados internos:\n- " + "\n- ".join(tool_results)
                    response_text = f"⚙️ Tarefa concluída.\nFerramentas utilizadas: {tools_str}{results_str}"
                else:
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
                raise e
            else:
                raise e
                
    if success:
        return response_text
    return "Error: Gemini model failed."

def call_qwen_llm(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, table: str, api_key: str = None) -> str:
    """
    Realiza uma chamada para a API da OpenAI compatível com modelos Qwen (DashScope).
    
    Argumentos:
        model_name (str): O nome do modelo Qwen.
        history (list): O histórico da conversa.
        config_kwargs (dict): Configurações adicionais de geração (ex: system_instruction).
        content (any): O conteúdo da mensagem do usuário atual.
        cursor (sqlite3.Cursor): O cursor do banco de dados (não utilizado ativamente nesta função, mantido para assinatura padrão).
        session_id (str): ID da sessão.
        message_in_id (str): ID da mensagem de entrada.
        table (str): Nome da tabela de saída.
        api_key (str, opcional): Chave de API do Qwen. Levanta exceção se ausente.
        
    Retorna:
        str: O texto da resposta gerada pelo modelo.
    """
    import openai
    if not api_key:
        raise ValueError("API Key for Qwen model is not set.")
    
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    
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
    
    response = client.chat.completions.create(
        model=model_name,
        messages=messages
    )
    return response.choices[0].message.content

def route_llm_call(model_name: str, history: list, config_kwargs: dict, content: any, cursor: any, session_id: str, message_in_id: str, is_ide: bool) -> str:
    """
    Roteia a chamada do LLM para o provedor apropriado (Qwen ou Gemini) 
    com base nas configurações armazenadas no banco de dados para o modelo solicitado.
    
    Argumentos:
        model_name (str): O nome do modelo selecionado.
        history (list): Histórico da conversa.
        config_kwargs (dict): Argumentos de configuração para o LLM.
        content (any): Conteúdo da mensagem a ser processada.
        cursor (sqlite3.Cursor): Cursor do banco de dados para operações de log.
        session_id (str): Identificador da sessão.
        message_in_id (str): Identificador da mensagem de origem.
        is_ide (bool): Flag indicando se a requisição se originou da interface da IDE.
        
    Retorna:
        str: Resposta processada pelo modelo selecionado.
    """
    table = "ide_messages_out" if is_ide else "messages_out"
    
    from database import get_db, decrypt_value
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT provider, api_key, thinking FROM llm_config WHERE model_name = ?", (model_name,))
    row = c.fetchone()
    conn.close()
    
    provider = None
    api_key = None
    model_thinking = False
    if row:
        provider = row['provider'].lower() if row['provider'] else None
        if row['api_key']:
            api_key = decrypt_value(row['api_key'])
        model_thinking = bool(row['thinking'])
            
    local_kwargs = config_kwargs.copy()
    if not model_thinking:
        local_kwargs.pop('thinking_config', None)
        
    if provider == "qwen" or model_name.lower().startswith("qwen"):
        return call_qwen_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)
    else:
        return call_gemini_llm(model_name, history, local_kwargs, content, cursor, session_id, message_in_id, table, api_key)

def invoke_llm_with_fallback(history: list, config_kwargs: dict, content: any, models_to_try: list, cursor: any, session_id: str, message_in_id: str, is_ide: bool = False) -> str:
    """
    Tenta invocar iterativamente uma lista de modelos preferenciais em caso de falha.
    Registra mensagens de feedback no banco informando a troca de modelos.
    
    Argumentos:
        history (list): O histórico da conversa.
        config_kwargs (dict): Configurações para a geração.
        content (any): O conteúdo da mensagem atual do usuário.
        models_to_try (list): Uma lista ordenada com os nomes dos modelos para tentar.
        cursor (sqlite3.Cursor): O cursor do banco de dados.
        session_id (str): ID da sessão.
        message_in_id (str): ID da mensagem de entrada associada.
        is_ide (bool): Se verdadeiro, envia o feedback para ide_messages_out. Padrão é False.
        
    Retorna:
        str: A resposta do primeiro modelo que obteve sucesso, ou uma mensagem de erro geral se todos falharem.
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

def process_message(message_in_id, session_id, content, on_complete=None):
    """
    Runs the LLM agent, providing it with tools and conversation history.
    """
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
    if session_row:
        channel_id = session_row['channel_id']
        if channel_id.startswith('wa_web:') or channel_id.startswith('whatsapp:'):
            clean_channel = channel_id.replace('wa_web:', '').replace('whatsapp:', '')
            if '-' in clean_channel or clean_channel.startswith('120363'):
                is_wa_group = True
    
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

    preferences = [get_config(f"LLM_PREF_{i}") for i in range(1, 6)]
    models_to_try = [m for m in preferences if m and m.strip()]
    if not models_to_try:
        models_to_try = [get_config("GEMINI_MODEL", "gemini-2.5-flash")]
    
    try:
        system_prompt = get_config("SYSTEM_PROMPT", "")
        
        cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
        session_row = cursor.fetchone()
        if session_row:
            channel_id = session_row['channel_id']
            if channel_id.startswith('whatsapp:') or channel_id.startswith('wa_web:'):
                system_prompt = f"This message comes from WhatsApp. To reply to the current conversation, simply output your text directly. Do NOT use the send_whatsapp_message tool for standard replies. The system will automatically forward your text to the chat. However, if you need to send an image or file (like a screenshot), you MUST use the send_whatsapp_file tool (with phone_number='self').\n\n{system_prompt}"
            elif channel_id.startswith('web-chat'):
                system_prompt = f"This message comes from the web chat (HTML). You must reply via the web chat.\n\n{system_prompt}"
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
            "tools": get_permitted_tools(),
            "temperature": 0.0,
        }
        
        system_prompt = standard_prompts.apply_standard_rules(system_prompt)
        
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        
        if thinking_enabled:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)
        
        mock_response = invoke_llm_with_fallback(history, config_kwargs, send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False)
        
            
    except Exception as e:
        mock_response = f"Error calling LLM API: {str(e)}"
    
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
            "tools": get_permitted_tools(),
            "temperature": 0.0,
        }

        system_prompt = standard_prompts.apply_standard_rules(system_prompt)

        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        if thinking_enabled:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)

        mock_response = invoke_llm_with_fallback(history, config_kwargs, content, models_to_try, cursor, session_id, message_in_id, is_ide=True)

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
