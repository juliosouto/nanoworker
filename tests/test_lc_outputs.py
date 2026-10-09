"""Tests for structured output support (Fase 1) — agent.lc.outputs."""
import json

import pytest
from pydantic import ValidationError

from agent.lc.outputs import (
    AgentResponse,
    agent_response_json_schema,
    build_structured_kwargs,
    gemini_response_config,
    json_object_response_format,
    openai_response_format,
    parse_agent_response,
    resolve_provider_for_model,
    structured_output_enabled,
    supports_native_structured,
)


class TestAgentResponse:
    def test_defaults(self):
        r = AgentResponse()
        assert r.llm_response == ""
        assert r.user_prompt == ""
        assert r.execution_plan is None
        assert r.is_the_user_request_completely_satisfied is None
        assert r.critical_system_failure is None

    def test_coerces_string_bools(self):
        r = AgentResponse(llm_response="x", is_the_user_request_completely_satisfied="true",
                          critical_system_failure=" FALSE ")
        assert r.is_the_user_request_completely_satisfied is True
        assert r.critical_system_failure is False

    def test_coerces_int_bools(self):
        r = AgentResponse(llm_response="x", is_the_user_request_completely_satisfied=1,
                          critical_system_failure=0)
        assert r.is_the_user_request_completely_satisfied is True
        assert r.critical_system_failure is False

    def test_unknown_string_becomes_none(self):
        r = AgentResponse(llm_response="x", is_the_user_request_completely_satisfied="maybe")
        assert r.is_the_user_request_completely_satisfied is None

    def test_llm_response_must_be_string(self):
        with pytest.raises(ValidationError):
            AgentResponse(llm_response=123)

    def test_to_legacy_dict_keys(self):
        r = AgentResponse(llm_response="ok", execution_plan="step1")
        d = r.to_legacy_dict()
        assert d["llm_response"] == "ok"
        assert d["execution_plan"] == "step1"
        assert set(d.keys()) == {
            "user_prompt", "execution_plan", "llm_response",
            "is_the_user_request_completely_satisfied", "critical_system_failure",
        }


class TestParseAgentResponse:
    def test_plain_json(self):
        raw = json.dumps({"llm_response": "ok", "is_the_user_request_completely_satisfied": True})
        r = parse_agent_response(raw)
        assert r.llm_response == "ok"
        assert r.is_the_user_request_completely_satisfied is True

    def test_fenced_json(self):
        raw = '```json\n{"llm_response": "ok", "critical_system_failure": false}\n```'
        r = parse_agent_response(raw)
        assert r.llm_response == "ok"
        assert r.critical_system_failure is False

    def test_prose_around_json(self):
        raw = 'Here: {"llm_response": "done", "is_the_user_request_completely_satisfied": "true"} done.'
        r = parse_agent_response(raw)
        assert r.llm_response == "done"
        assert r.is_the_user_request_completely_satisfied is True

    def test_execution_plan_extracted(self):
        raw = json.dumps({"llm_response": "r", "execution_plan": "1) a 2) b",
                          "is_the_user_request_completely_satisfied": True})
        r = parse_agent_response(raw)
        assert r.execution_plan == "1) a 2) b"

    def test_returns_none_without_llm_response(self):
        raw = json.dumps({"is_the_user_request_completely_satisfied": True})
        assert parse_agent_response(raw) is None

    def test_returns_none_without_flag_keys(self):
        # Mirrors the legacy loop gate: both flag keys absent -> not structured.
        raw = json.dumps({"llm_response": "only"})
        assert parse_agent_response(raw) is None

    def test_returns_none_on_prose_only(self):
        assert parse_agent_response("just prose, no json") is None

    def test_returns_none_on_empty(self):
        assert parse_agent_response("") is None
        assert parse_agent_response(None) is None


class TestProviderSupport:
    def test_openai_groq_native(self):
        assert supports_native_structured("openai", "gpt-4o") is True
        assert supports_native_structured("groq", "llama-3.3") is True

    def test_gemini_native(self):
        assert supports_native_structured("gemini", "gemini-2.5-flash") is True
        assert supports_native_structured(None, "gemini-2.5-flash") is True  # default branch

    def test_qwen_deepseek_native(self):
        assert supports_native_structured("qwen", "qwen-plus") is True
        assert supports_native_structured("deepseek", "deepseek-chat") is True

    def test_ollama_nvidia_not_native(self):
        assert supports_native_structured("ollama", "llama3.1") is False
        assert supports_native_structured("nvidia", "nvidia/qwen") is False

    def test_openrouter_only_openai_family(self):
        assert supports_native_structured("openrouter", "openai/gpt-4o") is True
        assert supports_native_structured("openrouter", "meta-llama/llama-3.3-70b:free") is False

    def test_structured_enabled_requires_stack(self, monkeypatch):
        # Fase 6: the production default stack is 'langchain', so with no env
        # the structured contract is enabled for capable providers.
        monkeypatch.delenv("LLM_STACK", raising=False)
        monkeypatch.delenv("LC_STRUCTURED_OUTPUT", raising=False)
        assert structured_output_enabled("openai", "gpt-4o") is True
        # Explicit legacy keeps it off (prompt-based fallback).
        monkeypatch.setenv("LLM_STACK", "legacy")
        assert structured_output_enabled("openai", "gpt-4o") is False

    def test_structured_enabled_auto(self, monkeypatch):
        monkeypatch.setenv("LLM_STACK", "langchain")
        monkeypatch.setenv("LC_STRUCTURED_OUTPUT", "auto")
        assert structured_output_enabled("openai", "gpt-4o") is True
        assert structured_output_enabled("ollama", "llama3.1") is False

    def test_structured_disabled_when_off(self, monkeypatch):
        monkeypatch.setenv("LLM_STACK", "langchain")
        monkeypatch.setenv("LC_STRUCTURED_OUTPUT", "off")
        assert structured_output_enabled("openai", "gpt-4o") is False


class TestKwargsBuilders:
    def test_gemini_config(self):
        cfg = gemini_response_config()
        assert cfg["response_mime_type"] == "application/json"
        assert isinstance(cfg["response_schema"], dict)

    def test_openai_response_format(self):
        fmt = openai_response_format()
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["name"] == "agent_response"
        assert fmt["json_schema"]["schema"]["type"] == "object"

    def test_build_kwargs_by_provider(self):
        assert "response_schema" in build_structured_kwargs("gemini")
        assert "lc_openai_response_format" in build_structured_kwargs("openai")
        assert "lc_openai_response_format" in build_structured_kwargs("qwen")
        assert build_structured_kwargs("ollama") == {}

    def test_schema_covers_contract_fields(self):
        schema = agent_response_json_schema()
        props = schema["properties"]
        for field in ("user_prompt", "llm_response",
                      "is_the_user_request_completely_satisfied",
                      "critical_system_failure"):
            assert field in props

    def test_json_object_response_format(self):
        fmt = json_object_response_format()
        assert fmt == {"type": "json_object"}
        # No schema enforcement: guarantees valid JSON only.
        assert "json_schema" not in fmt

    def test_qwen_deepseek_get_json_object(self):
        # Fix A: providers with looser format get json_object, not json_schema.
        assert build_structured_kwargs("qwen") == {"lc_openai_response_format": {"type": "json_object"}}
        assert build_structured_kwargs("deepseek") == {"lc_openai_response_format": {"type": "json_object"}}


class TestResolveProvider:
    def test_prefix_heuristics(self, mocker):
        mocker.patch("database.get_db", side_effect=RuntimeError("no db"))
        assert resolve_provider_for_model("openai/gpt-4o") == "openai"
        assert resolve_provider_for_model("groq/llama") == "groq"
        assert resolve_provider_for_model("ollama/llama3.1") == "ollama"
        assert resolve_provider_for_model("openrouter/x") == "openrouter"
        assert resolve_provider_for_model("qwen-plus") == "qwen"
        assert resolve_provider_for_model("gemini-2.5-flash") is None  # gemini default
        assert resolve_provider_for_model("") is None

    def test_db_row_wins(self, mocker):
        mock_conn = mocker.MagicMock()
        mock_conn.cursor.return_value.fetchone.return_value = {"provider": "Groq"}
        mocker.patch("database.get_db", return_value=mock_conn)
        assert resolve_provider_for_model("whatever-model") == "groq"
