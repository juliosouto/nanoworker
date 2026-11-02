"""Tests for the search_chat_history tool (tools/<os>/chat_search.py) and the
history_rag.search_history it relies on, on the conftest temp DB."""

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import database
from database import init_db, insert_message_history, set_config

CHANNEL = "wa_web:gA@g.us"
OTHER = "wa_web:gB@g.us"
OS_FOLDERS = ("linux", "macos", "windows")

# 2026-10-01, 2026-10-15 and 2026-11-01 at noon UTC.
OCT_1, OCT_15, NOV_1 = 1790856000, 1792065600, 1793534400


@pytest.fixture
def chat(monkeypatch):
    init_db()
    # Dates come from the epoch in local time; pin it so the filters are exact.
    monkeypatch.setenv("TZ", "UTC")
    import time
    time.tzset()

    def add(channel, content, ts, sender, message_id=None):
        insert_message_history(
            message_id=message_id or f"{channel}-{ts}",
            channel_id=channel, remote_jid=channel.split(":", 1)[1], is_group=1,
            sender_id=f"{sender.lower()}@s.whatsapp.net", sender_name=sender,
            content=content, msg_timestamp=ts,
        )

    add(CHANNEL, "o orçamento da viagem ficou em 5 mil", OCT_1, "Ana")
    add(CHANNEL, "acho o orçamento alto demais", OCT_15, "Bia")
    add(CHANNEL, "vamos de carro então", NOV_1, "Ana")
    add(OTHER, "orçamento secreto do outro grupo", OCT_15, "Zé")
    add(CHANNEL, "@Nano o que falaram do orçamento?", NOV_1 + 60, "Ana", message_id="req")
    with patch("tools.chat_history._current_channel", return_value=(CHANNEL, "req")):
        yield


def _tool(os_folder="linux"):
    return importlib.import_module(f"tools.{os_folder}.chat_search").search_chat_history


def test_same_tool_on_every_os():
    root = Path(__file__).resolve().parent.parent / "tools"
    sources = {(root / os_folder / "chat_search.py").read_text() for os_folder in OS_FOLDERS}
    assert len(sources) == 1


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_keyword_search_scoped_to_current_chat(chat, os_folder):
    out = _tool(os_folder)("orçamento")
    assert "5 mil" in out and "alto demais" in out
    assert "outro grupo" not in out
    # The request being answered is not a search result.
    assert "o que falaram" not in out


def test_sender_and_date_filters(chat):
    out = _tool()("orçamento", sender="bia")
    assert "alto demais" in out and "5 mil" not in out

    out = _tool()("orçamento", since="2026-10-10", until="2026-10-31")
    assert "alto demais" in out and "5 mil" not in out


def test_filters_without_query_list_newest_first(chat):
    out = _tool()(sender="Ana")
    lines = out.splitlines()
    assert "newest first" in lines[0]
    assert "vamos de carro" in lines[1] and "5 mil" in lines[2]
    assert "[2026-11-01 12:00] Ana:" in lines[1]


def test_hybrid_path_on_allowed_chat(chat):
    """On a RAG-allowed chat the hybrid retriever answers, with the filters."""
    set_config("HISTORY_RAG_ALLOWED_CHANNELS", json.dumps([CHANNEL]))
    from agent.lc.history_rag import vectorize_message

    for row_id in database.get_missing_vector_ids(limit=100):
        vectorize_message(row_id)

    out = _tool()("orçamento", sender="Bia")
    assert "alto demais" in out and "5 mil" not in out
    # The semantic leg returns the nearest vectors whatever the words; the
    # filters still drop Ana's messages from them.
    lines = _tool()("carro", sender="Bia").splitlines()[1:]
    assert lines and all(" Bia: " in line for line in lines)


@pytest.mark.parametrize("kwargs", [
    {},
    {"query": "x", "limit": 0},
    {"query": "x", "limit": 51},
    {"query": "x", "limit": "abc"},
    {"query": "x", "since": "01/10/2026"},
])
def test_invalid_arguments(chat, kwargs):
    assert _tool()(**kwargs).startswith("Error:")


def test_no_current_chat():
    with patch("tools.chat_history._current_channel", return_value=(None, None)):
        assert _tool()("x").startswith("Error: no current chat")


def test_no_match(chat):
    assert _tool()("inexistente") == "No matching messages found in this chat."


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_tool_is_loaded_on_every_os(os_folder):
    import os
    import tools

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(
            os.path.join(os.path.dirname(tools.__file__), os_folder), f"tools.{os_folder}"
        )
        assert "search_chat_history" in {f.__name__ for f in tools.AVAILABLE_TOOLS}
