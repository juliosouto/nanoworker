"""Tests for tools/chat_history.py on a temporary SQLite DB."""

import sqlite3
from unittest.mock import patch

import pytest

from tools import chat_history
from utils.session import current_session_id

GROUP = "120363000000000000@g.us"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions (id TEXT, channel_id TEXT);
        CREATE TABLE messages_in (id TEXT, session_id TEXT, client_message_id TEXT);
        CREATE TABLE message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, channel_id TEXT,
            remote_jid TEXT, is_group BOOLEAN, sender_id TEXT, sender_id_alt TEXT,
            sender_name TEXT, from_me BOOLEAN DEFAULT 0, is_bot BOOLEAN DEFAULT 0,
            content TEXT, msg_timestamp INTEGER, msg_date TEXT, msg_hour INTEGER,
            msg_minute INTEGER, msg_second INTEGER, was_processed BOOLEAN,
            worker_mentioned BOOLEAN, created_at TIMESTAMP);
        INSERT INTO sessions VALUES ('sid', '120363000000000000@g.us');
        INSERT INTO sessions VALUES ('other', 'x@g.us');
        INSERT INTO messages_in VALUES ('m', 'sid', 'req');
    """)
    rows = [
        ("a", GROUP, "Ana", 0, "Vamos marcar o churrasco", 1, 9, 5),
        ("b", GROUP, "Bia", 0, "Sábado   às\n14h", 2, 9, 7),
        ("c", GROUP, None, 1, "Anotado!", 3, 9, 8),
        ("d", "x@g.us", "Zé", 0, "outro grupo", 4, 9, 9),
        ("req", GROUP, "Ana", 0, "@Ratazana resume", 5, 9, 10),
    ]
    for mid, ch, name, bot, text, ts, h, m in rows:
        conn.execute(
            "INSERT INTO message_history (message_id, channel_id, sender_id, sender_name, is_bot,"
            " content, msg_timestamp, msg_date, msg_hour, msg_minute) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, ch, "5511999@s.whatsapp.net", name, bot, text, ts, "2026-10-31", h, m),
        )
    conn.commit()
    conn.close()

    def get_db():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    token = current_session_id.set("sid")
    with patch("database.get_db", get_db):
        yield
    current_session_id.reset(token)


def test_reads_current_chat_oldest_first(db):
    out = chat_history.read_chat_messages(10)
    assert out.splitlines() == [
        "Last 3 message(s) of this chat, oldest first:",
        "[2026-10-31 09:05] Ana: Vamos marcar o churrasco",
        "[2026-10-31 09:07] Bia: Sábado às 14h",
        "[2026-10-31 09:08] Agente: Anotado!",
    ]


def test_count_keeps_the_latest(db):
    out = chat_history.read_chat_messages("2")
    assert "churrasco" not in out and "Bia" in out and "Anotado" in out


def test_other_chat_is_not_read(db):
    assert "outro grupo" not in chat_history.read_chat_messages(500)


@pytest.mark.parametrize("count", [0, 501, "x"])
def test_invalid_count(db, count):
    assert chat_history.read_chat_messages(count).startswith("Error:")


def test_no_session():
    token = current_session_id.set(None)
    try:
        assert chat_history.read_chat_messages().startswith("Error: no current chat")
    finally:
        current_session_id.reset(token)


def test_tool_is_loaded_on_every_os():
    import os
    import tools

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(os.path.dirname(tools.__file__), "tools")
        assert "read_chat_messages" in {f.__name__ for f in tools.AVAILABLE_TOOLS}
