"""Live end-to-end tests of the WhatsApp user path against a real Gemini worker.

Same pipeline as test_user_path_e2e.py (webhook -> processing -> LangChain
runner -> Baileys callback), but the model is the real Gemini API. They cost
API calls, so they only run when asked:

    NW_LIVE_LLM=1 .venv/bin/python -m pytest tests/test_user_path_live.py -v

The API key comes from NW_LIVE_GEMINI_API_KEY or, when unset, from the Google
row of the local nanoworker.db. NW_LIVE_GEMINI_MODEL picks the model
(default gemini-3.1-flash-lite, the Ratazana worker's model).
"""
import base64
import os
import sqlite3
import struct
import zlib

import pytest

from test_user_path_e2e import WORKER, _post, build_env, get_weather

pytestmark = pytest.mark.skipif(
    os.environ.get("NW_LIVE_LLM") != "1",
    reason="live Gemini tests: set NW_LIVE_LLM=1 to run them",
)

LIVE_MODEL = os.environ.get("NW_LIVE_GEMINI_MODEL", "gemini-3.1-flash-lite")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _live_api_key():
    key = os.environ.get("NW_LIVE_GEMINI_API_KEY")
    if key:
        return key
    import database

    conn = sqlite3.connect(os.path.join(ROOT, "nanoworker.db"))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT model_name, api_key FROM llm_config "
            "WHERE LOWER(provider) IN ('google', 'gemini') AND api_key IS NOT NULL AND api_key != ''"
        ).fetchall()
    finally:
        conn.close()
    rows = sorted(rows, key=lambda r: r["model_name"] != LIVE_MODEL)
    if not rows:
        pytest.skip("no Gemini API key: set NW_LIVE_GEMINI_API_KEY or add a Google model")
    return database.decrypt_value(rows[0]["api_key"])


@pytest.fixture
def live(monkeypatch, tmp_path):
    key = _live_api_key()
    yield from build_env(monkeypatch, tmp_path, model_name=LIVE_MODEL, api_key=key, fake_model=False)


def _reply(env):
    """The final reply delivered to WhatsApp (progress messages excluded)."""
    texts = [t for t in env.baileys.sent_texts() if "Agent reflecting" not in t]
    assert texts, f"no reply sent; Baileys calls: {env.baileys.calls}"
    return texts[-1]


def _assert_clean(reply):
    assert reply.strip()
    assert "Error calling LLM API" not in reply
    assert "max iterations" not in reply
    assert not reply.lstrip().startswith("{"), f"raw JSON reached the user: {reply[:200]}"


def _red_png(size=32):
    """A solid red PNG, built without image libraries."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + b"\xff\x00\x00" * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


def test_live_simple_question(live):
    _post(live, f"@{WORKER} quanto é 7 vezes 8? responda só o número")
    reply = _reply(live)
    _assert_clean(reply)
    assert "56" in reply


def test_live_tool_call(live):
    _post(live, f"@{WORKER} use a ferramenta de previsão do tempo para Campinas e me diga a temperatura")
    reply = _reply(live)
    _assert_clean(reply)
    assert [c.lower() for c in get_weather.calls][:1] == ["campinas"]
    assert "25" in reply


def test_live_answers_the_current_sender(live):
    _post(live, "meu time é o Palmeiras", sender="5519911111111", name="Vitor", history_only=True)
    _post(live, "e eu torço pro Corinthians", sender="5519922222222", name="Capivara", history_only=True)
    _post(live, f"@{WORKER} qual é o meu nome e qual é o time do Vitor? responda curto", name="Julio")
    reply = _reply(live)
    _assert_clean(reply)
    assert "Julio" in reply
    assert "Palmeiras" in reply


def test_live_image_is_seen(live):
    png = base64.b64encode(_red_png()).decode()
    _post(live, f"@{WORKER} qual é a cor desta imagem? responda em uma palavra",
          image_base64=png, file_mime_type="image/png", file_name="cor.png")
    reply = _reply(live)
    _assert_clean(reply)
    assert "vermelh" in reply.lower() or "red" in reply.lower()
