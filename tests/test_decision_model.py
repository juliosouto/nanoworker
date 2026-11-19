"""Decision model (Agent Behavior > Use Decision Model): a quick OpenRouter
model decides whether a message needs the full agent or a direct reply."""
import io
import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

import agent.decision_model as dm


@pytest.fixture
def db(mock_db_path):
    import database
    database.init_db()
    yield database


@pytest.fixture(autouse=True)
def _clear_models_cache():
    dm._models_cache.update(at=0.0, models=[])
    yield
    dm._models_cache.update(at=0.0, models=[])


def _enable(database, model="openrouter/acme/router-mini"):
    database.set_config("DECISION_MODEL_ENABLED", "true")
    database.set_config("DECISION_MODEL", model)


# --------------------------------------------------------------------------
# Decisions API request / parse_route / decide_route
# --------------------------------------------------------------------------

def _answer(choice, probabilities=None, type_="choice", needs_info=None):
    ans = {"type": type_, "choice": choice}
    if probabilities is not None:
        ans["probabilities"] = probabilities
    answers = {"route": ans}
    if needs_info is not None:
        answers["needs_external_info"] = {"type": "noul", "noul": needs_info}
    return {"id": "d1", "model": "acme/router-mini", "answers": answers,
            "usage": {"input_tokens": 120, "output_tokens": 0, "cost": 0.0000024}}


def test_build_decision_request():
    req = dm.build_decision_request("openrouter/acme/router-mini", "bom dia",
                                    tool_names=["web_search"], last_reply="Oi", images=2)
    assert req["model"] == "acme/router-mini"  # prefix stripped for the API
    assert req["state"] == {"message": "bom dia", "attached_images": 2,
                            "previous_reply": "Oi", "agent_tools": ["web_search"]}
    question = req["questions"]["route"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"agent", "direct"}
    assert req["questions"]["needs_external_info"]["type"] == "noul"


def test_build_decision_request_with_tool_descriptions():
    req = dm.build_decision_request("m", "oi", tool_names={"web_search": "Search the web."})
    assert req["state"]["agent_tools"] == {"web_search": "Search the web."}


@pytest.mark.parametrize("message,expected", [
    ("Pesquise o preço do dólar", True),
    ("qual a cotação do euro?", True),
    ("Quem ganhou o jogo ontem?", True),
    ("Quais as notícias de hoje", True),
    ("me manda o arquivo", True),
    ("veja https://exemplo.com", True),
    ("search the latest news", True),
    ("Bom dia! Tudo bem?", False),
    ("obrigado!", False),
    ("traduza: good morning", False),
    ("Quem é o CEO da Nvidia?", False),  # left to the decision model
])
def test_asks_for_agent(message, expected):
    assert dm.asks_for_agent(message) is expected


def test_decide_route_keywords_skip_the_call(db):
    _enable(db)
    db.set_config("OPENROUTER_API_KEY", "sk")
    with patch("agent.decision_model.call_decisions_api") as call:
        assert dm.decide_route("pesquise isso pra mim", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


@pytest.mark.parametrize("response,expected", [
    (_answer("direct"), "direct"),
    (_answer("direct", {"direct": 0.9}, needs_info=0.1), "direct"),
    (_answer("direct", {"direct": 0.9}, needs_info=0.35), "agent"),  # likely needs a search
    (_answer("direct", {"direct": 0.7, "agent": 0.3}), "agent"),  # below 0.75
    (_answer("AGENT"), "agent"),
    (_answer("direct", {"direct": 0.9, "agent": 0.1}), "direct"),
    (_answer("direct", {"direct": 0.55, "agent": 0.45}), "agent"),  # not clear enough
    (_answer("agent", needs_info=0.0), "agent"),
    (_answer("maybe"), None),
    (_answer("direct", type_="noul"), None),
    ({"answers": {}}, None),
    ("not a dict", None),
    (None, None),
])
def test_parse_route(response, expected):
    assert dm.parse_route(response) == expected


def test_decide_route_off_never_calls_a_model(db):
    with patch("agent.decision_model.call_decisions_api") as call:
        assert dm.decide_route("oi", MagicMock(), "s", "m") == "agent"
        db.set_config("DECISION_MODEL_ENABLED", "true")  # enabled, no model
        assert dm.decide_route("oi", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


def test_decide_route_direct(db):
    _enable(db)
    db.set_config("OPENROUTER_API_KEY", "sk-config")
    with patch("agent.decision_model.call_decisions_api",
               return_value=_answer("direct", {"direct": 0.92, "agent": 0.08})) as call:
        route = dm.decide_route("bom dia!", MagicMock(), "s", "m",
                                tool_names=["web_search"], last_reply="Oi", images=1)
    assert route == "direct"
    payload, key = call.call_args.args
    assert key == "sk-config"
    assert payload["model"] == "acme/router-mini"
    assert payload["state"]["message"] == "bom dia!"
    conn = db.get_db()
    row = conn.execute("SELECT stage, model, provider, input_tokens, cost FROM llm_calls").fetchone()
    conn.close()
    assert dict(row) == {"stage": "decision", "model": "openrouter/acme/router-mini",
                         "provider": "openrouter", "input_tokens": 120, "cost": 0.0000024}


def test_decide_route_without_key_is_agent(db):
    _enable(db)
    with patch("agent.decision_model.call_decisions_api") as call:
        assert dm.decide_route("oi", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


@pytest.mark.parametrize("outcome", [RuntimeError("HTTP 400"), {"answers": {}}, _answer("x")])
def test_decide_route_fails_open_to_agent(db, outcome):
    _enable(db)
    db.set_config("OPENROUTER_API_KEY", "sk-config")
    kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
    with patch("agent.decision_model.call_decisions_api", **kwargs):
        assert dm.decide_route("pesquise o preço do dólar", MagicMock(), "s", "m") == "agent"


def test_decide_route_empty_message_is_agent(db):
    _enable(db)
    with patch("agent.decision_model.call_decisions_api") as call:
        assert dm.decide_route("   ", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


def test_call_decisions_api_posts_json():
    opener = _urlopen_returning(_answer("agent"))
    with patch("urllib.request.urlopen", opener):
        out = dm.call_decisions_api({"model": "x"}, "sk-1")
    assert out["answers"]["route"]["choice"] == "agent"
    req = opener.call_args.args[0]
    assert req.full_url == "https://openrouter.ai/api/alpha/decisions"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer sk-1"
    assert json.loads(req.data) == {"model": "x"}


def test_call_decisions_api_http_error_has_detail():
    import urllib.error
    err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"error":"bad model"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError, match="HTTP 400.*bad model"):
            dm.call_decisions_api({}, "k")


# --------------------------------------------------------------------------
# OpenRouter key
# --------------------------------------------------------------------------

def test_openrouter_key_prefers_registered_model(db):
    conn = db.get_db()
    conn.execute("INSERT INTO llm_config (model_name, provider, api_key) VALUES (?, ?, ?)",
                 ("openrouter/x/y", "OpenRouter", db.encrypt_value("sk-registered")))
    conn.commit()
    conn.close()
    db.set_config("OPENROUTER_API_KEY", "sk-config")
    assert dm.openrouter_api_key() == "sk-registered"


def test_openrouter_key_falls_back_to_config(db):
    db.set_config("OPENROUTER_API_KEY", "sk-config")
    assert dm.openrouter_api_key() == "sk-config"


# --------------------------------------------------------------------------
# OpenRouter decision model list
# --------------------------------------------------------------------------

_MODELS_JSON = {"data": [
    {"id": "b/fast:free", "name": "B Fast (free)", "context_length": 8000,
     "architecture": {"output_modalities": ["decisions"]}, "endpoints": ["/api/alpha/decisions"],
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "a/decider", "name": "A Decider", "architecture": {"output_modalities": ["decisions"]},
     "endpoints": ["/api/alpha/decisions", "/api/alpha/extractions"],
     "pricing": {"prompt": "0.000000042", "completion": "0"}},
    {"id": "c/extract-only", "name": "C Extract", "architecture": {"output_modalities": ["decisions"]},
     "endpoints": ["/api/alpha/extractions"]},
    {"id": "d/no-endpoints", "name": "D Old", "architecture": {"output_modalities": ["decisions"]}},
    {"id": "e/chat", "name": "E Chat", "architecture": {"output_modalities": ["text"]}},
    {"name": "no id"},
]}


def _urlopen_returning(payload):
    resp = MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return MagicMock(return_value=resp)


def test_list_decision_models_filters_and_formats():
    opener = _urlopen_returning(_MODELS_JSON)
    with patch("urllib.request.urlopen", opener):
        models = dm.list_openrouter_models()
    assert "output_modalities=decisions" in opener.call_args.args[0].full_url
    assert [m["id"] for m in models] == ["openrouter/a/decider", "openrouter/b/fast:free",
                                         "openrouter/d/no-endpoints"]
    decider, fast, _ = models
    assert decider["prompt_price"] == 0.042 and decider["completion_price"] == 0 and not decider["free"]
    assert fast["free"] and fast["context_length"] == 8000


def test_list_decision_models_cache_and_stale_fallback():
    opener = _urlopen_returning(_MODELS_JSON)
    with patch("urllib.request.urlopen", opener):
        first = dm.list_openrouter_models()
        dm.list_openrouter_models()
    assert opener.call_count == 1  # cached
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        assert dm.list_openrouter_models(force=True) == first  # stale list kept


def test_list_decision_models_raises_without_cache():
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        with pytest.raises(OSError):
            dm.list_openrouter_models()


# --------------------------------------------------------------------------
# Settings API and page
# --------------------------------------------------------------------------

@pytest.fixture
def client(db):
    from app import app
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        yield c


def test_api_lists_models(client, db):
    db.set_config("DECISION_MODEL", "openrouter/a/smart")
    with patch("agent.decision_model.list_openrouter_models", return_value=[{"id": "openrouter/a/smart"}]) as lst:
        resp = client.get('/api/settings/decision_models?refresh=1')
    assert resp.status_code == 200
    assert resp.get_json() == {"models": [{"id": "openrouter/a/smart"}], "selected": "openrouter/a/smart"}
    lst.assert_called_once_with(force=True)


def test_api_lists_models_error(client):
    with patch("agent.decision_model.list_openrouter_models", side_effect=OSError("x")):
        resp = client.get('/api/settings/decision_models')
    assert resp.status_code == 502


def test_api_saves_decision_settings(client, db):
    resp = client.post('/api/settings', json={"decision_model_enabled": True,
                                              "decision_model": "openrouter/b/fast:free"})
    assert resp.status_code == 200
    assert resp.get_json()["ignored_unknown_keys"] == []
    assert dm.decision_settings() == (True, "openrouter/b/fast:free")
    client.post('/api/settings', json={"decision_model_enabled": False})
    assert dm.decision_settings() == (False, "openrouter/b/fast:free")


def test_behavior_page_has_toggle(client, db):
    _enable(db)
    html = client.get('/settings/agent_behavior').get_data(as_text=True)
    assert 'id="decisionModelToggle" checked' in html
    assert 'data-selected="openrouter/acme/router-mini"' in html


# --------------------------------------------------------------------------
# Pipeline: _decide_direct_reply and the direct loop
# --------------------------------------------------------------------------

def _decide(**overrides):
    from agent.message_processor import _decide_direct_reply
    args = dict(worker={"tools_enabled": 1}, is_voice=False, sender_id="5511", message="oi",
                history=[types.Content(role="model", parts=[types.Part.from_text(text="Olá!")])],
                cursor=MagicMock(), session_id="s", message_in_id="m",
                is_wa_group=False, is_wa_private=True)
    args.update(overrides)
    return _decide_direct_reply(**args)


def test_decide_direct_reply_true_when_model_says_direct(db):
    _enable(db)
    with patch("agent.decision_model.decide_route", return_value="direct") as decide:
        assert _decide() is True
    assert decide.call_args.kwargs["last_reply"] == "Olá!"


@pytest.mark.parametrize("overrides", [
    {"is_voice": True},
    {"sender_id": "scheduler"},
    {"worker": {"tools_enabled": 0}},
])
def test_decide_direct_reply_skipped(db, overrides):
    _enable(db)
    with patch("agent.decision_model.decide_route", return_value="direct") as decide:
        assert _decide(**overrides) is False
    decide.assert_not_called()


def test_decide_direct_reply_off_or_failing(db):
    with patch("agent.decision_model.decide_route", return_value="direct") as decide:
        assert _decide() is False  # feature off
    decide.assert_not_called()
    _enable(db)
    with patch("agent.decision_model.decide_route", side_effect=RuntimeError("boom")):
        assert _decide() is False
    with patch("agent.decision_model.decide_route", return_value="agent"):
        assert _decide() is False


@pytest.mark.parametrize("raw,expected", [
    ('{"llm_response": "Oi!", "is_the_user_request_completely_satisfied": false}', "Oi!"),
    ("Oi, tudo bem?", "Oi, tudo bem?"),
])
def test_direct_loop_makes_one_call(db, raw, expected):
    from agent.autonomous_loop import execute_autonomous_loop
    db.set_config("AUTONOMOUS_MODE", "5")
    with patch("agent.autonomous_loop.invoke_llm_with_fallback", return_value=raw) as call, \
         patch("agent.lc.flow.run_agent_flow") as flow, \
         patch("utils.message_utils.newer_stop_requested", return_value=False):
        out = execute_autonomous_loop([], {}, "oi", ["m1"], MagicMock(), "s", "m",
                                      is_ide=False, direct=True)
    assert out == expected
    call.assert_called_once()  # no reflection round, even with "not satisfied"
    flow.assert_not_called()


# --------------------------------------------------------------------------
# Direct reply that needs tools is handed to the full agent
# --------------------------------------------------------------------------

def test_direct_rule_names_the_marker():
    from agent.message_processor import DIRECT_REPLY_RULE, NEEDS_AGENT_MARKER, _needs_agent
    assert NEEDS_AGENT_MARKER in DIRECT_REPLY_RULE
    assert _needs_agent("[[NEEDS_AGENT]]") and _needs_agent(' [[NEEDS_AGENT]]\n')
    assert not _needs_agent("Bom dia!") and not _needs_agent(None)


def _run_process_message(db, decide, loop_results):
    from agent import message_processor as mp

    conn = db.get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-web', 'agent-1', 'web:test')")
    conn.execute("INSERT INTO messages_in (id, session_id, content) VALUES ('m-d', 's-web', '@Quen bom dia')")
    conn.commit()
    conn.close()
    worker = {"worker_name": "Quen", "worker_model": "m", "tools_enabled": 1}
    search = MagicMock(__name__="web_search", __doc__="Search the web.")
    with patch.object(mp.time, "sleep"), \
         patch.object(mp, "resolve_worker_from_content", return_value=worker), \
         patch.object(mp, "_resolve_models", return_value=["m"]), \
         patch.object(mp, "_check_is_admin", return_value=True), \
         patch.object(mp, "_decide_direct_reply", return_value=decide), \
         patch.object(mp, "build_system_prompt", return_value="P"), \
         patch.object(mp, "get_permitted_tools", return_value=[search]), \
         patch("agent.lc.tools_lc.filter_tools_by_relevance", side_effect=lambda t, *a, **k: t), \
         patch.object(mp, "build_config_kwargs", side_effect=lambda **kw: dict(kw)) as bck, \
         patch.object(mp, "execute_autonomous_loop", side_effect=loop_results) as loop:
        _, reply = mp.process_message("m-d", "s-web", "@Quen bom dia")
    return reply, bck, loop


def test_direct_reply_needing_tools_runs_the_agent(db):
    reply, bck, loop = _run_process_message(db, True, ["[[NEEDS_AGENT]]", "Cotação: R$ 5,10"])
    assert reply == "Cotação: R$ 5,10"
    assert loop.call_count == 2
    first, second = loop.call_args_list
    assert first.kwargs["direct"] is True and second.kwargs["direct"] is False
    first_cfg, second_cfg = (c.kwargs for c in bck.call_args_list)
    assert first_cfg["tools"] is None and "[[NEEDS_AGENT]]" in first_cfg["system_prompt"]
    assert [t.__name__ for t in second_cfg["tools"]] == ["web_search"]
    assert "[[NEEDS_AGENT]]" not in second_cfg["system_prompt"]


def test_direct_reply_answered_runs_once(db):
    reply, bck, loop = _run_process_message(db, True, ["Bom dia! Como posso ajudar?"])
    assert reply == "Bom dia! Como posso ajudar?"
    assert loop.call_count == 1


def test_agent_route_runs_once_without_the_rule(db):
    reply, bck, loop = _run_process_message(db, False, ["ok"])
    assert loop.call_count == 1 and loop.call_args.kwargs["direct"] is False
    assert "[[NEEDS_AGENT]]" not in bck.call_args.kwargs["system_prompt"]
