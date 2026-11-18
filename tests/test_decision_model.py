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
# parse_route / decide_route
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('{"route": "direct"}', "direct"),
    ('```json\n{"route": "AGENT"}\n```', "agent"),
    ('{"route": "maybe"}', None),
    ("direct", None),
    ("", None),
    (None, None),
])
def test_parse_route(raw, expected):
    assert dm.parse_route(raw) == expected


def test_decide_route_off_never_calls_a_model(db):
    with patch("agent.llm_router.route_llm_call") as call:
        assert dm.decide_route("oi", MagicMock(), "s", "m") == "agent"
        db.set_config("DECISION_MODEL_ENABLED", "true")  # enabled, no model
        assert dm.decide_route("oi", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


def test_decide_route_direct(db):
    _enable(db)
    db.set_config("OPENROUTER_API_KEY", "sk-config")
    with patch("agent.llm_router.route_llm_call", return_value='{"route": "direct"}') as call:
        route = dm.decide_route("bom dia!", MagicMock(), "s", "m",
                                tool_names=["web_search"], last_reply="Oi", images=1)
    assert route == "direct"
    args, kwargs = call.call_args
    assert args[0] == "openrouter/acme/router-mini"
    assert args[2]["system_instruction"] == dm.DECISION_PROMPT
    assert args[2]["fallback_api_key"] == "sk-config"
    assert "bom dia!" in args[3] and "web_search" in args[3] and "[1 image(s) attached]" in args[3]
    assert kwargs["summarize"] is True


@pytest.mark.parametrize("outcome", [RuntimeError("down"), "not json", '{"route": "x"}'])
def test_decide_route_fails_open_to_agent(db, outcome):
    _enable(db)
    kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
    with patch("agent.llm_router.route_llm_call", **kwargs):
        assert dm.decide_route("pesquise o preço do dólar", MagicMock(), "s", "m") == "agent"


def test_decide_route_empty_message_is_agent(db):
    _enable(db)
    with patch("agent.llm_router.route_llm_call") as call:
        assert dm.decide_route("   ", MagicMock(), "s", "m") == "agent"
    call.assert_not_called()


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


def test_route_llm_call_uses_fallback_key_for_unregistered_model():
    from agent.llm_router import route_llm_call

    conn, cur = MagicMock(), MagicMock()
    cur.fetchone.return_value = None  # not in llm_config
    conn.cursor.return_value = cur
    with patch("agent.llm_router.lc_settings.stack_enabled", return_value=False), \
         patch("database.get_db", return_value=conn), \
         patch("agent.llm_providers.call_openrouter_llm", return_value="ok") as provider:
        route_llm_call("openrouter/acme/router-mini", [], {"fallback_api_key": "sk-fb"}, "hi",
                       MagicMock(), "s", "m", is_ide=False, summarize=True)
    args = provider.call_args.args
    assert args[8] == "sk-fb"
    assert "fallback_api_key" not in args[2]  # never sent to the provider


# --------------------------------------------------------------------------
# OpenRouter model list
# --------------------------------------------------------------------------

_MODELS_JSON = {"data": [
    {"id": "b/fast:free", "name": "B Fast (free)", "context_length": 8000,
     "architecture": {"output_modalities": ["text"]},
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "a/smart", "name": "A Smart", "architecture": {"output_modalities": ["text", "image"]},
     "pricing": {"prompt": "0.0000005", "completion": "0.0000015"}},
    {"id": "c/painter", "name": "C Painter", "architecture": {"output_modalities": ["image"]}},
    {"name": "no id"},
]}


def _urlopen_returning(payload):
    resp = MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return MagicMock(return_value=resp)


def test_list_openrouter_models_filters_and_formats():
    with patch("urllib.request.urlopen", _urlopen_returning(_MODELS_JSON)):
        models = dm.list_openrouter_models()
    assert [m["id"] for m in models] == ["openrouter/a/smart", "openrouter/b/fast:free"]
    smart, fast = models
    assert smart["prompt_price"] == 0.5 and smart["completion_price"] == 1.5 and not smart["free"]
    assert fast["free"] and fast["context_length"] == 8000


def test_list_openrouter_models_cache_and_stale_fallback():
    opener = _urlopen_returning(_MODELS_JSON)
    with patch("urllib.request.urlopen", opener):
        first = dm.list_openrouter_models()
        dm.list_openrouter_models()
    assert opener.call_count == 1  # cached
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        assert dm.list_openrouter_models(force=True) == first  # stale list kept


def test_list_openrouter_models_raises_without_cache():
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
