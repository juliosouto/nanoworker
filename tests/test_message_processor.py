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


if __name__ == "__main__":
    unittest.main()