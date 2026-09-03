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