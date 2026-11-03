"""One llm_calls row per model API call, with tokens and cost
(agent/llm_usage.py: log_llm_call and its per-stack readers)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openai
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent import llm_usage

OPENROUTER_USAGE = {
    "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
    "cost": 0.00012, "is_byok": False,
    "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 4},
    "completion_tokens_details": {"reasoning_tokens": 5},
    "cost_details": {"upstream_inference_cost": None},
}


@pytest.fixture(autouse=True)
def db():
    from database import init_db

    init_db()


@pytest.fixture(autouse=True)
def no_lookup():
    with patch.object(llm_usage, "_schedule_generation_lookup") as lookup:
        yield lookup


@pytest.fixture
def ctx():
    with llm_usage.call_context():
        llm_usage.set_call_info(provider="openrouter", model="openrouter/qwen/qwen3-32b",
                                session_id="s1", message_in_id="m1", api_key="k")
        yield


def _rows():
    from database import get_db

    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_calls ORDER BY id")]
    finally:
        conn.close()


def test_usage_fields_openrouter():
    fields = llm_usage.usage_fields(OPENROUTER_USAGE)
    assert {k: v for k, v in fields.items() if k != "usage_json"} == {
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "cached_tokens": 30, "cache_write_tokens": 4, "reasoning_tokens": 5,
        "cost": 0.00012, "is_byok": 0,
    }
    assert '"cost": 0.00012' in fields["usage_json"]


def test_usage_fields_langchain_and_gemini():
    lc = llm_usage.usage_fields({"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                                 "input_token_details": {"cache_read": 2},
                                 "output_token_details": {"reasoning": 1}})
    assert (lc["input_tokens"], lc["cached_tokens"], lc["reasoning_tokens"]) == (7, 2, 1)
    gemini = SimpleNamespace(model_dump=lambda: {
        "prompt_token_count": 50, "candidates_token_count": 9, "thoughts_token_count": 40,
        "cached_content_token_count": None, "total_token_count": 99})
    g = llm_usage.usage_fields(gemini)
    assert (g["input_tokens"], g["output_tokens"], g["reasoning_tokens"], g["total_tokens"]) == (50, 9, 40, 99)
    assert "cost" not in g


def test_openai_response_row(ctx, no_lookup):
    response = openai.types.chat.ChatCompletion.model_validate({
        "id": "gen-1", "object": "chat.completion", "created": 1,
        "model": "qwen/qwen3-32b", "provider": "DeepInfra",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "fetch_news", "arguments": "{}"}}]}}],
        "usage": OPENROUTER_USAGE,
    })
    with llm_usage.usage_worker("Ratazana"), llm_usage.usage_stage("executor"):
        assert llm_usage.log_openai_response(response, latency_ms=850)
    row = _rows()[0]
    assert row["session_id"] == "s1" and row["message_in_id"] == "m1"
    assert row["worker"] == "Ratazana" and row["stage"] == "executor" and row["stack"] == "legacy"
    assert row["provider"] == "openrouter" and row["model"] == "openrouter/qwen/qwen3-32b"
    assert row["response_model"] == "qwen/qwen3-32b" and row["upstream_provider"] == "DeepInfra"
    assert row["generation_id"] == "gen-1" and row["finish_reason"] == "tool_calls"
    assert row["tool_calls"] == 1 and row["latency_ms"] == 850
    assert (row["input_tokens"], row["output_tokens"], row["cached_tokens"]) == (100, 20, 30)
    assert row["cost"] == pytest.approx(0.00012)
    no_lookup.assert_not_called()  # cost and upstream provider already known


def test_langchain_result_row_looks_up_the_missing_provider(ctx, no_lookup):
    message = AIMessage(content="oi", usage_metadata={"input_tokens": 100, "output_tokens": 20,
                                                       "total_tokens": 120})
    result = LLMResult(
        generations=[[ChatGeneration(message=message, generation_info={"finish_reason": "stop"})]],
        llm_output={"token_usage": OPENROUTER_USAGE, "model_name": "qwen/qwen3-32b", "id": "gen-2"},
    )
    row_id = llm_usage.log_langchain_result(result, latency_ms=10)
    row = _rows()[0]
    assert row["stack"] == "langchain" and row["finish_reason"] == "stop"
    assert row["cost"] == pytest.approx(0.00012) and row["reasoning_tokens"] == 5
    no_lookup.assert_called_once_with(row_id, "gen-2", "k")


def test_generation_lookup_fills_the_row(ctx):
    row_id = llm_usage.log_llm_call("langchain", generation_id="gen-3", input_tokens=5)
    body = (b'{"data": {"total_cost": 0.002, "provider_name": "Together", '
            b'"upstream_inference_cost": 0.0019, "is_byok": false, "latency": 900}}')
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert llm_usage.fill_from_generation(row_id, "gen-3", "k", delays=(0,))
    assert urlopen.call_args.args[0].full_url.endswith("/generation?id=gen-3")
    row = _rows()[0]
    assert row["cost"] == pytest.approx(0.002) and row["upstream_provider"] == "Together"
    assert '"latency": 900' in row["generation_json"]


def test_calls_without_numbers_or_tables_are_skipped(ctx):
    assert llm_usage.log_llm_call("legacy", finish_reason="stop") == 0
    with patch("database.get_db", side_effect=Exception("no db")):
        assert llm_usage.log_llm_call("legacy", input_tokens=1) == 0
    assert _rows() == []


def test_callback_logs_each_model_call_with_latency(ctx):
    from agent.lc.runner import FeedbackCallbackHandler

    callback = FeedbackCallbackHandler(MagicMock(), "messages_out", "s1", "m1", False)
    message = AIMessage(content="oi", usage_metadata={"input_tokens": 3, "output_tokens": 2,
                                                       "total_tokens": 5})
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    callback.on_chat_model_start({}, [[]], run_id="r1")
    callback.on_llm_end(result, run_id="r1")
    row = _rows()[0]
    assert (row["input_tokens"], row["output_tokens"]) == (3, 2)
    assert row["latency_ms"] is not None and callback.usage_calls == 1


def test_router_sets_the_call_context():
    import agent.llm_router as router

    seen = {}

    def fake(*args, **kwargs):
        seen.update(llm_usage._call_context.get() or {})
        return "ok"

    row = {"provider": "openrouter", "api_key": None, "thinking": 0, "context_window": None,
           "max_output_tokens": None, "image_output": 0, "text_output": 1, "image_input": None}
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = row
    with patch("database.get_db", return_value=conn), \
            patch.object(router.lc_settings, "stack_enabled", return_value=False), \
            patch.object(router.lc_settings, "graph_flow_enabled", return_value=True), \
            patch("agent.llm_providers.call_openrouter_llm", side_effect=fake):
        router.route_llm_call("openrouter/x/y", [], {}, "oi", MagicMock(), "s9", "m9", is_ide=False)
    assert seen["provider"] == "openrouter" and seen["model"] == "openrouter/x/y"
    assert (seen["session_id"], seen["message_in_id"]) == ("s9", "m9")
    assert llm_usage._call_context.get() is None
