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