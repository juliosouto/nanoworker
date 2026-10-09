"""Tests for the autonomous reflection loop's JSON parsing and reflection behavior."""
import json

import pytest

from agent.autonomous_loop import (
    _coerce_bool,
    _extract_balanced_json_blocks,
    _parse_json_response,
    execute_autonomous_loop,
)
from google.genai import types


def make_part(text):
    return types.Part.from_text(text=text)


def make_content(items):
    return [make_part(i) if isinstance(i, str) else i for i in items]


# ---------------------------------------------------------------------------
# Unit tests for the parsing helpers
# ---------------------------------------------------------------------------

def test_coerce_bool_variants():
    assert _coerce_bool(True) is True
    assert _coerce_bool(False) is False
    assert _coerce_bool("true") is True
    assert _coerce_bool("True") is True
    assert _coerce_bool(" FALSE ") is False
    assert _coerce_bool("false") is False
    assert _coerce_bool(1) is True
    assert _coerce_bool(0) is False
    assert _coerce_bool(None) is None
    assert _coerce_bool("maybe") == "maybe"  # unknown string left untouched


def test_extract_balanced_json_blocks_skips_braces_in_strings():
    text = '{"use": "braces {inside}", "n": 1} e depois {"n": 2}'
    blocks = _extract_balanced_json_blocks(text)
    assert len(blocks) == 2
    assert json.loads(blocks[0])["use"] == "braces {inside}"
    assert json.loads(blocks[1])["n"] == 2


def test_extract_balanced_json_blocks_handles_escaped_quotes():
    text = r'{"msg": "he said \"hi}\""} trailing'
    blocks = _extract_balanced_json_blocks(text)
    assert len(blocks) == 1
    assert json.loads(blocks[0])["msg"] == 'he said "hi}"'


def test_parse_json_response_plain():
    obj = {"llm_response": "ok", "is_the_user_request_completely_satisfied": True}
    assert _parse_json_response(json.dumps(obj)) == obj


def test_parse_json_response_fenced():
    text = '```json\n{"llm_response": "ok", "is_the_user_request_completely_satisfied": false}\n```'
    parsed = _parse_json_response(text)
    assert parsed["is_the_user_request_completely_satisfied"] is False


def test_parse_json_response_prose_around():
    text = 'Sure! Here is your result: {"llm_response": "done", "critical_system_failure": true} Hope it helps.'
    parsed = _parse_json_response(text)
    assert parsed["llm_response"] == "done"
    assert parsed["critical_system_failure"] is True


def test_parse_json_response_greedy_regex_fails_but_scanner_recovers():
    # A trailing '}' outside the object makes the greedy regex swallow an extra
    # brace (invalid JSON); the balanced scanner isolates the valid block.
    text = '{"llm_response": "rec", "is_the_user_request_completely_satisfied": false} extra }'
    parsed = _parse_json_response(text)
    assert parsed["llm_response"] == "rec"


def test_parse_json_response_braces_in_string():
    text = '{"llm_response": "use {braces}", "critical_system_failure": false}'
    parsed = _parse_json_response(text)
    assert parsed["llm_response"] == "use {braces}"


def test_parse_json_response_multiple_blocks_prefers_llm_response():
    text = '{"a": 1} depois {"llm_response": "last", "is_the_user_request_completely_satisfied": true}'
    parsed = _parse_json_response(text)
    assert parsed["llm_response"] == "last"


def test_parse_json_response_unparseable():
    assert _parse_json_response("purely prose, no JSON here") is None
    assert _parse_json_response("") is None
    assert _parse_json_response(None) is None


# ---------------------------------------------------------------------------
# Reflection loop behavior
# ---------------------------------------------------------------------------

def run_loop(side_effect_responses, autonomous_mode="10", cursor=None, on_complete=None):
    """Drive execute_autonomous_loop with canned LLM responses.

    Returns (final_response, invoke_calls, history, cursor).
    """
    from unittest.mock import MagicMock
    mock_cursor = cursor or MagicMock()
    if cursor is None:
        # The loop queries for a /stop command; return None so it never stops.
        mock_cursor.fetchone.return_value = None

    calls = []

    def fake_invoke(history, config_kwargs, current_send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=None):
        calls.append(list(current_send_content))
        return side_effect_responses[len(calls) - 1]

    history = []

    import agent.autonomous_loop as mod
    original = mod.invoke_llm_with_fallback
    mod.invoke_llm_with_fallback = fake_invoke
    original_get_config = mod.get_config
    original_insert_feedback = mod.insert_feedback
    feedback_calls = []
    mod.insert_feedback = lambda *a, **k: feedback_calls.append(a)

    def fake_get_config(key, default=None):
        if key == "AUTONOMOUS_MODE":
            return str(autonomous_mode)
        return original_get_config(key, default)

    mod.get_config = fake_get_config
    try:
        final = execute_autonomous_loop(
            history,
            {"show_tools_results": True},
            ["user request"],
            ["model-a"],
            mock_cursor,
            "sess-x",
            "msg-in-1",
            is_ide=False,
            on_complete=on_complete,
        )
    finally:
        mod.invoke_llm_with_fallback = original
        mod.get_config = original_get_config
        mod.insert_feedback = original_insert_feedback

    return final, calls, history, mock_cursor, feedback_calls


def test_loop_reflects_when_not_satisfied():
    # First response says not satisfied -> re-invoke; second satisfies -> break.
    final, calls, history, cursor, feedback_calls = run_loop(
        [
            '{"llm_response": "partial", "is_the_user_request_completely_satisfied": false}',
            '{"llm_response": "final answer", "is_the_user_request_completely_satisfied": true}',
        ]
    )
    assert final == "final answer"
    assert len(calls) == 2
    # History gained a user + model turn from the first iteration.
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].parts[0].text == "user request"
    assert history[1].role == "model"
    assert history[1].parts[0].text.startswith('{"llm_response": "partial"')
    # The reflection feedback was recorded in the DB (insert_feedback).
    assert any("Agent reflecting" in str(a) for a in feedback_calls)
    # The second invocation receives the reflection feedback_text.
    assert "does not completely answer" in calls[1][0].text


def test_loop_breaks_when_satisfied():
    final, calls, history, cursor, feedback_calls = run_loop(
        ['{"llm_response": "done", "is_the_user_request_completely_satisfied": true}']
    )
    assert final == "done"
    assert len(calls) == 1
    assert history == []
    assert feedback_calls == []


def test_loop_breaks_on_critical_system_failure():
    final, calls, history, cursor, feedback_calls = run_loop(
        ['{"llm_response": "failed tool", "critical_system_failure": true}']
    )
    assert final == "failed tool"
    assert len(calls) == 1


def test_loop_plain_text_no_json_returns_raw():
    final, calls, history, cursor, feedback_calls = run_loop(["just a plain text answer"])
    assert final == "just a plain text answer"
    assert len(calls) == 1


def test_loop_coerces_string_booleans():
    # "false" as a string -> should still reflect; "true" as string -> breaks.
    final, calls, history, cursor, feedback_calls = run_loop(
        [
            '{"llm_response": "p", "is_the_user_request_completely_satisfied": "false"}',
            '{"llm_response": "q", "is_the_user_request_completely_satisfied": "true"}',
        ]
    )
    assert final == "q"
    assert len(calls) == 2


def test_loop_prose_around_json_recovers():
    final, calls, history, cursor, feedback_calls = run_loop(
        [
            'Here it is: {"llm_response": "partial", "is_the_user_request_completely_satisfied": false} end',
            '{"llm_response": "ok now", "is_the_user_request_completely_satisfied": true}',
        ]
    )
    assert final == "ok now"
    assert len(calls) == 2


def test_loop_respects_limit_no_reflection():
    # autonomous_mode=2 and an always-false response: reflects in iteration 0,
    # then breaks at the limit (iteration 1) returning the last llm_response.
    final, calls, history, cursor, feedback_calls = run_loop(
        [
            '{"llm_response": "a", "is_the_user_request_completely_satisfied": false}',
            '{"llm_response": "b", "is_the_user_request_completely_satisfied": false}',
        ],
        autonomous_mode=2,
    )
    assert final == "b"
    assert len(calls) == 2


def _run_loop_with_plan(response_raw, show_plan_in_chat):
    """Drive execute_autonomous_loop with a single canned LLM response, capturing
    feedback inserts and on_complete calls. Returns (final, feedback_calls, on_complete_msgs)."""
    import agent.autonomous_loop as mod
    from unittest.mock import MagicMock

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    on_complete_msgs = []

    def fake_invoke(history, config_kwargs, current_send_content, models_to_try, cursor, session_id, message_in_id, is_ide=False, on_complete=None):
        return response_raw

    original_invoke = mod.invoke_llm_with_fallback
    original_get_config = mod.get_config
    original_insert_feedback = mod.insert_feedback
    feedback_calls = []
    mod.invoke_llm_with_fallback = fake_invoke
    mod.insert_feedback = lambda *a, **k: feedback_calls.append(a)
    mod.get_config = lambda key, default=None: str(1) if key == "AUTONOMOUS_MODE" else original_get_config(key, default)
    try:
        final = mod.execute_autonomous_loop(
            [], {"show_tools_results": True}, ["user request"], ["model-a"],
            mock_cursor, "sess-x", "msg-in-1", is_ide=False,
            on_complete=lambda m: on_complete_msgs.append(m),
            show_plan_in_chat=show_plan_in_chat,
        )
    finally:
        mod.invoke_llm_with_fallback = original_invoke
        mod.get_config = original_get_config
        mod.insert_feedback = original_insert_feedback

    return final, feedback_calls, on_complete_msgs


def test_loop_show_plan_in_chat_true():
    final, feedback_calls, on_complete_msgs = _run_loop_with_plan(
        '{"llm_response": "final answer", "execution_plan": "step1; step2", "is_the_user_request_completely_satisfied": true}',
        show_plan_in_chat=True,
    )
    assert final == "final answer"
    # Plan surfaced as separate feedback (DB insert + on_complete stream).
    assert any("📋 Execution Plan" in str(f[4]) for f in feedback_calls)
    assert any("📋 Execution Plan" in m for m in on_complete_msgs)


def test_loop_show_plan_in_chat_false_discards():
    final, feedback_calls, on_complete_msgs = _run_loop_with_plan(
        '{"llm_response": "final answer", "execution_plan": "secret plan", "is_the_user_request_completely_satisfied": true}',
        show_plan_in_chat=False,
    )
    # Final response stays clean; plan never persisted nor streamed.
    assert final == "final answer"
    assert not any("Execution Plan" in str(f) for f in feedback_calls)
    assert on_complete_msgs == []


def test_loop_no_plan_key_unchanged():
    final, feedback_calls, on_complete_msgs = _run_loop_with_plan(
        '{"llm_response": "plain", "is_the_user_request_completely_satisfied": true}',
        show_plan_in_chat=True,
    )
    assert final == "plain"
    assert not any("Execution Plan" in str(f) for f in feedback_calls)
    assert on_complete_msgs == []