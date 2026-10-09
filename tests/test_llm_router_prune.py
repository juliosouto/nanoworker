"""Regression tests for history pruning (context window / max output tokens)."""
import pytest
from unittest.mock import patch, MagicMock

from google.genai import types

from agent.llm_router import (
    route_llm_call,
    _prune_history_to_fit,
    _estimate_tokens,
    _DEFAULT_OUTPUT_RESERVE,
    _SAFE_MARGIN_TOKENS,
)


def _dict_history(count, chars=4000):
    """Returns `count` OpenAI-style history items with known-length text."""
    return [{"role": "user", "content": "x" * chars} for _ in range(count)]


def _content_history(count, chars=4000):
    """Returns `count` Gemini-format history messages with known-length text."""
    return [
        types.Content(
            role="user" if i % 2 == 0 else "model",
            parts=[types.Part.from_text(text="x" * chars)],
        )
        for i in range(count)
    ]


def test_no_prune_when_context_unset():
    """context_window unset (None/0) must leave the history untouched (same object)."""
    history = _dict_history(5)
    result = _prune_history_to_fit(history, None, {}, "hi")
    assert result is history
    result = _prune_history_to_fit(history, 0, {}, "hi")
    assert result is history


def test_prunes_oldest_keeps_recent_order():
    """Old messages must be dropped, newest kept, order preserved."""
    # 4 msgs * 1000 tokens (4000 chars) = 4000 tokens input.
    # context=3000, reserve=100 -> budget = 3000-100-1024-~1 = ~1875,
    # so only the newest (last) message fits alone inside the budget.
    history = _dict_history(4, chars=4000)
    pruned = _prune_history_to_fit(history, 3000, {}, "hi", max_output_tokens=100)
    assert len(pruned) == 1
    assert pruned == history[3:]
    assert pruned[-1] is history[-1]


def test_history_that_fits_is_kept():
    """When everything fits, no message is dropped."""
    history = _dict_history(3, chars=4000)  # ~3000 tokens total
    pruned = _prune_history_to_fit(history, 300000, {}, "hi", max_output_tokens=100)
    assert pruned == history


def test_supports_content_objects():
    """Pruning must work with Gemini-format types.Content messages."""
    history = _content_history(4, chars=4000)
    pruned = _prune_history_to_fit(history, 3000, {}, "hi", max_output_tokens=100)
    assert len(pruned) == 1
    assert pruned[-1] is history[-1]


def test_reserve_uses_max_output_tokens_when_set():
    """With max_output_tokens set the reserve is that value -> no prune for small input."""
    history = _dict_history(3, chars=2000)  # ~1500 tokens total
    pruned = _prune_history_to_fit(history, 5000, {}, "hi", max_output_tokens=2000)
    assert pruned == history


def test_reserve_defaults_to_32000():
    """Without max_output_tokens the reserve mirrors OpenRouter's 32000 -> prune."""
    history = _dict_history(3, chars=2000)  # ~1500 tokens total
    pruned = _prune_history_to_fit(history, 5000, {}, "hi", max_output_tokens=None)
    # budget = 5000 - 32000 - 1024 - ~1 < 0 -> only the newest history message kept.
    assert len(pruned) == 1
    assert pruned[0] is history[-1]


def test_system_and_tools_count_toward_budget():
    """A large system prompt / tool set consumes budget and increases pruning."""
    history = _dict_history(3, chars=4000)  # ~3000 tokens total
    kwargs_empty = {}

    # context=5000, reserve=100 -> budget ~= 3875, which fits the 3000-token history.
    fitted = _prune_history_to_fit(history, 5000, kwargs_empty, "hi", max_output_tokens=100)
    assert fitted == history

    # A huge system prompt (+ tools) pushes the same history over the budget.
    class DummyTool:
        __doc__ = "z" * 40000  # ~10000 tokens

    kwargs = {
        "system_instruction": "y" * 80000,  # ~20000 tokens
        "tools": [DummyTool],
    }
    pruned = _prune_history_to_fit(history, 5000, kwargs, "hi", max_output_tokens=100)
    assert len(pruned) < len(history)


def test_current_message_and_content_list_count():
    """A long list content is accounted for as the current user message."""
    history = _dict_history(2, chars=4000)  # ~2000 tokens input
    content = ["q" * 40000]  # ~10000 tokens current message
    pruned = _prune_history_to_fit(
        history, 5000, {}, content, max_output_tokens=10
    )
    # budget = 5000 - 10 - 1024 - ~10000 < 0 -> only newest history message kept.
    assert len(pruned) == 1
    assert pruned[0] is history[-1]


def test_estimate_tokens_matches_chars_per_token():
    assert _estimate_tokens("abcd") == 1
    assert _estimate_tokens("") == 0
    assert _estimate_tokens(None) == 0


@patch("database.decrypt_value")
def test_route_llm_call_applies_pruning(mock_decrypt):
    """route_llm_call must prune before dispatching to the provider."""
    with patch("database.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "provider": "openai",
            "api_key": "enc_key",
            "thinking": 0,
            "context_window": 3000,
            "max_output_tokens": 100,
        }
        mock_decrypt.return_value = "key"

        history = _dict_history(4, chars=4000)  # ~4000 tokens -> pruned to 2
        content = "hello"

        with patch("agent.llm_providers.call_openai_llm") as mock_call:
            route_llm_call(
                "gpt-x",
                history,
                {},
                content,
                MagicMock(),
                "sess",
                "msg-in",
                False,
            )
            args = mock_call.call_args[0]
            assert len(args[1]) == 1  # history passed to provider is pruned to newest
            assert args[1][-1] is history[-1]