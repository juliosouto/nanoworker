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
from agent.stop_check import StopRequestedError, reset_stop_check, set_stop_check
from database import get_config
from utils.message_utils import MEDIA_PLACEHOLDER, slice_conversation_to_budget


def _strip_media_parts(send_content):
    """
    Replaces media parts (images/files) with a short text placeholder so media
    is only sent to the LLM on the first call of a working session, not on
    every subsequent reflection/tool-loop invocation. Returns the text length
    kept (for budget accounting).
    """
    new_parts = []
    for p in send_content:
        has_media = not isinstance(p, str) and not getattr(p, "text", None)
        if has_media:
            new_parts.append(types.Part.from_text(text=MEDIA_PLACEHOLDER))
        else:
            new_parts.append(p)
    return new_parts


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


def execute_autonomous_loop(history, config_kwargs, initial_content, models_to_try, cursor, session_id, message_in_id, is_ide, on_complete=None, show_plan_in_chat=True):
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
        show_plan_in_chat (bool): Whether the "execution_plan" field from the model's
            JSON output should be surfaced to the user (as a separate feedback message).
            When False, the plan is discarded silently and never reaches the user.

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
    table_in = "ide_messages_in" if is_ide else "messages_in"

    def _stop_requested() -> bool:
        """True when a newer /stop command has been issued for this message.
        Polled while retries are sleeping so the wait is interruptible."""
        cursor.execute(f'''
            SELECT id FROM {table_in} 
            WHERE session_id = ? AND LOWER(TRIM(content)) = '/stop' AND rowid > (SELECT rowid FROM {table_in} WHERE id = ?)
        ''', (session_id, message_in_id))
        return cursor.fetchone() is not None

    def _abort_with_stop_message():
        """Stops the loop cleanly with the /stop confirmation when requested."""
        nonlocal final_response
        final_response = "🛑 Processamento interrompido pelo usuário (/stop)."

    token = set_stop_check(_stop_requested)
    try:
        for iteration in range(autonomous_limit):
            # Check for /stop command between LLM calls
            if _stop_requested():
                _abort_with_stop_message()
                break

            try:
                mock_response_raw = invoke_llm_with_fallback(history, config_kwargs, current_send_content, models_to_try, cursor, session_id, message_in_id, is_ide=is_ide, on_complete=on_complete)
            except StopRequestedError:
                # /stop triggered while a rate-limit/quota retry was waiting.
                _abort_with_stop_message()
                break

            # Fase 1: try the validated AgentResponse contract first (Pydantic,
            # coerces bools, drops malformed keys). Falls back to the legacy
            # lenient parser when native structured output is not in play.
            from agent.lc import outputs as lc_outputs
            agent_resp = lc_outputs.parse_agent_response(mock_response_raw)
            if agent_resp is not None:
                parsed_json = agent_resp.to_legacy_dict()
            else:
                parsed_json = _parse_json_response(mock_response_raw)

            if parsed_json and isinstance(parsed_json, dict) and "llm_response" in parsed_json and ("is_the_user_request_completely_satisfied" in parsed_json or "critical_system_failure" in parsed_json):
                final_response = parsed_json["llm_response"]
                is_satisfied = _coerce_bool(parsed_json.get("is_the_user_request_completely_satisfied"))
                critical_system_failure = _coerce_bool(parsed_json.get("critical_system_failure", False))
                user_prompt_val = parsed_json.get("user_prompt", "")

                # Surface the plan as its own intermediate message, mirroring the
                # existing feedback pattern (e.g. "⚙️ Executed tools: ..."). The plan
                # lives in its own JSON field, so it never contaminates llm_response.
                plan_val = parsed_json.get("execution_plan")
                if plan_val and isinstance(plan_val, str) and plan_val.strip():
                    plan_msg = f"📋 Execution Plan:\n{plan_val.strip()}"
                    if show_plan_in_chat:
                        try:
                            insert_feedback(cursor, table, session_id, message_in_id, plan_msg)
                        except Exception:
                            pass
                        if on_complete:
                            try:
                                on_complete(plan_msg)
                            except Exception as e:
                                print(f"Failed to call on_complete: {e}")

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

                        # Media (images/files) already seen by the model is not
                        # re-sent on subsequent iterations: swap media parts for
                        # a placeholder before promoting the content to history.
                        parts = []
                        for p in _strip_media_parts(current_send_content):
                            if isinstance(p, str):
                                p = types.Part.from_text(text=p)
                            parts.append(p)
                        history.append(types.Content(role="user", parts=parts))
                        history.append(types.Content(role="model", parts=[types.Part.from_text(text=mock_response_raw)]))
                        # Re-apply the combined slice budget, since the history
                        # just grew by the previous turn + reflection feedback.
                        history, trimmed = slice_conversation_to_budget(history, feedback_text)
                        current_send_content = [types.Part.from_text(text=trimmed)]
                    else:
                        break
            else:
                final_response = mock_response_raw
                break
    finally:
        reset_stop_check(token)

    return final_response
