"""Tests for the friendly error message used in place of raw LLM API quota errors."""
import unittest

from agent.message_processor import _friendly_llm_error


class TestFriendlyLLMError(unittest.TestCase):
    def test_quota_429_returns_friendly_message(self):
        raw = ("Error calling LLM API: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
               "'message': 'Quota exceeded for metric ... generate_content_free_tier_input_token_count'}}")
        result = _friendly_llm_error(raw)
        self.assertIn("quota (429)", result)
        self.assertIn("resend", result)
        # Raw API payload must not leak to the user
        self.assertNotIn("generate_content_free_tier_input_token_count", result)
        self.assertNotIn("{'error'", result)

    def test_rate_limit_429_returns_friendly_message(self):
        result = _friendly_llm_error("Error calling LLM API: 429 rate limit exceeded")
        self.assertIn("quota (429)", result)

    def test_other_error_keeps_generic_message(self):
        result = _friendly_llm_error("503 Service Unavailable")
        self.assertEqual(result, "Error calling LLM API: 503 Service Unavailable")

    def test_provider_402_returns_friendly_message(self):
        # Exact production payload for a free OpenRouter model (GMICloud host).
        raw = ("Error calling LLM API: Error code: 402 - {'error': {'message': 'Provider returned error', "
               "'code': 402, 'metadata': {'raw': '{\"error\":\"Insufficient balance\","
               "\"reason\":\"access_data_unavailable\"}', 'provider_name': 'GMICloud', 'is_byok': False}}, "
               "'user_id': 'user_3Eopcxyr0HJyWPaTEswXMYH7IEB'}")
        result = _friendly_llm_error(raw)
        self.assertIn("402", result)
        self.assertIn("provider", result.lower())
        # Raw payload must not leak to the user
        self.assertNotIn("GMICloud", result)
        self.assertNotIn("user_3Eop", result)
        self.assertNotIn("user_3Eopcxyr0HJyWPaTEswXMYH7IEB", result)

    def test_own_insufficient_credits_returns_top_up_message(self):
        raw = ("Error calling LLM API: Error code: 402 - {'error': {'message': "
               "'Insufficient credits: buy more credits to use this model', 'code': 402}}")
        result = _friendly_llm_error(raw)
        self.assertIn("credits", result)
        self.assertIn("top up", result.lower())
        self.assertNotIn("buy more credits", result)


if __name__ == "__main__":
    unittest.main()

class TestToolQuery:
    """The tool filter reads the bot's last reply when the message is short."""

    def _history(self):
        from google.genai import types as gt

        return [
            gt.Content(role="user", parts=[gt.Part.from_text(text="[Message from: A]\nmanda o relatório")]),
            gt.Content(role="model", parts=[gt.Part.from_text(text="Quer que eu envie por e-mail?")]),
        ]

    def test_short_message_gets_last_bot_reply(self):
        from agent.message_processor import _tool_query

        assert _tool_query(self._history(), "sim") == "Quer que eu envie por e-mail?\nsim"

    def test_long_message_is_used_alone(self):
        from agent.message_processor import _tool_query

        msg = "qual é a previsão do tempo para amanhã em Campinas?"
        assert _tool_query(self._history(), msg) == msg

    def test_no_bot_reply_keeps_message(self):
        from agent.message_processor import _tool_query

        assert _tool_query([], "sim") == "sim"
