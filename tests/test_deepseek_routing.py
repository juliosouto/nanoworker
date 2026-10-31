"""Legacy stack: DeepSeek models go to the DeepSeek API, not to Gemini."""
import unittest
from unittest.mock import MagicMock, patch

import agent_runner


class TestDeepSeekRouting(unittest.TestCase):
    def _route(self, provider, model_name):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = {
            "provider": provider, "api_key": "enc", "thinking": 0,
        }
        with patch("database.get_db", return_value=conn), \
             patch("database.decrypt_value", return_value="key"), \
             patch("agent.llm_providers.call_deepseek_llm", return_value="DS") as ds, \
             patch("agent.llm_providers.call_gemini_llm", return_value="GEM") as gem:
            out = agent_runner.route_llm_call(
                model_name, [], {}, "q", MagicMock(), "sid", "mid", is_ide=False
            )
        return out, ds, gem

    def test_provider_column(self):
        out, ds, gem = self._route("DeepSeek", "deepseek-chat")
        self.assertEqual(out, "DS")
        gem.assert_not_called()
        self.assertEqual(ds.call_args.args[8], "key")

    def test_prefix_without_provider(self):
        out, _, gem = self._route(None, "deepseek/deepseek-chat")
        self.assertEqual(out, "DS")
        gem.assert_not_called()

    def test_prefix_is_stripped_and_base_url_set(self):
        from agent import llm_providers

        with patch("openai.OpenAI") as client, \
             patch("agent.llm_providers.execute_openai_compatible_llm", return_value="ok") as run:
            llm_providers.call_deepseek_llm(
                "deepseek/deepseek-chat", [], {}, "q", None, "s", "m", "messages_out", api_key="k"
            )
        self.assertEqual(client.call_args.kwargs["base_url"], "https://api.deepseek.com")
        self.assertEqual(run.call_args.args[1], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
