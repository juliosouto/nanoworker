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


def _creds_patch(provider=None, api_key="test-key"):
    """Keeps credential resolution hermetic (no real DB in unit tests)."""
    return patch(
        "agent.lc.tools_lc._resolve_selector_credentials",
        return_value=(provider, api_key),
    )


def _selector_returning(raw_content):
    """Patches make_chat_model so the selector LLM answers `raw_content`."""
    mock_model = MagicMock()
    mock_model.invoke.return_value = MagicMock(content=raw_content)
    return patch("agent.lc.models.make_chat_model", return_value=mock_model)


def _enabled():
    """Flag ON context (use with _creds_patch + _selector_returning)."""
    return patch("agent.lc.settings.tool_relevance_filter", return_value=True)


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
        with _enabled(), _creds_patch(), _selector_returning(
            '["search_web"]'
        ) as mock_make:
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search the web for cats", model_name="gpt-4o"
            )
        self.assertEqual(result, [search_web])
        # Credentials resolved from llm_config/app_config reach the factory —
        # make_chat_model does NOT resolve keys itself.
        kwargs = mock_make.call_args[1]
        self.assertIsNone(kwargs["provider"])
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["temperature"], 0)

    def test_enabled_parses_array_wrapped_in_prose(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _creds_patch(), _selector_returning(
            'Sure! Here are the tools: ["search_web", "send_whatsapp_file"]'
        ):
            result = filter_tools_by_relevance(
                ALL_TOOLS, "search cats and send me the file", model_name="m"
            )
        self.assertEqual(result, [search_web, send_whatsapp_file])

    def test_enabled_multimodal_content_is_flattened(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _creds_patch(), _selector_returning('["search_web"]') as mock_make:
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
        ), _creds_patch(), patch(
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
        ), _creds_patch(), _selector_returning("no tools needed for this"):
            result = filter_tools_by_relevance(ALL_TOOLS, "hello there")
        self.assertEqual(result, ALL_TOOLS)

    def test_unknown_tool_names_fail_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _creds_patch(), _selector_returning('["made_up_tool", "another_fake"]'):
            result = filter_tools_by_relevance(ALL_TOOLS, "do the thing")
        self.assertEqual(result, ALL_TOOLS)

    def test_empty_selection_fails_open(self):
        with patch(
            "agent.lc.settings.tool_relevance_filter", return_value=True
        ), _creds_patch(), _selector_returning("[]"):
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


class TestSelectorCredentials(unittest.TestCase):
    """_resolve_selector_credentials mirrors route_llm_call's key resolution:
    llm_config row (decrypted) first, GEMINI_API_KEY app_config fallback."""

    def _run(self):
        return filter_tools_by_relevance(
            ALL_TOOLS, "search the web", model_name="test-model"
        )

    @patch("database.decrypt_value", side_effect=lambda v: f"dec({v})")
    @patch("database.get_config", return_value=None)
    @patch("database.get_db")
    def test_key_from_llm_config_row(self, mock_get_db, *_):
        row = {"provider": "openrouter", "api_key": "enc-key"}
        cursor = MagicMock()
        cursor.fetchone.return_value = row
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_db.return_value = conn

        with _enabled(), _selector_returning('["search_web"]') as mock_make:
            result = self._run()

        self.assertEqual(result, [search_web])
        kwargs = mock_make.call_args[1]
        self.assertEqual(kwargs["provider"], "openrouter")
        self.assertEqual(kwargs["api_key"], "dec(enc-key)")

    @patch("database.decrypt_value", side_effect=lambda v: f"dec({v})")
    @patch("database.get_config", return_value="appconfig-gemini-key")
    @patch("database.get_db")
    def test_gemini_falls_back_to_app_config_key(self, mock_get_db, *_):
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # no llm_config row
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_db.return_value = conn

        with _enabled(), _selector_returning('["search_web"]') as mock_make:
            result = self._run()

        self.assertEqual(result, [search_web])
        kwargs = mock_make.call_args[1]
        self.assertIsNone(kwargs["provider"])
        self.assertEqual(kwargs["api_key"], "dec(appconfig-gemini-key)")

    @patch("database.get_db", side_effect=RuntimeError("db down"))
    def test_creds_failure_still_fails_open(self, *_):
        # REAL make_chat_model (not mocked): creds (None, None) -> ValueError
        # ("API Key for Gemini model is not set.") -> caught -> fail-open.
        with _enabled():
            result = self._run()
        self.assertEqual(result, ALL_TOOLS)


if __name__ == "__main__":
    unittest.main()