"""End-to-end tests of the WhatsApp user path on the LangChain stack.

A message goes through the real pipeline: POST /api/webhook -> message_history
-> route_inbound_message -> process_message (prompt, history, RAG, tools) ->
execute_autonomous_loop -> route_llm_call -> run_langchain_llm -> the Baileys
callback. Only the edges are replaced:

    * the Gemini chat model is a scripted fake that records every request;
    * the Baileys HTTP calls are captured instead of sent;
    * the processing thread runs inline, so each POST returns after the reply.

Live runs against the real Gemini workers are in test_user_path_live.py.
"""
import base64
import json
import threading

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import database
from app import app

SECRET = "e2e-secret"
GROUP = "120363000000000001@g.us"
CHANNEL = f"wa_web:{GROUP}"
WORKER = "Rata"
OTHER_WORKER = "Bilu"
MODEL = "gemini-e2e"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class ScriptedGemini(BaseChatModel):
    """Gemini stand-in: returns scripted replies and records each request."""

    script: list = []
    calls: list = []
    default: object = None  # callable(messages) used once the script runs out

    @property
    def _llm_type(self) -> str:
        return "scripted-gemini"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        if self.script:
            reply = self.script.pop(0)
        else:
            reply = self.default or _answer("ok")
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, str):
            reply = AIMessage(content=reply)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        return self


def _answer(text, satisfied=True):
    """A reply in the AgentResponse JSON contract."""
    return json.dumps({
        "user_prompt": "",
        "llm_response": text,
        "is_the_user_request_completely_satisfied": satisfied,
        "critical_system_failure": False,
    })


def _tool_call(name, args, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class FakeBaileys:
    """Captures the HTTP calls the backend makes to the Baileys worker."""

    def __init__(self):
        self.calls = []
        self._n = 0

    def post(self, url, json=None, timeout=None, **kwargs):
        self.calls.append((url.rsplit("/", 1)[-1], json or {}))
        self._n += 1

        class Resp:
            status_code = 200
            text = "ok"

            def __init__(self, msg_id):
                self._msg_id = msg_id

            def json(self):
                return {"status": "sent", "message_id": self._msg_id}

        return Resp(f"bot-msg-{self._n}")

    def sent_texts(self):
        return [body["text"] for kind, body in self.calls if kind == "send"]


class InlineThread:
    """Runs the processing thread inline so a POST returns after the reply."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, **_):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def get_weather(city: str) -> str:
    """Gets the weather forecast for a city."""
    get_weather.calls.append(city)
    return f"Sunny, 25C in {city}"


get_weather.calls = []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def build_env(monkeypatch, tmp_path, model_name=MODEL, api_key="test-key", fake_model=True):
    """Sets up the database, the worker and the fakes; yields nothing.

    With ``fake_model=False`` the real Gemini chat model is built from
    ``model_name`` and ``api_key`` (live tests).
    """
    database.init_db()
    monkeypatch.setenv("LLM_STACK", "langchain")
    for key, value in {
        "WEBHOOK_SECRET": SECRET,
        "REQUIRE_AT_PREFIX": "true",
        "AUTONOMOUS_MODE": "15",
        "TOOL_RELEVANCE_FILTER": "false",
        "HISTORY_RAG_ENABLED": "false",
        "PLAN_BEFORE_EXECUTION": "false",
    }.items():
        database.set_config(key, value)

    conn = database.get_db()
    conn.execute(
        "INSERT INTO llm_config (model_name, provider, api_key, image_input) VALUES (?, ?, ?, 1)",
        (model_name, "Google", database.encrypt_value(api_key)),
    )
    conn.execute(
        "INSERT INTO workers_config (worker_name, worker_model, worker_instructions, is_default, tools_enabled) "
        "VALUES (?, ?, ?, 1, 1)",
        (WORKER, model_name, "You are Rata, the group assistant."),
    )
    conn.execute(
        "INSERT INTO workers_config (worker_name, worker_model, worker_instructions, is_default, tools_enabled) "
        "VALUES (?, ?, ?, 0, 1)",
        (OTHER_WORKER, model_name, "You are Bilu."),
    )
    conn.commit()
    conn.close()

    model = ScriptedGemini(script=[], calls=[])
    built = []
    if fake_model:
        def make_chat_model(model_name, provider=None, api_key=None, **kwargs):
            built.append({"model_name": model_name, "provider": provider, "api_key": api_key, **kwargs})
            return model

        monkeypatch.setattr("agent.lc.models.make_chat_model", make_chat_model)

    baileys = FakeBaileys()
    get_weather.calls.clear()

    def save_attachment(data):
        b64 = data.get("file_base64") or data.get("image_base64")
        if not b64:
            return None
        path = tmp_path / data.get("file_name", "attachment")
        path.write_bytes(base64.b64decode(b64))
        return f"path:{path}"

    monkeypatch.setattr("routes.webhooks.req.post", baileys.post)
    monkeypatch.setattr("routes.webhooks.check_wa_permissions", lambda data, content: (True, None))
    monkeypatch.setattr("routes.webhooks.save_webhook_attachment", save_attachment)
    # Only the router's dispatch runs inline; LangChain keeps real threads.
    monkeypatch.setattr("router.threading", type("T", (), {"Thread": InlineThread}))
    monkeypatch.setattr("agent.message_processor.get_permitted_tools", lambda **kw: [get_weather])

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield type("Env", (), {
            "client": client, "model": model, "baileys": baileys, "built": built,
        })


@pytest.fixture
def env(monkeypatch, tmp_path):
    yield from build_env(monkeypatch, tmp_path)


_msg_seq = iter(range(1, 10_000))


def _post(env, text, sender="5519900000001", name="Julio", history_only=False,
          group=GROUP, **extra):
    msg_id = f"wa-msg-{next(_msg_seq)}"
    payload = {
        "channel_id": f"wa_web:{group}",
        "remote_jid": group,
        "sender_id": sender,
        "sender_name": name,
        "content": text,
        "message_id": msg_id,
        "from_me": False,
        **extra,
    }
    if history_only:
        payload["history_only"] = True
    resp = env.client.post("/api/webhook", json=payload, headers={"X-Webhook-Secret": SECRET})
    assert resp.status_code in (200, 202), resp.get_json()
    return msg_id


def _request_text(messages):
    """Text of every human/system message of one model request."""
    out = []
    for m in messages:
        if isinstance(m.content, str):
            out.append(m.content)
    return "\n".join(out)


def _human_input(messages):
    """The user prompt of the turn: the last human text before the agent steps."""
    texts = [m for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, str)]
    return texts[-1].content


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reply_reaches_the_group_quoting_the_message(env):
    env.model.script = [_answer("Bom dia, Julio!")]
    msg_id = _post(env, f"@{WORKER} bom dia")

    assert env.baileys.sent_texts() == ["Bom dia, Julio!"]
    send = [body for kind, body in env.baileys.calls if kind == "send"][0]
    assert send["jid"] == GROUP
    assert send["quoted_msg_id"] == msg_id
    # The worker's model, provider and key were used.
    assert env.built[0]["model_name"] == MODEL
    assert env.built[0]["api_key"] == "test-key"


def test_model_gets_system_prompt_with_worker_instructions_and_memories(env):
    database.add_user_memory('WhatsApp user "Julio" is the administrator.')
    env.model.script = [_answer("ok")]
    _post(env, f"@{WORKER} oi")

    system = env.model.calls[0][0]
    assert isinstance(system, SystemMessage)
    assert "You are Rata, the group assistant." in system.content
    assert 'WhatsApp user "Julio" is the administrator.' in system.content
    # Gemini with tools: the JSON contract stays in the prompt.
    assert "is_the_user_request_completely_satisfied" in system.content


def test_group_messages_keep_each_sender_and_mark_the_current_one(env):
    _post(env, "alguém sabe a cotação do dólar?", sender="5519911111111", name="Vitor", history_only=True)
    _post(env, "eu queria saber da previsão do tempo", sender="5519922222222", name="Capivara", history_only=True)
    env.model.script = [_answer("Julio, o dólar está R$ 5,00.")]
    _post(env, f"@{WORKER} me responde a pergunta do Vitor", name="Julio")

    prompt = _human_input(env.model.calls[0])
    # Each message on its own line, with its own sender.
    assert "[Message from: Vitor (5519911111111)]\nalguém sabe a cotação do dólar?" in prompt
    assert "dólar?\n\n[Message from: Capivara (5519922222222)]" in prompt
    # The message being answered names who to reply to.
    assert "[Message from: Julio (5519900000001)] [Current message: reply to Julio]" in prompt
    assert prompt.rstrip().endswith("me responde a pergunta do Vitor")


def test_previous_bot_reply_is_an_assistant_turn(env):
    env.model.script = [_answer("Primeira resposta"), _answer("Segunda resposta")]
    _post(env, f"@{WORKER} primeira pergunta")
    _post(env, f"@{WORKER} segunda pergunta")

    second = env.model.calls[1]
    ai_turns = [m.content for m in second if isinstance(m, AIMessage)]
    assert "Primeira resposta" in ai_turns
    # The bot reply is stored once, flagged as the bot's.
    conn = database.get_db()
    rows = conn.execute(
        "SELECT is_bot, sender_name, content FROM message_history WHERE content = 'Primeira resposta'"
    ).fetchall()
    conn.close()
    assert [(r["is_bot"], r["sender_name"]) for r in rows] == [(1, WORKER)]


def test_tool_is_called_and_its_result_reaches_the_model(env):
    env.model.script = [
        _tool_call("get_weather", {"city": "Campinas"}),
        _answer("Em Campinas está ensolarado, 25C."),
    ]
    _post(env, f"@{WORKER} como está o tempo em Campinas?")

    assert get_weather.calls == ["Campinas"]
    assert len(env.model.calls) == 2
    tool_results = [m.content for m in env.model.calls[1] if isinstance(m, ToolMessage)]
    assert tool_results == ["Sunny, 25C in Campinas"]
    assert env.baileys.sent_texts()[-1] == "Em Campinas está ensolarado, 25C."


def test_reflection_reruns_until_satisfied(env):
    env.model.script = [
        _answer("Ainda não terminei", satisfied=False),
        _answer("Pronto, terminei."),
    ]
    _post(env, f"@{WORKER} faça a tarefa")

    assert len(env.model.calls) == 2
    second_prompt = _human_input(env.model.calls[1])
    assert "does not completely answer" in second_prompt
    texts = env.baileys.sent_texts()
    assert any("Agent reflecting (Iteration 1/15)" in t for t in texts)
    assert texts[-1] == "Pronto, terminei."


def test_clarifying_question_is_sent_without_reflection(env):
    env.model.script = [_answer("Para qual cidade?", satisfied=True)]
    _post(env, f"@{WORKER} qual a previsão do tempo?")

    assert len(env.model.calls) == 1
    assert env.baileys.sent_texts() == ["Para qual cidade?"]


def test_image_reaches_the_model(env):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
    env.model.script = [_answer("É uma imagem.")]
    _post(env, f"@{WORKER} o que é isso?", image_base64=png,
          file_mime_type="image/png", file_name="foto.png")

    media = [
        block
        for m in env.model.calls[0] if isinstance(m, HumanMessage) and isinstance(m.content, list)
        for block in m.content
    ]
    assert media and media[0]["type"] == "media"
    assert media[0]["mime_type"] == "image/png"
    assert media[0]["data"].startswith(b"\x89PNG")


def test_step_limit_still_produces_an_answer(env, monkeypatch):
    monkeypatch.setattr("agent.lc.settings.agent_max_iterations", lambda: 2)
    env.model.script = [
        _tool_call("get_weather", {"city": "A"}, "c1"),
        _tool_call("get_weather", {"city": "B"}, "c2"),
        _answer("Consegui o tempo de A e B."),
    ]
    _post(env, f"@{WORKER} tempo em A e B")

    sent = env.baileys.sent_texts()[-1]
    assert sent == "Consegui o tempo de A e B."
    assert "max iterations" not in sent


def test_message_without_mention_is_only_recorded(env):
    _post(env, "conversa normal do grupo", sender="5519911111111", name="Vitor", history_only=True)

    assert env.model.calls == []
    assert env.baileys.sent_texts() == []
    conn = database.get_db()
    row = conn.execute(
        "SELECT sender_name, is_bot FROM message_history WHERE content = 'conversa normal do grupo'"
    ).fetchone()
    conn.close()
    assert (row["sender_name"], row["is_bot"]) == ("Vitor", 0)


# ---------------------------------------------------------------------------
# Concurrency: one agent must not delay or cancel another
# ---------------------------------------------------------------------------

MODEL_LATENCY = 1.0


def _slow_reply_to_sender(messages):
    """Answers after MODEL_LATENCY seconds, naming who the reply is for."""
    import re
    import time

    time.sleep(MODEL_LATENCY)
    prompt = _human_input(messages)
    match = re.search(r"\[Current message: reply to ([^\]]+)\]", prompt)
    return _answer(f"resposta para {match.group(1) if match else '?'}")


@pytest.fixture
def threaded(env, monkeypatch):
    """Real processing threads, a short debounce and a slow model."""
    monkeypatch.setattr("router.threading", threading)
    monkeypatch.setattr("agent.message_processor._DEBOUNCE_SECONDS", 0.5)
    env.model.default = _slow_reply_to_sender
    return env


def _wait_replies(env, count, timeout=20):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        replies = [t for t in env.baileys.sent_texts() if t.startswith("resposta para")]
        if len(replies) >= count:
            return replies
        time.sleep(0.05)
    raise AssertionError(f"expected {count} replies, got {env.baileys.sent_texts()}")


def test_two_agents_in_different_groups_run_in_parallel(threaded):
    import time

    start = time.monotonic()
    _post(threaded, f"@{WORKER} oi", name="Julio", group="120363000000000001@g.us")
    _post(threaded, f"@{OTHER_WORKER} oi", sender="5519911111111", name="Vitor",
          group="120363000000000002@g.us")
    replies = _wait_replies(threaded, 2)
    elapsed = time.monotonic() - start

    assert sorted(replies) == ["resposta para Julio", "resposta para Vitor"]
    # Serial processing would take at least 2 x (debounce + latency) = 3s.
    assert elapsed < 0.5 + MODEL_LATENCY + 1.2, f"agents ran serially ({elapsed:.1f}s)"


def test_messages_from_two_people_in_one_group_are_both_answered(threaded):
    _post(threaded, f"@{WORKER} me ajuda", name="Julio")
    _post(threaded, f"@{OTHER_WORKER} me ajuda também", sender="5519911111111", name="Vitor")

    replies = _wait_replies(threaded, 2)
    assert sorted(replies) == ["resposta para Julio", "resposta para Vitor"]


def test_same_person_to_two_workers_gets_both_answers(threaded):
    _post(threaded, f"@{WORKER} pergunta um")
    _post(threaded, f"@{OTHER_WORKER} pergunta dois")

    replies = _wait_replies(threaded, 2)
    assert replies == ["resposta para Julio", "resposta para Julio"]


def test_rapid_messages_from_one_person_to_one_worker_are_batched(threaded):
    import time

    _post(threaded, f"@{WORKER} primeira parte")
    _post(threaded, f"@{WORKER} segunda parte")
    _wait_replies(threaded, 1)
    time.sleep(0.5 + MODEL_LATENCY)  # room for a second, unwanted reply

    assert len(threaded.model.calls) == 1
    prompt = _human_input(threaded.model.calls[0])
    assert "primeira parte" in prompt and "segunda parte" in prompt


def test_audio_transcription_does_not_hold_the_webhook(env, monkeypatch):
    import time

    def slow_transcribe(content, audio_b64, mimetype):
        time.sleep(1.0)
        return f"{content}\n[Transcription]: @{WORKER} que horas são?"

    monkeypatch.setattr("routes.webhooks.transcribe_webhook_audio", slow_transcribe)
    env.model.script = [_answer("São 10h.")]

    start = time.monotonic()
    _post(env, "[Audio received, waiting for transcription...]", audio_base64="AAAA",
          mimetype="audio/ogg")
    assert time.monotonic() - start < 0.5  # the webhook answered before transcribing

    deadline = time.monotonic() + 10
    while not env.baileys.sent_texts() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert env.baileys.sent_texts() == ["São 10h."]
    assert "que horas são?" in _human_input(env.model.calls[0])


def test_overloaded_gemini_is_retried(env, monkeypatch):
    monkeypatch.setattr("agent.lc.runner.sleep_interruptible", lambda seconds: False)

    def overloaded(messages):
        raise Exception(
            "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
            "experiencing high demand.', 'status': 'UNAVAILABLE'}}"
        )

    env.model.script = [overloaded, _answer("Respondi depois da fila.")]
    _post(env, f"@{WORKER} oi")

    texts = env.baileys.sent_texts()
    assert any("Model overloaded (503) on attempt 1/5" in t for t in texts)
    assert texts[-1] == "Respondi depois da fila."
    # The progress message is deleted once the answer arrives.
    assert any(kind == "delete" for kind, _ in env.baileys.calls)
