"""Thinking is turned off explicitly when the worker has it disabled
(agent/thinking_control.py and its wiring in the router and model builders)."""

from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

from agent import thinking_control as tc


@pytest.fixture(autouse=True)
def _clean_minimal_cache():
    tc._MINIMAL_UNSUPPORTED.clear()
    yield
    tc._MINIMAL_UNSUPPORTED.clear()


def _gemini(model):
    return tc.thinking_off_kwargs("google", model).get("thinking_config")


def test_gemini_25_budget_zero_and_pro_minimum():
    assert _gemini("gemini-2.5-flash").thinking_budget == 0
    assert _gemini("gemini-2.5-flash-lite").thinking_budget == 0
    assert _gemini("gemini-2.5-pro").thinking_budget == 128


def test_gemini_3_lowest_level():
    assert _gemini("gemini-3-flash-preview").thinking_level == types.ThinkingLevel.MINIMAL
    assert _gemini("gemini-3.7-flash").thinking_level == types.ThinkingLevel.MINIMAL
    assert _gemini("gemini-3.1-pro-preview").thinking_level == types.ThinkingLevel.LOW


def test_gemini_minimal_rejected_falls_back_to_low():
    assert tc.mark_minimal_unsupported("gemini-3.8-flash") is True
    assert tc.mark_minimal_unsupported("gemini-3.8-flash") is False
    assert _gemini("gemini-3.8-flash").thinking_level == types.ThinkingLevel.LOW


def test_gemma_gets_nothing():
    assert tc.thinking_off_kwargs("google", "gemma-4-31b-it") == {}


@pytest.mark.parametrize("info, expected", [
    ({"mandatory": False, "supported_efforts": ["high", "low", "none"]}, {"effort": "none"}),
    ({"mandatory": True, "supported_efforts": ["max", "high", "low"]}, {"effort": "low"}),
    ({"mandatory": False, "supported_efforts": []}, {"enabled": False}),
    (None, {"enabled": False}),
])
def test_openrouter_uses_the_model_list(info, expected):
    with patch.object(tc, "_openrouter_reasoning_info", return_value=info) as lookup:
        out = tc.thinking_off_kwargs("openrouter", "openrouter/z-ai/glm-5.2:free")
    lookup.assert_called_once_with("z-ai/glm-5.2:free")
    assert out == {"openai_extra_body": {"reasoning": expected}}


def test_openrouter_model_list_is_cached(monkeypatch):
    monkeypatch.setattr(tc, "_openrouter_cache", {"at": 0.0, "models": {}})
    body = b'{"data": [{"id": "a/b", "reasoning": {"mandatory": true}}]}'
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert tc._openrouter_reasoning_info("a/b") == {"mandatory": True}
        assert tc._openrouter_reasoning_info("x/y") is None
    assert urlopen.call_count == 1


def test_openai_compatible_providers():
    assert tc.thinking_off_kwargs("qwen", "qwen-plus") == {"openai_extra_body": {"enable_thinking": False}}
    nim = tc.thinking_off_kwargs("nvidia", "nvidia/deepseek-ai/deepseek-v4.1-flash")
    assert nim == {"openai_extra_body": {"chat_template_kwargs": {"enable_thinking": False, "thinking": False}}}
    assert tc.thinking_off_kwargs("nvidia", "nvidia/openai/gpt-oss-20b") == {
        "openai_extra_body": {"reasoning_effort": "low"}}
    assert tc.thinking_off_kwargs("groq", "qwen/qwen3-32b") == {"openai_extra_body": {"reasoning_effort": "none"}}
    assert tc.thinking_off_kwargs("groq", "llama-3.3-70b") == {}
    assert tc.thinking_off_kwargs("deepseek", "deepseek/deepseek-chat") == {}


def _route(provider, thinking, config_kwargs, model="openrouter/x/y"):
    """Runs route_llm_call on the legacy stack with the provider call mocked;
    returns the config_kwargs the provider received."""
    import agent.llm_router as router

    row = {"provider": provider, "api_key": None, "thinking": thinking, "context_window": None,
           "max_output_tokens": None, "image_output": 0, "text_output": 1, "image_input": None}
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = row
    with patch("database.get_db", return_value=conn), \
            patch.object(router.lc_settings, "stack_enabled", return_value=False), \
            patch.object(router.lc_settings, "graph_flow_enabled", return_value=True), \
            patch.object(router.lc_settings, "openrouter_provider_sort", return_value=""), \
            patch.object(tc, "_openrouter_reasoning_info", return_value=None), \
            patch("agent.llm_providers.call_openrouter_llm", return_value="ok") as call:
        router.route_llm_call(model, [], config_kwargs, "oi", MagicMock(), "s", "m", is_ide=False)
    return call.call_args.args[2]


def test_router_sends_thinking_off_when_the_worker_disables_it():
    sent = _route("openrouter", 1, {})
    assert sent["openai_extra_body"] == {"reasoning": {"enabled": False}}


def test_router_applies_the_worker_level():
    sent = _route("openrouter", 1, {"thinking_level": "high"})
    assert sent["openai_extra_body"] == {"reasoning": {"effort": "high"}}
    assert "thinking_level" not in sent


def test_router_keeps_an_explicit_thinking_config():
    sent = _route("openrouter", 1, {"thinking_config": types.ThinkingConfig(thinking_budget=8000)})
    assert "openai_extra_body" not in sent


def test_router_sends_nothing_for_models_without_thinking():
    assert "openai_extra_body" not in _route("openrouter", 0, {})


def test_router_retries_with_low_when_minimal_is_rejected():
    import agent.llm_router as router

    calls = []

    def fake(*args):
        calls.append(args)
        if len(calls) == 1:
            raise Exception("400 INVALID_ARGUMENT: thinking level MINIMAL is not supported")
        return "ok"

    with patch.object(router, "_route_llm_call", fake):
        assert router.route_llm_call("gemini-3.8-flash", [], {}, "oi", None, "s", "m", False) == "ok"
    assert len(calls) == 2
    assert _gemini("gemini-3.8-flash").thinking_level == types.ThinkingLevel.LOW


def test_router_does_not_retry_other_errors():
    import agent.llm_router as router

    with patch.object(router, "_route_llm_call", side_effect=Exception("500 boom")) as call:
        with pytest.raises(Exception, match="boom"):
            router.route_llm_call("gemini-3-flash-preview", [], {}, "oi", None, "s", "m", False)
    assert call.call_count == 1


def test_legacy_loop_puts_extra_body_in_the_request():
    from agent.openai_tools import execute_openai_compatible_llm

    client = MagicMock()
    reply = client.chat.completions.create.return_value
    reply.choices = [MagicMock()]
    reply.choices[0].message.content = "oi"
    reply.choices[0].message.tool_calls = None
    reply.usage = None
    execute_openai_compatible_llm(
        client, "x/y", [], {"openai_extra_body": {"reasoning": {"enabled": False}}},
        "oi", MagicMock(), "s", "m", "messages_out",
    )
    assert client.chat.completions.create.call_args.kwargs["extra_body"] == {"reasoning": {"enabled": False}}


def test_langchain_models_get_extra_body():
    from agent.lc.models import make_chat_model

    body = {"reasoning": {"enabled": False}}
    model = make_chat_model("openrouter/x/y", provider="openrouter", api_key="k", extra_body=body)
    assert model.extra_body == body
    groq = make_chat_model("qwen/qwen3-32b", provider="groq", api_key="k",
                           extra_body={"reasoning_effort": "none"})
    assert groq.reasoning_effort == "none"


def test_gemini_levels():
    on = lambda model, level: tc.thinking_kwargs("google", model, level)["thinking_config"]
    assert on("gemini-2.5-flash", "low").thinking_budget == 2048
    assert on("gemini-2.5-flash", "high").thinking_budget == 24576
    assert on("gemini-3-flash-preview", "medium").thinking_level == types.ThinkingLevel.MEDIUM
    assert on("gemini-3.1-pro-preview", "minimal").thinking_level == types.ThinkingLevel.LOW


def test_openrouter_level_uses_the_nearest_supported_effort():
    info = {"mandatory": False, "supported_efforts": ["high", "low", "none"]}
    with patch.object(tc, "_openrouter_reasoning_info", return_value=info):
        assert tc.thinking_kwargs("openrouter", "openrouter/a/b", "medium") == {
            "openai_extra_body": {"reasoning": {"effort": "high"}}}
        assert tc.thinking_kwargs("openrouter", "openrouter/a/b", "minimal") == {
            "openai_extra_body": {"reasoning": {"effort": "low"}}}


def test_openai_compatible_levels_on():
    assert tc.thinking_kwargs("qwen", "qwen-plus", "low") == {"openai_extra_body": {"enable_thinking": True}}
    assert tc.thinking_kwargs("nvidia", "nvidia/openai/gpt-oss-20b", "high") == {
        "openai_extra_body": {"reasoning_effort": "high"}}
    assert tc.thinking_kwargs("groq", "qwen/qwen3-32b", "medium") == {
        "openai_extra_body": {"reasoning_effort": "default"}}


@pytest.mark.parametrize("level, enabled, expected", [
    ("high", False, "high"), ("HIGH ", False, "high"), (None, True, "medium"),
    ("", False, "disabled"), ("weird", True, "medium"),
])
def test_normalize_level(level, enabled, expected):
    assert tc.normalize_level(level, enabled) == expected


def test_config_kwargs_carry_the_level():
    from agent.prompt_builder import build_config_kwargs

    assert build_config_kwargs("p", thinking_level="low")["thinking_level"] == "low"
    assert build_config_kwargs("p", thinking_enabled=True)["thinking_level"] == "medium"
    assert build_config_kwargs("p")["thinking_level"] == "disabled"
