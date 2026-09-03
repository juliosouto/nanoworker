"""Tests for the in-flight /stop mechanism that interrupts long retry waits."""
import pytest
from unittest.mock import MagicMock, patch

from agent.stop_check import (
    StopRequestedError,
    is_stop_requested,
    reset_stop_check,
    set_stop_check,
    sleep_interruptible,
)
from agent.llm_providers import call_gemini_llm
from agent.openai_tools import execute_openai_compatible_llm
from agent.llm_router import invoke_llm_with_fallback


def test_is_stop_requested_false_without_checker():
    # No checker registered (default context) -> never reports a stop.
    assert is_stop_requested() is False


def test_sleep_interruptible_waits_fully_without_stop():
    with patch("agent.stop_check.time.sleep", return_value=None) as mock_sleep:
        aborted = sleep_interruptible(3.0, poll_interval=1.0)
    assert aborted is False
    # 3 chunks of 1s each
    assert mock_sleep.call_count == 3


def test_stop_check_context_roundtrip():
    token = set_stop_check(lambda: True)
    try:
        assert is_stop_requested() is True
    finally:
        reset_stop_check(token)
    assert is_stop_requested() is False


@patch("agent.llm_providers.get_config")
@patch("agent.llm_providers.genai.Client")
def test_gemini_429_aborts_on_stop(mock_client_cls, mock_get_config):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_chat = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    err_429 = "429 RESOURCE_EXHAUSTED. Quota exceeded GenerateContentInputTokensPerModelPerMinute-FreeTier"
    mock_chat.send_message.side_effect = Exception(err_429)

    token = set_stop_check(lambda: True)  # user issued /stop
    try:
        with patch("agent.llm_providers.time.sleep", return_value=None), \
             patch("agent.llm_providers.time.time", return_value=30.0), \
             pytest.raises(StopRequestedError):
            call_gemini_llm("model", [], {}, "Hello", MagicMock(),
                            "sess", "msg", "tbl", api_key="test_key")
    finally:
        reset_stop_check(token)

    # Only the first send_message happened; the retry aborted instead of waiting.
    assert mock_chat.send_message.call_count == 1


@patch("agent.openai_tools.get_config")
def test_openai_429_aborts_on_stop(mock_get_config):
    mock_get_config.side_effect = lambda key, default=None: default
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception(
        "429 RESOURCE_EXHAUSTED. rate limit exceeded"
    )

    token = set_stop_check(lambda: True)
    try:
        with pytest.raises(StopRequestedError):
            execute_openai_compatible_llm(
                mock_client, "gpt-4o", [], {}, "hello",
                MagicMock(), "session-1", "msg-1", "messages_out",
            )
    finally:
        reset_stop_check(token)

    assert mock_client.chat.completions.create.call_count == 1


@patch("agent.llm_router.route_llm_call")
@patch("agent.llm_router.insert_feedback")
def test_fallback_does_not_run_after_stop(mock_insert_feedback, mock_route):
    mock_route.side_effect = StopRequestedError()
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.execute.return_value = None

    model_call_lines = []

    def _fake_insert_feedback(cursor, table, session_id, message_in_id, content):
        model_call_lines.append(content)

    mock_insert_feedback.side_effect = _fake_insert_feedback

    with pytest.raises(StopRequestedError):
        invoke_llm_with_fallback(
            [], {}, "hello", ["model-a", "model-b"],
            cursor, "session-1", "msg-1", is_ide=False,
        )

    # No "Changing to model-b" feedback is emitted: the fallback chain is aborted.
    assert not any("Changing to" in line for line in model_call_lines)