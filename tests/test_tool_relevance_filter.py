"""Tests for the opt-in tool relevance filter (TOOL_RELEVANCE_FILTER).

The filter uses ONE lightweight LangChain chat call to narrow the permitted
tool set to what the user's message needs. Core contract: FAIL-OPEN — any
problem (flag off, selector error, unparseable output, empty/unknown selection)
returns the ORIGINAL tool list unchanged.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.lc.tools_lc import filter_tools_by_relevance


def search_web(query: str) -> str:
    """Searches the web. Args: query: the search term."""
    return "results"


def send_whatsapp_file(file_path: str) -> str:
    """Sends a file. Args: file_path: absolute path of the file."""
    return "sent"


def read_file(file_path: str) -> str:
    """Reads a file from disk. Args: file_path: absolute path of the file."""
    return "contents"


ALL_TOOLS = [search_web, send_whatsapp_file, read_file]


def _selector_returning(raw_content):
    """Patches make_chat_model so the selector LLM answers `raw_content`."""
    mock_model = MagicMock()
    mock_model.invoke.return_value = MagicMock(content=raw_content)
    return patch("agent.lc.models.make_chat_model", return_value=mock_model)


class TestToolRelevanceFilter(unittest.TestCase):
    def test_disabled_returns_same_list_and_never_calls_llm(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=False
        ), patch(
            "agent.lc.models.make_chat_model",
            side_effect=AssertionError("must not call the LLM when disabled"),
        ):
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search the web for cats", model_name="gpt-4o"
            )
        self.assertEqual(result, ALL_TOOLS)

    def test_enabled_selects_relevant_subset(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning('["search_web"]'):
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search the web for cats", model_name="gpt-4o"
            )
        self.assertEqual(result, [search_web])

    def test_enabled_parses_array_wrapped_in_prose(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning(
            'Sure! Here are the tools: ["search_web", "send_whatsapp_file"]'
        ):
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search cats and send me the file", model_name="m"
            )
        self.assertEqual(result, [search_web, send_whatsapp_file])

    def test_enabled_multimodal_content_is_flattened(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning('["search_web"]') as mock_make:
            result = filter_tools_by_relevance(
                ALL_TOOLS,
                [{"type": "text", "text": "please search_web for cats"}],
                model_name="m",
            )
        self.assertEqual(result, [search_web])
        # The flattened text reached the selector prompt.
        prompt_text = mock_make.return_value.invoke.call_args[0][0][1][1]
        self.assertIn("please search_web for cats", prompt_text)

    def test_selector_error_fails_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), patch(
            "agent.lc.models.make_chat_model",
            side_effect=RuntimeError("api key missing"),
        ):
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search the web", model_name="gpt-4o"
            )
        self.assertEqual(result, ALL_TOOLS)

    def test_unparseable_output_fails_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning("no tools needed for this"):
            result = filter_tools_by_relevance(ALL_TOOLS, "hello there")
        self.assertEqual(result, ALL_TOOLS)

    def test_unknown_tool_names_fail_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning('["made_up_tool", "another_fake"]'):
            result = filter_tools_by_relevance(ALL_TOOLS, "do the thing")
        self.assertEqual(result, ALL_TOOLS)

    def test_empty_selection_fails_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _selector_returning("[]"):
            result = filter_tools_by_relevance(ALL_TOOLS, "hi")
        self.assertEqual(result, ALL_TOOLS)

    def test_empty_message_fails_open_without_llm(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), patch(
            "agent.lc.models.make_chat_model",
            side_effect=AssertionError("must not call the LLM on empty message"),
        ):
            result = filter_tools_by_relevance(ALL_TOOLS, "   ")
        self.assertEqual(result, ALL_TOOLS)

    def test_empty_tool_list_returns_empty(self):
        self.assertEqual(filter_tools_by_relevance([], "hello"), [])


if __name__ == "__main__":
    unittest.main()