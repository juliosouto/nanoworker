"""The worker's ordered quantization list reaches OpenRouter as
provider.quantizations plus provider.order (agent/quantization_control.py)."""

from unittest.mock import MagicMock, patch

import pytest

from agent import quantization_control as qc

ENDPOINTS = [
    ("deepinfra/fp4", "fp4"),
    ("novita/bf16", "bf16"),
    ("together/fp8", "fp8"),
    ("baseten/fp4/us", "nvfp4"),
    ("chutes", "unknown"),
]


@pytest.fixture(autouse=True)
def _clean_cache():
    qc._endpoints_cache.clear()
    yield
    qc._endpoints_cache.clear()


@pytest.mark.parametrize("value, expected", [
    (None, []), ("", []), ([], []),
    (["FP8", "bf16", "fp8"], ["fp8", "bf16"]),
    ('["int4"]', ["int4"]),
    (["fp8", "q4"], None), ("fp8", None), ({"a": 1}, None),
])
def test_parse_quantizations(value, expected):
    assert qc.parse_quantizations(value) == expected


def test_order_follows_the_worker_preference():
    with patch.object(qc, "_model_endpoints", return_value=ENDPOINTS) as lookup:
        out = qc.quantization_kwargs("openrouter", "openrouter/qwen/qwen3-32b", ["bf16", "fp4"])
    lookup.assert_called_once_with("qwen/qwen3-32b")
    assert out == {"provider": {
        "quantizations": ["bf16", "fp4"],
        # fp4 also covers nvfp4; endpoints of the same level keep the API order.
        "order": ["novita/bf16", "deepinfra/fp4", "baseten/fp4/us"],
    }}


def test_filter_only_when_no_endpoint_matches_or_list_is_unknown():
    with patch.object(qc, "_model_endpoints", return_value=[]):
        assert qc.quantization_kwargs("openrouter", "a/b", ["fp8"]) == {"provider": {"quantizations": ["fp8"]}}


def test_other_providers_and_empty_lists_get_nothing():
    with patch.object(qc, "_model_endpoints") as lookup:
        assert qc.quantization_kwargs("groq", "qwen/qwen3-32b", ["fp8"]) == {}
        assert qc.quantization_kwargs("openrouter", "a/b", []) == {}
    lookup.assert_not_called()


def test_endpoints_are_read_once_and_cached():
    body = b'{"data": {"endpoints": [{"tag": "deepinfra/fp8", "quantization": "fp8"}, {"tag": "x", "quantization": null}]}}'
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert qc._model_endpoints("a/b") == [("deepinfra/fp8", "fp8"), ("x", "unknown")]
        assert qc._model_endpoints("a/b") == [("deepinfra/fp8", "fp8"), ("x", "unknown")]
    assert urlopen.call_count == 1
    assert urlopen.call_args.args[0] == "https://openrouter.ai/api/v1/models/a/b/endpoints"


def test_router_merges_routing_with_the_thinking_settings():
    import agent.llm_router as router
    from agent import thinking_control as tc

    row = {"provider": "openrouter", "api_key": None, "thinking": 1, "context_window": None,
           "max_output_tokens": None, "image_output": 0, "text_output": 1, "image_input": None}
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = row
    with patch("database.get_db", return_value=conn), \
            patch.object(router.lc_settings, "stack_enabled", return_value=False), \
            patch.object(router.lc_settings, "graph_flow_enabled", return_value=True), \
            patch.object(tc, "_openrouter_reasoning_info", return_value=None), \
            patch.object(qc, "_model_endpoints", return_value=ENDPOINTS), \
            patch("agent.llm_providers.call_openrouter_llm", return_value="ok") as call:
        router.route_llm_call("openrouter/x/y", [], {"thinking_level": "high", "quantizations": ["fp8"]},
                              "oi", MagicMock(), "s", "m", is_ide=False)
    sent = call.call_args.args[2]
    assert sent["openai_extra_body"] == {
        "reasoning": {"effort": "high"},
        "provider": {"quantizations": ["fp8"], "order": ["together/fp8"]},
    }
    assert "quantizations" not in sent


def test_config_kwargs_carry_the_list():
    from agent.prompt_builder import build_config_kwargs

    assert build_config_kwargs("p", quantizations='["fp8", "bf16"]')["quantizations"] == ["fp8", "bf16"]
    assert "quantizations" not in build_config_kwargs("p")
