"""Tests for the didactic error feedback in the OpenAI-compatible tool loop.

These only cover error paths (invalid JSON, unknown tool) that previously returned
generic messages, which is where small models get stuck.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner


def tool_a(query: str) -> str:
    """A simple dummy tool. Args: query: the search term."""
    return "result a"


def _mock_config(key, default=None):
    if key == "AUTONOMOUS_MODE":
        return "1"
    if key == "agent_name":
        return "Agent"
    return default


def _run_loop(tool_calls):
    mock_client = MagicMock()

    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = tool_calls["name"]
    tc.function.arguments = tool_calls["arguments"]

    msg1 = MagicMock()
    msg1.content = None
    msg1.tool_calls = [tc]
    c1 = MagicMock()
    c1.choices = [MagicMock(message=msg1)]

    msg2 = MagicMock()
    msg2.content = "final answer"
    msg2.tool_calls = None
    c2 = MagicMock()
    c2.choices = [MagicMock(message=msg2)]

    mock_client.chat.completions.create.side_effect = [c1, c2]

    with patch("agent.openai_tools.get_config", side_effect=_mock_config):
        result = agent_runner.execute_openai_compatible_llm(
            mock_client,
            "gpt-4o",
            [],
            {"tools": [tool_a]},
            "hello",
            MagicMock(),
            "session-1",
            "msg-1",
            "messages_out",
        )
    messages = mock_client.chat.completions.create.call_args_list[1][1]["messages"]
    tool_msg = [m for m in messages if m["role"] == "tool"]
    return result, (tool_msg[0]["content"] if tool_msg else "")


class TestLoopErrorFeedback(unittest.TestCase):
    def test_invalid_json_is_didactic(self):
        result, tool_content = _run_loop(
            tool_calls={"name": "tool_a", "arguments": "{bad json"}
        )
        self.assertEqual(result, "final answer")
        self.assertIn("could not be parsed", tool_content)
        self.assertIn("invalid JSON", tool_content)
        self.assertIn("query", tool_content)  # documents expected argument

    def test_unknown_tool_lists_available(self):
        result, tool_content = _run_loop(
            tool_calls={"name": "nonexistent_tool", "arguments": "{}"}
        )
        self.assertEqual(result, "final answer")
        self.assertIn("does not exist", tool_content)
        self.assertIn("Available tools", tool_content)
        self.assertIn("tool_a", tool_content)

    def test_type_error_lists_expected_args(self):
        # Existing tool, valid JSON but missing required param triggers TypeError.
        result, tool_content = _run_loop(
            tool_calls={"name": "tool_a", "arguments": "{}"}
        )
        self.assertEqual(result, "final answer")
        self.assertIn("Error executing tool_a", tool_content)
        self.assertIn("query", tool_content)


class TestRateLimitRetry(unittest.TestCase):
    """429 rate-limit / quota errors are retried with real-time feedback before
    propagating to the model fallback chain."""

    def _final_answer_response(self):
        msg = MagicMock()
        msg.content = "final answer"
        msg.tool_calls = None
        c = MagicMock()
        c.choices = [MagicMock(message=msg)]
        return c

    @patch("agent.openai_tools.sleep_interruptible", return_value=False)
    def test_429_retries_then_succeeds(self, mock_sleep_interruptible):
        mock_client = MagicMock()
        calls = {"n": 0}

        def _create(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("429 RESOURCE_EXHAUSTED. Quota exceeded. Please retry in 5s.")
            return self._final_answer_response()

        mock_client.chat.completions.create.side_effect = _create
        on_complete = MagicMock()

        with patch("agent.openai_tools.get_config", side_effect=_mock_config):
            result = agent_runner.execute_openai_compatible_llm(
                mock_client, "gpt-4o", [], {}, "hello",
                MagicMock(), "session-1", "msg-1", "messages_out",
                on_complete=on_complete,
            )

        self.assertEqual(result, "final answer")
        self.assertEqual(mock_client.chat.completions.create.call_count, 2)
        # Wait respects the provider's "retry in 5s" hint.
        mock_sleep_interruptible.assert_called_once_with(5.0)
        feedbacks = [c[0][0] for c in on_complete.call_args_list]
        self.assertTrue(any("Rate limit (429)" in f for f in feedbacks))

    @patch("agent.openai_tools.sleep_interruptible", return_value=False)
    def test_429_persistent_raises_after_all_retries(self, mock_sleep_interruptible):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED. rate limit exceeded"
        )

        with self.assertRaises(Exception) as ctx, \
             patch("agent.openai_tools.get_config", side_effect=_mock_config):
            agent_runner.execute_openai_compatible_llm(
                mock_client, "gpt-4o", [], {}, "hello",
                MagicMock(), "session-1", "msg-1", "messages_out",
            )

        self.assertIn("429", str(ctx.exception))
        # 5 attempts -> only the first 4 wait (last attempt re-raises)
        self.assertEqual(mock_sleep_interruptible.call_count, 4)

    def test_non_rate_limit_error_raises_immediately(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("400 Bad Request")

        with self.assertRaises(Exception) as ctx, \
             patch("agent.openai_tools.get_config", side_effect=_mock_config), \
             patch("time.sleep", return_value=None) as mock_sleep:
            agent_runner.execute_openai_compatible_llm(
                mock_client, "gpt-4o", [], {}, "hello",
                MagicMock(), "session-1", "msg-1", "messages_out",
            )

        self.assertIn("400 Bad Request", str(ctx.exception))
        mock_sleep.assert_not_called()


class TestToolSchemaEnum(unittest.TestCase):
    def test_enum_extracted_from_must_be_one_of(self):
        def enum_tool(category: str) -> str:
            """Do something.

            Args:
                category: The folder. Must be one of: 'documents', 'images', 'videos'.
            """
            return category

        schema = agent_runner.convert_to_openai_tool(enum_tool)
        props = schema["function"]["parameters"]["properties"]
        self.assertEqual(props["category"]["enum"], ["documents", "images", "videos"])


if __name__ == "__main__":
    unittest.main()