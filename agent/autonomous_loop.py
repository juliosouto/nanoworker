"""
Autonomous reflection loop: re-invokes the LLM when the agent determines
the user's request is not yet fully satisfied.
"""
import json
import re
import uuid

from google.genai import types

from agent.db_feedback import insert_feedback
from agent.llm_router import invoke_llm_with_fallback
from database import get_config


def execute_autonomous_loop(history, config_kwargs, initial_content, models_to_try, cursor, session_id, message_in_id, is_ide, on_complete=None):
    """
    Executes the autonomous reflection loop that re-invokes the LLM
    when the response indicates the user's request is not yet satisfied.

    Arguments:
        history (list): The conversation history.
        config_kwargs (dict): Configuration for generation.
        initial_content: The content to send on the first iteration.
        models_to_try (list): Ordered list of model names to try.
        cursor: Database cursor.
        session_id (str): Session identifier.
        message_in_id (str): Input message ID.
        is_ide (bool): Whether this is an IDE message.
        on_complete (callable, optional): Callback for intermediate feedback.

    Returns:
        str: The final response text.
    """
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
    table = "ide_messages_out" if is_ide else "messages_out"

    for iteration in range(autonomous_limit):
        # Check for /stop command
        table_in = "ide_messages_in" if is_ide else "messages_in"
        cursor.execute(f'''
            SELECT id FROM {table_in} 
            WHERE session_id = ? AND LOWER(TRIM(content)) = '/stop' AND rowid > (SELECT rowid FROM {table_in} WHERE id = ?)
        ''', (session_id, message_in_id))
        stop_msg = cursor.fetchone()
        if stop_msg:
            final_response = "🛑 Processamento interrompido pelo usuário (/stop)."
            break

        mock_response_raw = invoke_llm_with_fallback(history, config_kwargs, current_send_content, models_to_try, cursor, session_id, message_in_id, is_ide=is_ide, on_complete=on_complete)

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

        if parsed_json and isinstance(parsed_json, dict) and "llm_response" in parsed_json and ("is_the_user_request_completely_satisfied" in parsed_json or "critical_system_failure" in parsed_json):
            final_response = parsed_json["llm_response"]
            is_satisfied = parsed_json.get("is_the_user_request_completely_satisfied")
            critical_system_failure = parsed_json.get("critical_system_failure", False)
            user_prompt_val = parsed_json.get("user_prompt", "")

            if critical_system_failure is True:
                break
            elif is_satisfied is True:
                break
            else:
                if iteration < autonomous_limit - 1:
                    feedback_text = f"Your response does not completely answer the user's prompt. Try a different approach or tool.\n{{\n  \"user_prompt\": {json.dumps(user_prompt_val)},\n  \"llm_response\": {json.dumps(final_response)},\n  \"is_the_user_request_completely_satisfied\": null,\n  \"critical_system_failure\": null\n}}\nPlease try again."

                    user_feedback_msg = f"🔄 Agent reflecting (Iteration {iteration + 1}/{autonomous_limit})..."
                    try:
                        insert_feedback(cursor, table, session_id, message_in_id, user_feedback_msg)
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
