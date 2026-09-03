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


def _coerce_bool(value):
    """Coerce a JSON boolean that may arrive as a raw bool, a string ("true"/"false"),
    or an int (0/1) into a real Python bool. None is preserved as None so the
    existing nullable semantics of the reflection fields stay unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return value


def _extract_balanced_json_blocks(text):
    """Scan ``text`` and return every top-level JSON object literal ``{...}`` that
    is fully balanced. Strings are skipped (honoring backslash escapes), so braces
    inside string values ("use {braces}") never break the object balance. Blocks
    are returned in order of appearance."""
    blocks = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        if ch == "{":
            start = i
            depth = 1
            i += 1
            closed = False
            while i < n:
                c = text[i]
                if c == '"':
                    i += 1
                    while i < n:
                        if text[i] == "\\":
                            i += 2
                        elif text[i] == '"':
                            i += 1
                            break
                        else:
                            i += 1
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(text[start:i + 1])
                        closed = True
                        i += 1
                        break
                i += 1
            if not closed:
                break  # unterminated block -> stop scanning
            continue
        i += 1
    return blocks


def _parse_json_response(raw_response):
    """Attempt to parse a model response into a dict, trying progressively more
    lenient extraction strategies.

    1. The whole (fence-stripped) text as JSON.
    2. The greedy regex fallback (``{...}``) for backward compatibility.
    3. A balanced-brace scanner over the raw text; candidate blocks are tried from
       last to first (the final answer usually appears last).

    The first parseable dict that contains ``llm_response`` is preferred; otherwise
    the first parseable dict (if any) is returned. Returns None if nothing parses.
    """
    if not raw_response:
        return None

    raw_text = raw_response.strip()

    # Strip markdown fences regardless of language tag / surrounding prose.
    cleaned = raw_text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    candidates = []

    # Fast path: the entire (fence-cleaned) response is valid JSON.
    if cleaned:
        try:
            candidates.append(json.loads(cleaned))
        except (json.JSONDecodeError, TypeError):
            pass

    # Backward-compatible greedy regex fallback.
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            candidates.append(json.loads(match.group(0)))
        except (json.JSONDecodeError, TypeError):
            pass

    # Balanced-brace scanner; try from the last block to the first.
    for block in reversed(_extract_balanced_json_blocks(raw_text)):
        try:
            candidates.append(json.loads(block))
        except (json.JSONDecodeError, TypeError):
            continue

    for obj in candidates:
        if isinstance(obj, dict) and "llm_response" in obj:
            return obj
    for obj in candidates:
        if isinstance(obj, dict):
            return obj
    return None


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

        parsed_json = _parse_json_response(mock_response_raw)

        if parsed_json and isinstance(parsed_json, dict) and "llm_response" in parsed_json and ("is_the_user_request_completely_satisfied" in parsed_json or "critical_system_failure" in parsed_json):
            final_response = parsed_json["llm_response"]
            is_satisfied = _coerce_bool(parsed_json.get("is_the_user_request_completely_satisfied"))
            critical_system_failure = _coerce_bool(parsed_json.get("critical_system_failure", False))
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
