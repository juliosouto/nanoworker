"""Tests for agent.lc.models — the chat-model factory for phase 5.

The factory builds real LangChain chat models, but construction never contacts
a provider, so no network or real keys are needed. Assertions inspect the
resulting model's resolved fields (temperature, max tokens, base URL, kwargs)
to prove parity with the legacy call_*_llm providers.
"""

import unittest
from unittest.mock import patch

from agent.lc.models import (
    PROVIDER_BASE_URLS,
    make_chat_model,
    resolve_provider,
)


class TestResolveProvider(unittest.TestCase):
    """resolve_provider precedence matches route_llm_call exactly."""

    def test_provider_column_wins(self):
        # The configured provider column is the source of truth, even when the
        # model name has a misleading prefix.
        self.assertEqual(resolve_provider("groq", "gemini-2.0"), "groq")
        self.assertEqual(resolve_provider("gemini", "openai/gpt"), "gemini")

    def test_nvidia_prefix_before_others(self):
        # NIM hosts models whose last segment overlaps other providers.
        self.assertEqual(resolve_provider(None, "nvidia/qwen/qwen3"), "nvidia")
        self.assertEqual(resolve_provider(None, "nvidia/openai/gpt-oss"), "nvidia")

    def test_other_prefixes(self):
        self.assertEqual(resolve_provider(None, "qwen-plus"), "qwen")
        self.assertEqual(resolve_provider(None, "groq/llama"), "groq")
        self.assertEqual(resolve_provider(None, "openai/gpt"), "openai")
        self.assertEqual(resolve_provider(None, "ollama/llama"), "ollama")
        self.assertEqual(resolve_provider(None, "openrouter/x"), "openrouter")

    def test_default_is_gemini(self):
        self.assertEqual(resolve_provider(None, "gemini-2.0-flash"), "gemini")
        self.assertEqual(resolve_provider(None, "some-unknown-model"), "gemini")

    def test_empty_model_name_is_gemini(self):
        self.assertEqual(resolve_provider(None, ""), "gemini")

    def test_custom_default(self):
        # lc.outputs.resolve_provider_for_model delegates with default=None to
        # express "no native branch" (route_llm_call's default is Gemini).
        self.assertIsNone(resolve_provider(None, "unknown-model", default=None))
        self.assertIsNone(resolve_provider(None, "", default=None))
        # Known prefixes still win over the custom default.
        self.assertEqual(resolve_provider(None, "qwen-max", default=None), "qwen")


class TestGeminiModel(unittest.TestCase):
    """Gemini → ChatGoogleGenerativeAI with 2.0 default temperature."""

    def test_defaults(self):
        m = make_chat_model("gemini-2.0-flash", provider="gemini", api_key="k")
        self.assertEqual(m.model, "gemini-2.0-flash")
        self.assertEqual(m.temperature, 2.0)

    def test_max_output_tokens(self):
        m = make_chat_model(
            "gemini-2.0-flash", provider="gemini", api_key="k", max_output_tokens=4096
        )
        self.assertEqual(m.max_output_tokens, 4096)

    def test_temperature_override(self):
        m = make_chat_model(
            "gemini-2.0-flash", provider="gemini", api_key="k", temperature=0.7
        )
        self.assertEqual(m.temperature, 0.7)

    def test_thinking_config_forwarded(self):
        # Real callers pass a google-genai ThinkingConfig; a dict is accepted
        # by the ChatGoogleGenerativeAI field validator, so assert the values
        # survive the round-trip.
        m = make_chat_model(
            "gemini-2.0-flash",
            provider="gemini",
            api_key="k",
            thinking_config={"thinking_budget": 8000},
        )
        self.assertEqual(m.thinking_config, {"thinking_budget": 8000})

    def test_json_schema_without_tools(self):
        schema = {"type": "object"}
        m = make_chat_model(
            "gemini-2.0-flash",
            provider="gemini",
            api_key="k",
            gemini_json_mime=True,
            gemini_json_schema=schema,
            has_tools=False,
        )
        self.assertEqual(m.response_mime_type, "application/json")
        self.assertEqual(m.response_schema, schema)

    def test_json_schema_dropped_with_tools(self):
        # Gemini rejects response_schema together with function calling.
        m = make_chat_model(
            "gemini-2.0-flash",
            provider="gemini",
            api_key="k",
            gemini_json_mime=True,
            gemini_json_schema={"type": "object"},
            has_tools=True,
        )
        self.assertEqual(m.response_mime_type, "application/json")
        self.assertIsNone(m.response_schema)

    def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            make_chat_model("gemini-x", provider="gemini", api_key=None)

class TestOpenAICompatModels(unittest.TestCase):
    """openai/qwen/openrouter/nvidia → ChatOpenAI (1.0 default temperature)."""

    def test_openai_default_temperature(self):
        m = make_chat_model("gpt-4o", provider="openai", api_key="k")
        self.assertEqual(m.temperature, 1.0)

    def test_fixed_base_urls(self):
        self.assertEqual(
            make_chat_model("qwen-plus", provider="qwen", api_key="k").openai_api_base,
            PROVIDER_BASE_URLS["qwen"],
        )
        self.assertEqual(
            make_chat_model("x", provider="openrouter", api_key="k").openai_api_base,
            PROVIDER_BASE_URLS["openrouter"],
        )
        self.assertEqual(
            make_chat_model("nvidia/x", provider="nvidia", api_key="k").openai_api_base,
            PROVIDER_BASE_URLS["nvidia"],
        )

    def test_openai_has_no_fixed_base_url(self):
        # Plain OpenAI uses the SDK default endpoint; base_url stays unset.
        self.assertIsNone(
            make_chat_model("gpt-4o", provider="openai", api_key="k").openai_api_base
        )

    def test_response_format_forwarded(self):
        rf = {"type": "json_object"}
        m = make_chat_model("qwen-plus", provider="qwen", api_key="k", response_format=rf)
        self.assertEqual(m.model_kwargs.get("response_format"), rf)

    def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            make_chat_model("gpt-4o", provider="openai", api_key=None)


class TestGroqModel(unittest.TestCase):
    """Groq → ChatGroq with the 1024 default max_tokens (parity call_groq_llm)."""

    def test_default_max_tokens(self):
        m = make_chat_model("llama-3.1", provider="groq", api_key="k")
        self.assertEqual(m.max_tokens, 1024)
        self.assertEqual(m.temperature, 1.0)

    def test_max_output_tokens_override(self):
        m = make_chat_model("llama-3.1", provider="groq", api_key="k", max_output_tokens=2048)
        self.assertEqual(m.max_tokens, 2048)

    def test_response_format_via_model_kwargs(self):
        rf = {"type": "json_schema", "json_schema": {"name": "agent_response"}}
        m = make_chat_model("llama-3.1", provider="groq", api_key="k", response_format=rf)
        self.assertEqual(m.model_kwargs.get("response_format"), rf)

    def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            make_chat_model("llama-3.1", provider="groq", api_key=None)


class TestOllamaModel(unittest.TestCase):
    """Ollama → ChatOpenAI(base_url=OLLAMA_BASE_URL, api_key='ollama')."""

    def test_prefix_stripped_and_base_url(self):
        with patch("database.get_config", return_value="http://localhost:11434/v1"):
            m = make_chat_model("ollama/llama3", provider="ollama")
        self.assertEqual(m.model_name, "llama3")
        self.assertEqual(m.openai_api_base, "http://localhost:11434/v1")

    def test_no_key_required(self):
        # Ollama never raises on a missing api_key (placeholder is used).
        with patch("database.get_config", return_value="http://h/v1"):
            m = make_chat_model("ollama/llama3", provider="ollama", api_key=None)
        self.assertEqual(m.model_name, "llama3")

    def test_prefix_inferred_from_model_name(self):
        with patch("database.get_config", return_value="http://h/v1"):
            m = make_chat_model("ollama/phi", provider=None)
        self.assertEqual(m.model_name, "phi")




if __name__ == "__main__":
    unittest.main()
